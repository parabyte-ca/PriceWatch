"""Post-purchase price protection: watch the retailer after you buy, alert on a claimable drop, keep proof."""

import hashlib
import io
import json
import logging
import zipfile
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Item, Observation, ProofCapture, Purchase, SourceLink
from ..timeutil import utcnow
from . import events, settings_store
from .policies import policy_for

log = logging.getLogger(__name__)
OPEN = ("watching", "claimable")


def terms(db: Session, domain: str | None, purchased_on: date, member: bool,
          badged: bool) -> tuple[int, date | None, str | None]:
    """(days, protected until, basis) from the retailer's policy. Nothing when the policy offers no protection."""
    policy = policy_for(db, domain)
    if policy is None or not policy.enabled:
        return 0, None, None
    days, until, basis = 0, None, None
    if policy.own_price_adjustment:
        days = (policy.member_window_days if member and policy.member_window_days else policy.window_days) or 0
        if days:
            until = purchased_on + timedelta(days=days)
            basis = f"{days}-day price adjustment"
    bf_start, bf_end = events.EVENTS_2026["black_friday_week"]
    if policy.event_guarantee and badged and bf_start <= purchased_on <= bf_end:
        if until is None or bf_end > until:
            until = bf_end
            days = (bf_end - purchased_on).days
            basis = "Black Friday Price Guarantee (badged item)"
    return days, until, basis


def _artifact_dir(purchase_id: int):
    path = get_settings().data_dir / "artifacts" / "proof" / str(purchase_id) / utcnow().strftime("%Y%m%dT%H%M%SZ")
    path.mkdir(parents=True, exist_ok=True)
    return path


def capture(db: Session, purchase: Purchase, src: SourceLink, obs: Observation, html: str | None) -> ProofCapture:
    folder = _artifact_dir(purchase.id)
    sha = None
    if html:
        data = html.encode("utf-8", errors="replace")
        sha = hashlib.sha256(data).hexdigest()
        (folder / "page.html").write_bytes(data)
    local = events.local_now(obs.observed_at)
    meta = {
        "purchase_id": purchase.id, "retailer": purchase.retailer_name, "url": src.url, "channel": src.channel,
        "observed_at_utc": obs.observed_at.isoformat() + "Z", "observed_at_local": local.isoformat(),
        "price_cents": obs.price_cents, "seller": obs.seller, "seller_type": obs.seller_type,
        "condition": obs.condition, "fetch_method": obs.method, "page_sha256": sha,
        "paid_cents": purchase.price_cents, "purchased_on": purchase.purchased_on.isoformat(),
    }
    (folder / "proof.json").write_text(json.dumps(meta, indent=2))
    cap = ProofCapture(purchase_id=purchase.id, observation_id=obs.id, url=src.url, price_cents=obs.price_cents,
                       seller=obs.seller, page_sha256=sha, path=str(folder.relative_to(get_settings().data_dir)))
    db.add(cap)
    db.flush()
    return cap


def matching_purchases(db: Session, src: SourceLink) -> list[Purchase]:
    today = events.local_now().date()
    domain = src.retailer.domain if src.retailer else None
    rows = db.scalars(select(Purchase).where(Purchase.item_id == src.item_id, Purchase.status.in_(OPEN),
                                             Purchase.protection_until >= today)).all()
    return [p for p in rows if p.source_link_id == src.id or (domain and p.retailer_domain == domain
                                                               and p.channel == (src.channel or "online"))]


