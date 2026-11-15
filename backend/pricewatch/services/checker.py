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
from ..fetch import browser
from ..fetch.http import FetchResult, domain_of, looks_like_challenge
from ..metrics import FETCH_SECONDS, FETCH_TOTAL
from ..models import FetchRun, Item, Observation, Retailer, SourceLink
from ..timeutil import utcnow
from . import alerts, events, keepa, runtime, settings_store

log = logging.getLogger(__name__)

MAX_RETRY_AFTER = 24 * 3600
CONFIDENCE = {"jsonld": 0.95, "css": 0.9, "microdata": 0.85, "opengraph": 0.7, "keepa": 0.99,
              "changedetection": 0.9, "manual": 1.0}
SKIP_MODES = ("manual", "changedetection")


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


async def fetch_and_parse(url: str, retailer: Retailer | None, mode: str, *, etag: str | None = None,
                          last_modified: str | None = None, use_cache: bool = False,
                          allow_browser: bool = True) -> tuple[FetchResult, ParsedProduct | None, str]:
    """Return (fetch result, parsed product or None, method used)."""
    s = get_settings()
    fetcher = runtime.get_fetcher()
    domain = retailer.domain if retailer else domain_of(url)
    cfg = RetailerConfig(domain=domain, selectors=retailer.selectors if retailer else None)
    adapter = get_adapter(retailer.adapter if retailer else None)
    respect = retailer.respect_robots if retailer else True
    min_interval = retailer.min_interval_seconds if retailer else None
    result: FetchResult
    parsed: ParsedProduct | None = None
    method = "http"

    if mode != "browser":
        start = time.monotonic()
        result = await fetcher.fetch(url, etag=etag, last_modified=last_modified, respect_robots=respect,
                                     min_interval=min_interval, use_cache=use_cache)
        FETCH_SECONDS.labels(method="http").observe(time.monotonic() - start)
        if result.outcome == "ok" and result.html:
            parsed = adapter.parse(result.html, result.url, cfg)
        if result.outcome in ("ok", "not_modified", "robots", "blocked") and (
            result.outcome != "ok" or (parsed and parsed.has_price)
        ):
            return result, parsed, method
        if mode == "http" or not (s.browser_enabled and allow_browser):
            return result, parsed, method
    else:
        result = FetchResult(url=url, outcome="error")
        if not s.browser_enabled:
            result.error = "Browser mode requested but PRICEWATCH_BROWSER_ENABLED is false"
            return result, None, "browser"
        if respect and not await fetcher.allowed(url):
            return FetchResult(url=url, outcome="robots", error="Disallowed by robots.txt"), None, "browser"

    method = "browser"
    start = time.monotonic()
    try:
        async with runtime.browser_lock(domain):
            html = await browser.render(url, s.browser_ws, s.browser_timeout, fetcher.user_agent,
                                        s.data_dir / "screenshots")
        parsed = adapter.parse(html, url, cfg)
        result = FetchResult(url=url, outcome="ok", status_code=200, html=html,
                             elapsed_ms=int((time.monotonic() - start) * 1000))
    except Exception as exc:  # noqa: BLE001
        result = FetchResult(url=url, outcome="error", error=f"browser: {type(exc).__name__}: {exc}",
                             elapsed_ms=int((time.monotonic() - start) * 1000))
    FETCH_SECONDS.labels(method="browser").observe(time.monotonic() - start)
    return result, parsed, method


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


async def _check_keepa(db: Session, src: SourceLink) -> tuple[str, str | None, dict | None]:
    key = get_settings().keepa_api_key
    if not key:
        return "needs_keepa", "Amazon.ca needs a Keepa API key (KEEPA_API_KEY); add prices by hand meanwhile", None
    asin = src.external_id or keepa.asin_from_url(src.url)
    if not asin:
        return "no_price", "No ASIN found in the Amazon URL", None
    src.external_id = asin
    first = src.last_success_at is None
    try:
        product = await keepa.fetch_product(key, asin, history=first)
    except keepa.KeepaError as exc:
        return "error", str(exc), None
    item = src.item
    if first:
        seed_keepa_history(db, src, product)
        if item.autofill:
            apply_autofill(item, product.title, product.brand, product.model, product.gtin, product.image)
    if product.amazon_price_cents:
        price, seller_type = product.amazon_price_cents, "first_party"
    elif product.buybox_price_cents:
        price, seller_type = product.buybox_price_cents, "marketplace:Amazon buy box"
    else:
        src.last_in_stock = False
        return "out_of_stock", "No Amazon or buy box offer right now", None
    _, previous = record_observation(
        db, src, price_cents=price, was_price_cents=product.list_price_cents
        if product.list_price_cents and product.list_price_cents > price else None,
        shipping_cents=None, in_stock=True, seller="Amazon.ca" if seller_type == "first_party" else None,
        method="keepa", seller_type=seller_type, parse_confidence=CONFIDENCE["keepa"])
    if product.title and not src.title:
        src.title = product.title[:500]
    return "ok", None, previous


def seed_keepa_history(db: Session, src: SourceLink, product: keepa.KeepaProduct) -> int:
    """Seed the seasonal window with Amazon-as-seller history so the seasonal low is meaningful on day one."""
    cfg = settings_store.get_all(db)
    since = events.season_start(cfg, utcnow())
    count = 0
    for at, price in product.amazon_history:
        if at < since or price is None:
            continue
        record_observation(db, src, price_cents=price, was_price_cents=None, shipping_cents=None, in_stock=True,
                           seller="Amazon.ca", method="keepa", parse_confidence=CONFIDENCE["keepa"],
                           observed_at=at, update_source=False)
        count += 1
    return count


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


async def check_source(source_id: int) -> str:
    """Check one source link. Returns the outcome string."""
    db = session_scope()
    try:
        src = db.get(SourceLink, source_id)
        if src is None or src.status != "confirmed" or src.url.startswith("manual://"):
            return "skipped"
        retailer = src.retailer
        domain = retailer.domain if retailer else domain_of(src.url)
        mode = src.fetch_mode or (retailer.fetch_mode if retailer else "auto")
        if mode in SKIP_MODES:
            src.next_check_at = None
            db.commit()
            return "skipped"
        now = utcnow()
        if retailer and retailer.backoff_until and retailer.backoff_until > now:
            src.next_check_at = retailer.backoff_until + timedelta(seconds=random.randint(30, 300))
            db.commit()
            return "backoff"
        started = utcnow()
        previous = None
        page_html = None
        method = mode
        http_status = None
        elapsed = 0

        if mode == "keepa":
            t0 = time.monotonic()
            status, error, previous = await _check_keepa(db, src)
            elapsed = int((time.monotonic() - t0) * 1000)
        else:
            allow_browser = bool(settings_store.get(db, "browser_fallback"))
            result, parsed, method = await fetch_and_parse(
                src.url, retailer, mode, etag=src.etag, last_modified=src.last_modified, allow_browser=allow_browser)
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

        db.add(FetchRun(source_link_id=src.id, domain=domain, started_at=started, duration_ms=elapsed,
                        status=status, http_status=http_status, method=method, error=error))
        FETCH_TOTAL.labels(domain=domain, status=status, method=method).inc()

        if status in ("ok", "not_modified", "excluded"):
            reset_blocks(retailer)
        else:
            # never write a price on failure: freshness only
            src.last_checked_at = utcnow()
            src.last_error = error
            src.consecutive_failures = (src.consecutive_failures or 0) + 1
            if status == "blocked" and mode != "keepa":
                retry_after = result.retry_after if mode != "keepa" else None
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
