"""Check one source link: fetch, parse, store an observation, update state, raise alerts.

Rules:
- A failed or blocked fetch never writes a price; it updates freshness (last_checked_at, last_error) only.
- A 200 response without a parsed price is BLOCKED when the page looks like a bot challenge, else NO_PRICE.
- Three consecutive BLOCKED results on a domain open a circuit breaker (6 hours) and send one alert.
"""

import hashlib
import json
import logging
import random
import time
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..adapters.base import ParsedProduct, RetailerConfig
from ..adapters.registry import get_adapter
from ..config import get_settings
from ..db import session_scope
from ..fetch.http import FetchResult, domain_of, looks_like_challenge
from ..metrics import FETCH_SECONDS, FETCH_TOTAL
from ..models import FetchRun, Item, Observation, Retailer, SourceLink
from ..timeutil import utcnow
from . import alerts, events, runtime, settings_store

log = logging.getLogger(__name__)

MAX_RETRY_AFTER = 24 * 3600
CONFIDENCE = {"jsonld": 0.95, "css": 0.9, "microdata": 0.85, "opengraph": 0.7, "manual": 1.0, "search": 0.75,
              "embedded_json": 0.9}
CLAUDE_FALLBACK_STATUSES = ("blocked", "no_price", "robots")
SKIP_MODES = ("manual", "search")  # "search": prices come from the cross-store searches only


def payload_hash(parsed: ParsedProduct) -> str:
    data = {k: parsed.to_dict()[k] for k in ("price_cents", "was_price_cents", "in_stock", "seller", "shipping_cents")}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def next_interval_minutes(item: Item, db: Session | None = None) -> int:
    s = get_settings()
    base = s.hot_interval_minutes if item.hot else s.default_interval_minutes
    if db is not None and item.hot:
        cfg = settings_store.get_all(db)
        if events.blackfriday_active(cfg) and item.id in events.blackfriday_item_ids(db):
            base = s.blackfriday_interval_minutes
    j = s.schedule_jitter
    return max(5, int(base * random.uniform(1 - j, 1 + j)))


def schedule_next(src: SourceLink, minutes: int | None = None, db: Session | None = None) -> None:
    src.next_check_at = utcnow() + timedelta(minutes=minutes or next_interval_minutes(src.item, db))


MARKETPLACE_RETAILERS = {"bestbuy.ca", "walmart.ca", "amazon.ca", "newegg.ca", "thebay.com", "staples.ca",
                         "canadiantire.ca", "sportchek.ca", "indigo.ca"}
MARKETPLACE_HINTS = ("marketplace", "third party", "third-party", "sold by", "vendeur")
LEGAL_SUFFIXES = (" inc", " ltd", " ltee", " ltée", " corp", " corporation", " co", " ulc", " lp", " limited")


def seller_type_for(seller: str | None, retailer: Retailer | None) -> str:
    """first_party unless the listed seller is clearly someone else.

    Conservative on purpose: a wrong "marketplace" verdict hides a real first-party price. Only retailers that run
    a marketplace can produce marketplace offers, plus any seller text that says so explicitly.
    """
    if not seller or retailer is None:
        return "first_party"
    s = seller.lower().strip()
    if any(h in s for h in MARKETPLACE_HINTS):
        return f"marketplace:{seller[:100]}"
    if retailer.domain not in MARKETPLACE_RETAILERS:
        return "first_party"
    for suffix in LEGAL_SUFFIXES:
        if s.endswith(suffix) or s.endswith(suffix + "."):
            s = s[: s.rfind(suffix)].strip(" ,.")
    compact = s.replace(" ", "").replace(".ca", "").replace(".com", "").replace("canada", "").replace("'", "")
    stems = {retailer.name.lower(), retailer.domain.split(".")[0]}
    stems = {n.replace(" canada", "").replace(".ca", "").replace(" ", "").replace("'", "") for n in stems}
    if any(st and (st in compact or compact in st) for st in stems):
        return "first_party"
    return f"marketplace:{seller[:100]}"


def normal_condition(value: str | None) -> str:
    v = (value or "new").lower().replace(" ", "_").replace("-", "_")
    return {"openbox": "open_box", "open_box": "open_box", "refurbished": "refurbished", "used": "used"}.get(v, "new")


