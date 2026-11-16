"""Weekly flyer matching through Flipp's public item search (opt-in, off by default).

Flyer prices are hints, like forum threads: in-store, regional and time-limited. PriceWatch never records them as
observations. One search per active item per day, through the same polite fetcher (robots.txt, per-domain delay,
backoff). The endpoint is unofficial and may change; when it stops answering, the job logs it and does nothing.
"""

import json
import logging
import re
from datetime import datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import FlyerMatch, Item
from ..timeutil import utcnow
from . import llm_match, runtime, settings_store
from .matching import Candidate, ItemSpec, match

log = logging.getLogger(__name__)
SEARCH_URL = "https://backflipp.wishabi.com/flipp/items/search"
POSTAL_RE = re.compile(r"^[A-Za-z]\d[A-Za-z] ?\d[A-Za-z]\d$")
_last_run: datetime | None = None


def valid_postal(code: str | None) -> str | None:
    code = (code or "").strip()
    return code.replace(" ", "").upper() if POSTAL_RE.match(code) else None


def query_for(item: Item) -> str:
    parts = [item.brand or "", item.model or item.name]
    q = " ".join(p for p in parts if p).strip()
    return q[:80]


def _dt(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(tz=None).replace(tzinfo=None)
    except ValueError:
        return None


def parse_items(text: str) -> list[dict]:
    """Defensive parse of the search response -> [{id, merchant, title, price_cents, valid_from, valid_to}]."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return []
    rows = data.get("items") if isinstance(data, dict) else None
    out = []
    for it in rows or []:
        if not isinstance(it, dict):
            continue
        fid = it.get("flyer_item_id") or it.get("id")
        title, merchant = (it.get("name") or "").strip(), (it.get("merchant_name") or it.get("merchant") or "").strip()
        if not fid or not title or not merchant:
            continue
        price = it.get("current_price")
        try:
            cents = round(float(price) * 100) if price not in (None, "") else None
        except (TypeError, ValueError):
            cents = None
        out.append({"id": str(fid), "merchant": merchant[:200], "title": title[:500], "price_cents": cents,
                    "valid_from": _dt(it.get("valid_from")), "valid_to": _dt(it.get("valid_to")),
                    "url": f"https://flipp.com/en-ca/item/{fid}"})
    return out


def ingest(db: Session, item: Item, rows: list[dict], postal: str) -> list[FlyerMatch]:
    from .alerts import money, raise_alert
    from .users import members_of

    threshold = float(settings_store.get(db, "match_threshold") or 85)
    spec = ItemSpec.from_item(item)
    spec.exclude_marketplace = False
    now = utcnow()
    new = []
    for r in rows:
        if r["valid_to"] and r["valid_to"] < now:
            continue
        cand = Candidate(title=r["title"], url=r["url"], price_cents=r["price_cents"], merchant=r["merchant"])
        res = match(spec, cand, threshold)
        if not res.accepted or llm_match.vetoed(db, spec, cand, res):
            continue
        if db.scalar(select(FlyerMatch.id).where(FlyerMatch.item_id == item.id,
                                                 FlyerMatch.flyer_item_id == r["id"])):
            continue
        fm = FlyerMatch(item_id=item.id, flyer_item_id=r["id"], merchant=r["merchant"], title=r["title"],
                        price_cents=r["price_cents"], valid_from=r["valid_from"], valid_to=r["valid_to"],
                        postal_code=postal, score=res.confidence, url=r["url"])
        db.add(fm)
        db.flush()
        new.append(fm)
        until = f" until {fm.valid_to:%b %d}" if fm.valid_to else ""
        for user in members_of(db, item.list_id):
            cfg = settings_store.get_all(db, user.id)
            at_target = bool(item.target_price_cents and fm.price_cents and fm.price_cents <= item.target_price_cents)
            raise_alert(
                db, item=item, rule="flyer", key=f"flyer:{fm.id}", user_id=user.id,
                title=f"Flyer: {item.name} at {fm.merchant}" + (f" {money(fm.price_cents)}" if fm.price_cents else ""),
                body=f"{fm.title}{until}. Flyer prices are often in-store or regional; check before you go.",
                url=fm.url, cfg=cfg, instant=at_target and bool(cfg.get("alert_flyer")))  # else the daily summary
    db.commit()
    return new


async def poll(db: Session, force: bool = False) -> dict:
    """Search each active item once a day. Does nothing unless flyers_enabled and a valid postal code are set."""
    global _last_run
    cfg = settings_store.get_all(db)
    postal = valid_postal(cfg.get("postal_code"))
    if not cfg.get("flyers_enabled") or not postal:
        return {"enabled": False}
    if not force and _last_run and utcnow() - _last_run < timedelta(hours=23):
        return {"skipped": "ran today"}
    _last_run = utcnow()
    stats = {"items": 0, "matches": 0, "errors": 0}
    fetcher = runtime.get_fetcher()
    for item in db.scalars(select(Item).where(Item.active.is_(True))).all():
        url = f"{SEARCH_URL}?{urlencode({'locale': 'en-ca', 'postal_code': postal, 'q': query_for(item)})}"
        result = await fetcher.fetch(url, respect_robots=True)
        stats["items"] += 1
        if result.outcome != "ok" or not result.html:
            stats["errors"] += 1
            if result.outcome in ("blocked", "robots"):
                log.info("flyer search stopped", extra={"outcome": result.outcome})
                break
            continue
        rows = parse_items(result.html)
        if llm_match.enabled(db):
            spec = ItemSpec.from_item(item)
            spec.exclude_marketplace = False
            threshold = float(settings_store.get(db, "match_threshold") or 85)
            cands = [Candidate(title=r["title"], url=r["url"], price_cents=r["price_cents"], merchant=r["merchant"])
                     for r in rows]
            await llm_match.prefetch(db, [(spec, c, match(spec, c, threshold)) for c in cands])
        stats["matches"] += len(ingest(db, item, rows, postal))
    log.info("flyer poll", extra=stats)
    return stats


def for_item(db: Session, item_id: int) -> list[dict]:
    now = utcnow()
    rows = db.scalars(select(FlyerMatch).where(FlyerMatch.item_id == item_id)
                      .order_by(FlyerMatch.price_cents.is_(None), FlyerMatch.price_cents)).all()
    return [{"id": f.id, "merchant": f.merchant, "title": f.title, "price_cents": f.price_cents,
             "valid_from": f.valid_from, "valid_to": f.valid_to, "url": f.url, "score": f.score,
             "current": f.valid_to is None or f.valid_to >= now} for f in rows]
