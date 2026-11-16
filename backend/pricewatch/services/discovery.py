"""Candidate discovery through a SERP provider, matched against the item and stored as suggestions."""

import logging
from datetime import timedelta
from urllib.parse import urlsplit

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Item, SerpSearch, SourceLink
from ..serp import ProviderError, SerpProvider, get_provider
from ..timeutil import utcnow
from . import llm_match, settings_store
from .matching import Candidate, ItemSpec, match, normalize_url
from .retailers import get_or_create_retailer

log = logging.getLogger(__name__)

CACHE_DAYS = 7
GOOGLE_HOSTS = ("google.", "googleadservices.", "doubleclick.")


class DiscoveryError(Exception):
    pass


def build_query(item: Item) -> str:
    if item.search_query:
        return item.search_query.strip()
    parts = [item.brand or "", item.name]
    if item.model and item.model.lower() not in item.name.lower():
        parts.append(item.model)
    words: list[str] = []
    for part in parts:
        for w in part.split():
            if w.lower() not in {x.lower() for x in words}:
                words.append(w)
    return " ".join(words)[:300]


def month_usage(db: Session, provider: str) -> int:
    now = utcnow()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return db.scalar(select(func.count(SerpSearch.id)).where(
        SerpSearch.provider == provider, SerpSearch.billable.is_(True), SerpSearch.status == "ok",
        SerpSearch.created_at >= start)) or 0


def _is_merchant_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return bool(host) and not any(g in host for g in GOOGLE_HOSTS)


def _candidate_dict(c: Candidate) -> dict:
    return {"title": c.title, "url": c.url, "price_cents": c.price_cents, "merchant": c.merchant,
            "condition": c.condition, "shipping_cents": c.shipping_cents, "gtin": c.gtin, "mpn": c.mpn,
            "brand": c.brand, "provider": c.provider, "extra": c.extra}


async def run_search(db: Session, item: Item | None, provider: SerpProvider, query: str, force: bool,
                     client: httpx.AsyncClient | None) -> tuple[list[Candidate], bool]:
    """Return (candidates, cached). Uses a 7-day cache and enforces the monthly limit."""
    if not force:
        cached = db.scalar(
            select(SerpSearch).where(SerpSearch.provider == provider.name, SerpSearch.query == query,
                                     SerpSearch.status == "ok",
                                     SerpSearch.created_at >= utcnow() - timedelta(days=CACHE_DAYS))
            .order_by(SerpSearch.created_at.desc()).limit(1))
        if cached and cached.results is not None:
            return [Candidate(**r) for r in cached.results], True
    limit = int(settings_store.get(db, "serp_monthly_limit") or 0)
    used = month_usage(db, provider.name)
    if limit and used >= limit:
        raise DiscoveryError(f"Monthly search limit reached for {provider.name} ({used}/{limit}); raise it in Settings")
    own_client = client is None
    client = client or httpx.AsyncClient()
    record = SerpSearch(provider=provider.name, query=query, item_id=item.id if item else None)
    try:
        candidates = await provider.search(query, client)
        record.result_count = len(candidates)
        record.results = [_candidate_dict(c) for c in candidates]
    except ProviderError as exc:
        record.status, record.error = "error", str(exc)
        db.add(record)
        db.commit()
        raise DiscoveryError(str(exc)) from exc
    finally:
        if own_client:
            await client.aclose()
    db.add(record)
    db.commit()
    return candidates, False