def counts_for_item(item: Item, condition: str, seller_type: str) -> str | None:
    """Reason this offer does not count for the item's comparisons, or None when it counts."""
    if condition == "refurbished" and item.exclude_refurbished:
        return "refurbished"
    if condition == "used" and item.exclude_used:
        return "used"
    if condition == "open_box" and item.exclude_open_box:
        return "open box"
    if seller_type.startswith("marketplace") and item.exclude_marketplace:
        return "marketplace seller"
    return None


def _currency_ok(parsed: ParsedProduct) -> bool:
    return parsed.currency in (None, "", "CAD")


async def fetch_and_parse(url: str, retailer: Retailer | None, mode: str = "auto", *, etag: str | None = None,
                          last_modified: str | None = None,
                          use_cache: bool = False) -> tuple[FetchResult, ParsedProduct | None, str]:
    """Fetch a product page politely and read its price. Returns (fetch result, parsed product or None, "http")."""
    fetcher = runtime.get_fetcher()
    domain = retailer.domain if retailer else domain_of(url)
    cfg = RetailerConfig(domain=domain, selectors=retailer.selectors if retailer else None)
    adapter = get_adapter(retailer.adapter if retailer else None)
    respect = retailer.respect_robots if retailer else True
    min_interval = retailer.min_interval_seconds if retailer else None
    parsed: ParsedProduct | None = None
    start = time.monotonic()
    result = await fetcher.fetch(url, etag=etag, last_modified=last_modified, respect_robots=respect,
                                 min_interval=min_interval, use_cache=use_cache)
    FETCH_SECONDS.labels(method="http").observe(time.monotonic() - start)
    if result.outcome == "ok" and result.html:
        parsed = adapter.parse(result.html, result.url, cfg)
    return result, parsed, "http"


def record_observation(db: Session, src: SourceLink, *, price_cents: int | None, was_price_cents: int | None,
                       shipping_cents: int | None, in_stock: bool | None, seller: str | None,
                       method: str, phash: str | None = None, seller_type: str = "first_party",
                       condition: str = "new", coupon_cents: int | None = None,
                       parse_confidence: float | None = None, observed_at=None,
                       update_source: bool = True) -> tuple[Observation, dict]:
    """Store an observation, update the source, and return (observation, previous state)."""
    item = src.item
    prev_atl = db.scalar(
        select(func.min(Observation.price_cents)).where(
            Observation.item_id == item.id, Observation.price_cents.is_not(None),
            Observation.condition == "new", Observation.seller_type == "first_party",
            Observation.source_link_id.in_([s.id for s in item.sources if s.status == "confirmed"] or [-1]),
        )
    )
    previous = {"price": src.last_price_cents, "in_stock": src.last_in_stock, "atl": prev_atl}
    now = observed_at or utcnow()
    obs = Observation(item_id=item.id, source_link_id=src.id, observed_at=now, price_cents=price_cents,
                      was_price_cents=was_price_cents, shipping_cents=shipping_cents, in_stock=in_stock,
                      seller=seller, payload_hash=phash, method=method, channel=src.channel or "online",
                      seller_type=seller_type, condition=condition, coupon_cents=coupon_cents,
                      parse_confidence=parse_confidence)
    db.add(obs)
    if update_source:
        src.last_price_cents = price_cents
        src.last_was_price_cents = was_price_cents
        src.last_shipping_cents = shipping_cents
        src.last_in_stock = in_stock
        src.last_seller = seller
        src.last_seller_type = seller_type
        src.last_condition = condition
        src.last_checked_at = utcnow()
        src.last_success_at = utcnow()
        src.last_error = None
        src.consecutive_failures = 0
    db.flush()
    return obs, previous


def run_alerts(db: Session, src: SourceLink, previous: dict, html: str | None = None) -> list:
    from . import protection

    db.refresh(src.item)
    raised = alerts.evaluate_item(db, src.item, None, source=src, previous_price=previous["price"],
                                  previous_in_stock=previous["in_stock"], previous_atl=previous["atl"])
    try:
        raised += protection.on_observation(db, src, html)
    except Exception:  # noqa: BLE001 - never let proof capture break a check
        log.exception("price protection check failed", extra={"source_id": src.id})
    return raised


