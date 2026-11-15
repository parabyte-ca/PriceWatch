"""Check one source link: fetch, parse, store an observation, update state, raise alerts."""

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
from ..fetch.http import FetchResult, domain_of
from ..metrics import FETCH_SECONDS, FETCH_TOTAL
from ..models import FetchRun, Item, Observation, Retailer, SourceLink
from ..timeutil import utcnow
from . import alerts, runtime, settings_store
from .summary import summarize_items

log = logging.getLogger(__name__)

MIN_BACKOFF = 15 * 60
MAX_BACKOFF = 24 * 3600


def payload_hash(parsed: ParsedProduct) -> str:
    data = {k: parsed.to_dict()[k] for k in ("price_cents", "was_price_cents", "in_stock", "seller", "shipping_cents")}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def next_interval_minutes(item: Item) -> int:
    s = get_settings()
    base = s.hot_interval_minutes if item.hot else s.default_interval_minutes
    return int(base * random.uniform(0.9, 1.1))


def schedule_next(src: SourceLink, minutes: int | None = None) -> None:
    src.next_check_at = utcnow() + timedelta(minutes=minutes or next_interval_minutes(src.item))


def _apply_backoff(retailer: Retailer | None, retry_after: int | None) -> int:
    if retailer is None:
        return MIN_BACKOFF
    seconds = max(MIN_BACKOFF, min(MAX_BACKOFF, (retailer.backoff_seconds or MIN_BACKOFF // 2) * 2))
    if retry_after:
        seconds = max(seconds, min(MAX_BACKOFF, retry_after))
    retailer.backoff_seconds = seconds
    retailer.backoff_until = utcnow() + timedelta(seconds=seconds)
    return seconds


def _currency_ok(parsed: ParsedProduct) -> bool:
    return parsed.currency in (None, "", "CAD")


async def fetch_and_parse(url: str, retailer: Retailer | None, mode: str, *, etag: str | None = None,
                          last_modified: str | None = None, use_cache: bool = False,
                          allow_browser: bool = True) -> tuple[FetchResult, ParsedProduct | None, str]:
    """Return (fetch result, parsed product or None, method used)."""
    s = get_settings()
    fetcher = runtime.get_fetcher()
    cfg = RetailerConfig(domain=retailer.domain if retailer else domain_of(url),
                         selectors=retailer.selectors if retailer else None)
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
                       method: str, phash: str | None = None) -> tuple[Observation, dict]:
    """Store an observation, update the source, and return (observation, previous state)."""
    item = src.item
    prev_atl = db.scalar(
        select(func.min(Observation.price_cents)).where(
            Observation.item_id == item.id, Observation.price_cents.is_not(None),
            Observation.source_link_id.in_([s.id for s in item.sources if s.status == "confirmed"] or [-1]),
        )
    )
    previous = {"price": src.last_price_cents, "in_stock": src.last_in_stock, "atl": prev_atl}
    now = utcnow()
    obs = Observation(item_id=item.id, source_link_id=src.id, observed_at=now, price_cents=price_cents,
                      was_price_cents=was_price_cents, shipping_cents=shipping_cents, in_stock=in_stock,
                      seller=seller, payload_hash=phash, method=method)
    db.add(obs)
    src.last_price_cents = price_cents
    src.last_was_price_cents = was_price_cents
    src.last_shipping_cents = shipping_cents
    src.last_in_stock = in_stock
    src.last_seller = seller
    src.last_checked_at = now
    src.last_success_at = now
    src.last_error = None
    src.consecutive_failures = 0
    db.flush()
    return obs, previous


def run_alerts(db: Session, src: SourceLink, previous: dict) -> list:
    db.refresh(src.item)
    summary = summarize_items(db, [src.item])[src.item.id]
    return alerts.evaluate_item(db, src.item, summary, source=src, previous_price=previous["price"],
                                previous_in_stock=previous["in_stock"], previous_atl=previous["atl"])


async def check_source(source_id: int) -> str:
    """Check one source link. Returns the outcome string."""
    db = session_scope()
    try:
        src = db.get(SourceLink, source_id)
        if src is None or src.status != "confirmed" or src.url.startswith("manual://"):
            return "skipped"
        retailer = src.retailer
        domain = retailer.domain if retailer else domain_of(src.url)
        now = utcnow()
        if retailer and retailer.backoff_until and retailer.backoff_until > now:
            src.next_check_at = retailer.backoff_until + timedelta(seconds=random.randint(30, 300))
            db.commit()
            return "backoff"
        mode = src.fetch_mode or (retailer.fetch_mode if retailer else "auto")
        allow_browser = bool(settings_store.get(db, "browser_fallback"))
        started = utcnow()
        result, parsed, method = await fetch_and_parse(
            src.url, retailer, mode, etag=src.etag, last_modified=src.last_modified, allow_browser=allow_browser)

        status = result.outcome
        error = result.error
        if result.outcome == "ok":
            if parsed and parsed.has_price and _currency_ok(parsed):
                status = "ok"
            elif parsed and parsed.has_price:
                status, error = "currency", f"Price is in {parsed.currency}, not CAD"
            else:
                status, error = "no_price", "No price found on the page"

        db.add(FetchRun(source_link_id=src.id, domain=domain, started_at=started, duration_ms=result.elapsed_ms,
                        status=status, http_status=result.status_code, method=method, error=error))
        FETCH_TOTAL.labels(domain=domain, status=status, method=method).inc()

        previous = None
        if status == "ok":
            assert parsed is not None
            if method == "http":
                src.etag, src.last_modified = result.etag, result.last_modified
            if parsed.name and not src.title:
                src.title = parsed.name[:500]
            if retailer:
                retailer.backoff_seconds = 0
                retailer.backoff_until = None
            _, previous = record_observation(
                db, src, price_cents=parsed.price_cents, was_price_cents=parsed.was_price_cents,
                shipping_cents=parsed.shipping_cents, in_stock=parsed.in_stock, seller=parsed.seller,
                method=method, phash=payload_hash(parsed))
        elif status == "not_modified" and src.last_price_cents is not None:
            _, previous = record_observation(
                db, src, price_cents=src.last_price_cents, was_price_cents=src.last_was_price_cents,
                shipping_cents=src.last_shipping_cents, in_stock=src.last_in_stock, seller=src.last_seller,
                method="not_modified")
        else:
            src.last_checked_at = utcnow()
            src.last_error = error
            src.consecutive_failures = (src.consecutive_failures or 0) + 1
            if status == "blocked":
                seconds = _apply_backoff(retailer, result.retry_after)
                schedule_next(src, minutes=max(seconds // 60, 1) + random.randint(1, 10))
            if status == "not_modified":
                src.etag = src.last_modified = None  # force a full fetch next time
        if src.next_check_at is None or src.next_check_at <= utcnow():
            failures = src.consecutive_failures or 0
            # back off gently on repeated failures: 1x, 2x, 4x the interval, capped at 24 h
            minutes = min(next_interval_minutes(src.item) * (2 ** min(failures, 2)), 24 * 60) if failures else None
            schedule_next(src, minutes)
        db.commit()
        if previous is not None:
            run_alerts(db, src, previous)
        log.info("checked", extra={"source_id": src.id, "domain": domain, "status": status, "method": method})
        return status
    except Exception:
        db.rollback()
        log.exception("check failed", extra={"source_id": source_id})
        return "error"
    finally:
        db.close()