def on_observation(db: Session, src: SourceLink, html: str | None = None) -> list:
    """Check open purchases against the newest observation for this source; capture proof and alert."""
    from .alerts import money, raise_alert

    obs = db.scalar(select(Observation).where(Observation.source_link_id == src.id)
                    .order_by(Observation.observed_at.desc(), Observation.id.desc()).limit(1))
    if obs is None or obs.price_cents is None or obs.condition != "new" or obs.seller_type != "first_party":
        return []
    raised = []
    min_claim = int(settings_store.get(db, "min_claim_cents") or 0)
    for p in matching_purchases(db, src):
        if obs.price_cents > p.price_cents - min_claim:
            continue
        if p.lowest_seen_cents is not None and obs.price_cents >= p.lowest_seen_cents:
            continue  # already alerted at this level or lower
        p.lowest_seen_cents, p.lowest_seen_at, p.status = obs.price_cents, obs.observed_at, "claimable"
        capture(db, p, src, obs, html)
        diff = p.price_cents - obs.price_cents
        item = db.get(Item, p.item_id)
        alert = raise_alert(
            db, item=item, rule="protection", key=f"prot:{p.id}:{obs.price_cents}", user_id=p.user_id,
            title=f"Claim {money(diff)} back: {item.name if item else 'purchase'}",
            body=(f"{p.retailer_name} now sells it for {money(obs.price_cents)}; you paid {money(p.price_cents)} on "
                  f"{p.purchased_on:%b %d}. {p.protection_basis or 'Price protection'} until {p.protection_until:%b %d}. "
                  "Proof saved in PriceWatch (Purchases)."),
            url=src.url)
        if alert:
            raised.append(alert)
    db.commit()
    return raised


def expire(db: Session) -> int:
    today = events.local_now().date()
    rows = db.scalars(select(Purchase).where(Purchase.status.in_(OPEN), Purchase.protection_until < today)).all()
    for p in rows:
        p.status = "expired"
    db.commit()
    return len(rows)


def proof_zip(db: Session, purchase: Purchase) -> bytes:
    base = get_settings().data_dir
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        summary = {
            "item": db.get(Item, purchase.item_id).name, "retailer": purchase.retailer_name, "channel": purchase.channel,
            "paid_cents": purchase.price_cents, "purchased_on": purchase.purchased_on.isoformat(),
            "order_ref": purchase.order_ref, "protection_until": purchase.protection_until.isoformat()
            if purchase.protection_until else None, "protection_basis": purchase.protection_basis,
            "lowest_seen_cents": purchase.lowest_seen_cents, "generated_at_utc": utcnow().isoformat() + "Z",
        }
        z.writestr("summary.json", json.dumps(summary, indent=2))
        caps = db.scalars(select(ProofCapture).where(ProofCapture.purchase_id == purchase.id)
                          .order_by(ProofCapture.captured_at)).all()
        for cap in caps:
            folder = (base / cap.path) if cap.path else None
            if folder and folder.is_dir():
                for f in folder.iterdir():
                    z.write(f, f"{folder.name}/{f.name}")
    return buf.getvalue()


async def add_screenshots(db: Session, src: SourceLink) -> int:
    """Best effort: add a browser screenshot to proof captured in the last few minutes for this source's purchases."""
    from ..fetch import browser
    from . import runtime

    s = get_settings()
    if not s.browser_enabled:
        return 0
    since = utcnow() - timedelta(minutes=10)
    caps = db.scalars(select(ProofCapture).where(ProofCapture.url == src.url, ProofCapture.screenshot.is_(False),
                                                 ProofCapture.captured_at >= since)).all()
    done = 0
    for cap in caps:
        folder = s.data_dir / cap.path if cap.path else None
        if folder is None:
            continue
        try:
            domain = src.retailer.domain if src.retailer else ""
            async with runtime.browser_lock(domain):
                png = await browser.screenshot(src.url, s.browser_ws, s.browser_timeout, runtime.get_fetcher().user_agent)
            (folder / "screenshot.png").write_bytes(png)
            meta = folder / "proof.json"
            if meta.is_file():
                data = json.loads(meta.read_text())
                data["screenshot_sha256"] = hashlib.sha256(png).hexdigest()
                data["screenshot_taken_utc"] = utcnow().isoformat() + "Z"
                meta.write_text(json.dumps(data, indent=2))
            cap.screenshot = True
            done += 1
        except Exception:  # noqa: BLE001
            log.warning("proof screenshot failed", extra={"url": src.url})
    db.commit()
    return done