def register_block(db: Session, retailer: Retailer | None, retry_after: int | None) -> bool:
    """Count a block; open the circuit breaker after N in a row. Returns True when the breaker opened."""
    if retailer is None:
        return False
    s = get_settings()
    now = utcnow()
    retailer.consecutive_blocks = (retailer.consecutive_blocks or 0) + 1
    until = None
    if retry_after:
        until = now + timedelta(seconds=min(retry_after, MAX_RETRY_AFTER))
    opened = False
    if retailer.consecutive_blocks >= s.breaker_blocks:
        breaker = now + timedelta(hours=s.breaker_hours)
        until = max(until, breaker) if until else breaker
        opened = retailer.backoff_until is None or retailer.backoff_until <= now
    if until:
        retailer.backoff_until = until
        retailer.backoff_seconds = int((until - now).total_seconds())
    return opened


def reset_blocks(retailer: Retailer | None) -> None:
    if retailer:
        retailer.consecutive_blocks = 0
        retailer.backoff_seconds = 0
        retailer.backoff_until = None


def apply_autofill(item: Item, name: str | None, brand: str | None, model: str | None, gtin: str | None,
                   image: str | None) -> None:
    """Fill details for items created from a bare URL (paste-a-list, share target, bookmarklet)."""
    import re as _re

    if name:
        item.name = name[:300]
    item.brand = item.brand or brand
    item.model = item.model or model
    if gtin and _re.fullmatch(r"\d{8,14}", gtin) and not item.gtin:
        item.gtin = gtin
    item.image_url = item.image_url or image
    item.autofill = False


async def claude_fallback(db: Session, src: SourceLink, retailer: Retailer | None,
                          force: bool = False) -> dict | None:
    """Read the price through Claude when the store blocked the direct check. Returns the previous state, or None."""
    from . import claude_price

    ok, _ = claude_price.ready()
    if not ok:
        return None
    since = utcnow() - timedelta(hours=claude_price.MIN_HOURS)
    recent = db.scalar(select(func.count()).select_from(Observation).where(
        Observation.source_link_id == src.id, Observation.method == "claude", Observation.observed_at >= since))
    if recent and not force:
        return None
    name = src.title or (src.item.name if src.item else None)
    try:
        found = await claude_price.lookup(src.url, name)
    except claude_price.Unavailable:
        return None
    except Exception:  # noqa: BLE001  never let the fallback break a check
        log.exception("claude price lookup failed", extra={"source_id": src.id})
        return None
    if found is None:
        return None
    if found.title and not src.title:
        src.title = found.title[:500]
    _, previous = record_observation(
        db, src, price_cents=found.price_cents, was_price_cents=found.was_price_cents, shipping_cents=None,
        in_stock=found.in_stock, seller=retailer.name if retailer else None, method="claude",
        parse_confidence=found.confidence)
    src.last_error = None
    return previous