async def discover(db: Session, item: Item, *, provider_name: str | None = None, force: bool = False,
                   client: httpx.AsyncClient | None = None) -> dict:
    provider = get_provider(provider_name)
    if provider is None:
        raise DiscoveryError("No search provider configured. Set SERPAPI_KEY or BRIGHTDATA_API_KEY in .env")
    cfg = settings_store.get_all(db)
    query = build_query(item)
    candidates, cached = await run_search(db, item, provider, query, force, client)

    spec = ItemSpec.from_item(item)
    existing = {normalize_url(s.url): s for s in item.sources}
    threshold = float(cfg["match_threshold"])
    use_llm = llm_match.enabled(db)
    out, seen = [], set()
    added = 0
    for cand in candidates:
        url = normalize_url(cand.url)
        if url in seen:
            continue
        seen.add(url)
        result = match(spec, cand, threshold)
        ai = None
        if use_llm and result.accepted and result.method == "fuzzy" and llm_match.in_band(result.confidence):
            ai = await llm_match.check(db, spec, cand)
            if ai and not ai["same_product"]:
                result.accepted = False
                result.reasons = [*result.reasons, f"Claude: not the same product ({ai['reason']})"]
        row = {"title": cand.title, "url": url, "merchant": cand.merchant, "price_cents": cand.price_cents,
               "confidence": result.confidence, "method": result.method, "accepted": result.accepted,
               "reasons": result.reasons, "exclusions": result.exclusions, "ai": ai}
        if not _is_merchant_url(url):
            row["status"] = "no merchant link"
        elif url in existing:
            row["status"] = f"already {existing[url].status}"
        elif not result.accepted:
            row["status"] = "excluded" if result.exclusions else "low match"
        else:
            retailer = get_or_create_retailer(db, url)
            # a matching barcode or model number (same brand, not an accessory) is near certain: track it at once
            auto = (cfg["auto_confirm_gtin"] and result.method == "gtin") or (
                cfg.get("auto_confirm_strong", True) and result.method in ("gtin", "mpn", "model")
                and result.confidence >= 0.9)
            src = SourceLink(
                item_id=item.id, retailer_id=retailer.id, url=url, title=cand.title[:500],
                status="confirmed" if auto else "suggested", match_confidence=result.confidence,
                match_method=result.method, discovered_via=provider.name,
                match_reasons={"reasons": result.reasons, "exclusions": result.exclusions,
                               "serp_price_cents": cand.price_cents, "merchant": cand.merchant,
                               "query": query, "ai": ai},
            )
            if auto:
                src.next_check_at = utcnow()  # first real price soon
            db.add(src)
            db.flush()
            existing[url] = src
            added += 1
            row["status"] = "confirmed" if auto else "suggested"
        out.append(row)
    db.commit()
    out.sort(key=lambda r: (not r["accepted"], -r["confidence"]))
    log.info("discovery", extra={"item_id": item.id, "provider": provider.name, "cached": cached,
                                 "candidates": len(out), "added": added})
    return {"provider": provider.name, "query": query, "cached": cached, "added": added,
            "usage": month_usage(db, provider.name), "limit": int(cfg["serp_monthly_limit"] or 0),
            "candidates": out}


async def barcode_lookup(db: Session, code: str) -> dict:
    """Search Google Shopping for a scanned UPC/EAN and return likely product names (one cached search)."""
    from .matching import normalize_gtin

    digits = "".join(ch for ch in code if ch.isdigit())
    gtin = normalize_gtin(digits)
    if gtin is None:
        raise DiscoveryError("That is not a valid UPC or EAN barcode")
    provider = get_provider(None)
    if provider is None:
        return {"gtin": digits, "provider": None, "names": []}
    candidates, cached = await run_search(db, None, provider, digits, False, None)
    names: list[dict] = []
    seen: set[str] = set()
    for c in candidates:
        key = c.title.lower().strip()
        if not c.title or key in seen:
            continue
        seen.add(key)
        names.append({"title": c.title[:300], "brand": c.brand, "exact": normalize_gtin(c.gtin) == gtin,
                      "merchant": c.merchant, "price_cents": c.price_cents})
    names.sort(key=lambda n: not n["exact"])
    return {"gtin": digits, "provider": provider.name, "cached": cached, "names": names[:6]}


_running: set[int] = set()


def searching(item_id: int) -> bool:
    return item_id in _running


async def discover_in_background(item_id: int) -> None:
    """Look for the item at other stores without making the person wait (after adding an item)."""
    from ..db import session_scope

    if item_id in _running or get_provider(None) is None:
        return
    _running.add(item_id)
    db = session_scope()
    try:
        item = db.get(Item, item_id)
        if item is not None and settings_store.get(db, "discover_on_add"):
            await discover(db, item)
    except DiscoveryError as exc:
        log.info("background discovery skipped", extra={"item_id": item_id, "reason": str(exc)})
    except Exception:  # noqa: BLE001 - never let a background search break anything
        log.exception("background discovery failed", extra={"item_id": item_id})
    finally:
        _running.discard(item_id)
        db.close()


def start_background(item_id: int) -> None:
    """Schedule discover_in_background from async code or from a worker thread (sync endpoints)."""
    import asyncio

    from ..config import get_settings
    from . import runtime

    if not get_settings().scheduler_enabled:
        return  # background work follows the scheduler switch (off in tests)
    try:
        asyncio.get_running_loop().create_task(discover_in_background(item_id))
    except RuntimeError:
        if runtime.main_loop is not None and runtime.main_loop.is_running():
            asyncio.run_coroutine_threadsafe(discover_in_background(item_id), runtime.main_loop)


async def refresh_stale(db: Session, per_run: int = 5, days: int = 7) -> int:
    """Weekly re-search for active items, a few per run, so new stores and new listings are found."""
    if get_provider(None) is None or not settings_store.get(db, "discover_on_add"):
        return 0
    since = utcnow() - timedelta(days=days)
    recent = set(db.scalars(select(SerpSearch.item_id).where(SerpSearch.created_at >= since,
                                                             SerpSearch.item_id.is_not(None))).all())
    items = [i for i in db.scalars(select(Item).where(Item.active.is_(True)).order_by(Item.priority, Item.id)).all()
             if i.id not in recent][:per_run]
    done = 0
    for item in items:
        try:
            await discover(db, item)
            done += 1
        except DiscoveryError as exc:
            log.info("weekly discovery stopped", extra={"reason": str(exc)})
            break
    return done