async def check_source(source_id: int, verify: bool = False) -> str:
    """Check one source link. Returns the outcome string.

    ``verify`` (a person pressed Verify): stores whose prices come from searches are read by Claude right now.
    """
    db = session_scope()
    try:
        src = db.get(SourceLink, source_id)
        if src is None or src.status != "confirmed" or src.url.startswith("manual://"):
            return "skipped"
        retailer = src.retailer
        domain = retailer.domain if retailer else domain_of(src.url)
        mode = src.fetch_mode or (retailer.fetch_mode if retailer else "auto")
        if mode == "search" and verify:
            previous = await claude_fallback(db, src, retailer, force=True)
            db.add(FetchRun(source_link_id=src.id, domain=domain, started_at=utcnow(), duration_ms=0,
                            status="ok" if previous is not None else "no_price", method="claude"))
            db.commit()
            if previous is not None:
                run_alerts(db, src, previous, None)
                return "ok"
            return "no_price"
        if mode in SKIP_MODES:
            src.next_check_at = None
            db.commit()
            return "skipped"
        now = utcnow()
        if retailer and retailer.backoff_until and retailer.backoff_until > now:
            # the store is paused after blocks: PriceWatch does not knock again, but Claude may read the price
            previous = await claude_fallback(db, src, retailer)
            src.next_check_at = retailer.backoff_until + timedelta(seconds=random.randint(30, 300))
            if previous is not None:
                db.add(FetchRun(source_link_id=src.id, domain=domain, started_at=now, duration_ms=0, status="ok",
                                method="claude"))
                FETCH_TOTAL.labels(domain=domain, status="ok", method="claude").inc()
                schedule_next(src, None, db)
                db.commit()
                run_alerts(db, src, previous, None)
                return "ok"
            db.commit()
            return "backoff"
        started = utcnow()
        previous = None
        page_html = None
        method = mode
        http_status = None
        elapsed = 0

        result, parsed, method = await fetch_and_parse(
            src.url, retailer, mode, etag=src.etag, last_modified=src.last_modified)
        http_status, elapsed = result.status_code, result.elapsed_ms
        status, error = result.outcome, result.error
        if result.outcome == "ok":
            if parsed and parsed.has_price and _currency_ok(parsed):
                status = "ok"
            elif parsed and parsed.has_price:
                status, error = "currency", f"Price is in {parsed.currency}, not CAD"
            elif looks_like_challenge(result.html):
                status, error = "blocked", "Page loaded but looks like a bot challenge (no price)"
            else:
                status, error = "no_price", "No price found on the page"

        if status == "ok":
            assert parsed is not None
            page_html = result.html
            if method == "http":
                src.etag, src.last_modified = result.etag, result.last_modified
            from ..adapters.base import clean_name

            parsed.name = clean_name(parsed.name, src.url, retailer.name if retailer else None)
            if parsed.name and not src.title:
                src.title = parsed.name[:500]
            if src.item.autofill:
                apply_autofill(src.item, parsed.name, parsed.brand, parsed.mpn, parsed.gtin, parsed.image)
            seller_type = seller_type_for(parsed.seller, retailer)
            condition = normal_condition(parsed.condition)
            _, previous = record_observation(
                db, src, price_cents=parsed.price_cents, was_price_cents=parsed.was_price_cents,
                shipping_cents=parsed.shipping_cents, in_stock=parsed.in_stock, seller=parsed.seller,
                method=method, phash=payload_hash(parsed), seller_type=seller_type, condition=condition,
                parse_confidence=CONFIDENCE.get(parsed.source or "", 0.6))
            reason = counts_for_item(src.item, condition, seller_type)
            if reason:
                status, error = "excluded", f"Recorded, but not compared: listing is {reason}"
                src.last_error = error
        elif status == "not_modified" and src.last_price_cents is not None:
            _, previous = record_observation(
                db, src, price_cents=src.last_price_cents, was_price_cents=src.last_was_price_cents,
                shipping_cents=src.last_shipping_cents, in_stock=src.last_in_stock, seller=src.last_seller,
                method="not_modified", seller_type=src.last_seller_type or "first_party",
                condition=src.last_condition or "new", parse_confidence=1.0)

        if status in CLAUDE_FALLBACK_STATUSES:
            t0 = time.monotonic()
            fallback_prev = await claude_fallback(db, src, retailer)
            if fallback_prev is not None:
                # note the direct block for the breaker, but the price itself came in
                if status == "blocked" and register_block(db, retailer, result.retry_after) and retailer is not None:
                    alerts.domain_blocked(db, retailer)
                previous, status, method, error = fallback_prev, "ok", "claude", None
                elapsed += int((time.monotonic() - t0) * 1000)
                src.consecutive_failures = 0

        db.add(FetchRun(source_link_id=src.id, domain=domain, started_at=started, duration_ms=elapsed,
                        status=status, http_status=http_status, method=method, error=error))
        FETCH_TOTAL.labels(domain=domain, status=status, method=method).inc()

        if status in ("ok", "not_modified", "excluded"):
            if method != "claude":
                reset_blocks(retailer)
        else:
            # never write a price on failure: freshness only
            src.last_checked_at = utcnow()
            src.last_error = error
            src.consecutive_failures = (src.consecutive_failures or 0) + 1
            if status == "blocked":
                retry_after = result.retry_after
                if register_block(db, retailer, retry_after) and retailer is not None:
                    alerts.domain_blocked(db, retailer)
            if status == "not_modified":
                src.etag = src.last_modified = None  # force a full fetch next time
        if src.next_check_at is None or src.next_check_at <= utcnow():
            failures = src.consecutive_failures or 0
            # back off gently on repeated failures: 1x, 2x, 4x the interval, capped at 24 h
            minutes = min(next_interval_minutes(src.item) * (2 ** min(failures, 2)), 24 * 60) if failures else None
            schedule_next(src, minutes, db)
        db.commit()
        if previous is not None:
            run_alerts(db, src, previous, page_html)
        log.info("checked", extra={"source_id": src.id, "domain": domain, "status": status, "method": method})
        return status
    except Exception:
        db.rollback()
        log.exception("check failed", extra={"source_id": source_id})
        return "error"
    finally:
        db.close()
