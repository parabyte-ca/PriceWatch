"""Candidate discovery through a SERP provider, matched against the item and stored as suggestions."""

import hashlib
import logging
import re
from datetime import timedelta
from urllib.parse import urlsplit

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..fetch.http import domain_of
from ..models import Item, MarketOffer, SerpSearch, SourceLink
from ..serp import ProviderError, SerpProvider, get_provider
from ..timeutil import utcnow
from . import llm_match, settings_store
from .matching import Candidate, ItemSpec, match, normalize_url
from .retailers import domain_for_merchant, get_or_create_retailer, merchant_kind

log = logging.getLogger(__name__)

CACHE_DAYS = 7
EXPAND_MAX = 2  # store-list lookups per discovery (each is one SerpApi search)


class _StoreList:
    """Adapter so a Google product's store list goes through run_search (cache, monthly limit, history)."""

    def __init__(self, provider, token: str) -> None:
        self.provider, self.token, self.name = provider, token, provider.name

    async def search(self, query: str, client: httpx.AsyncClient) -> list[Candidate]:
        return await self.provider.expand(self.token, client)
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
    """Search for the item at every store, track each known Canadian store and record the prices."""
    provider = get_provider(provider_name)
    if provider is None:
        raise DiscoveryError("No search provider configured. Set SERPAPI_KEY in .env or add a Claude key")
    r = await compare(db, item, provider, force=force, client=client)
    dropped = drop_wrong_generation(db, item)
    market = save_offers(db, item, r["offers"], query=r["query"])
    market["dropped"] = dropped
    db.commit()
    log.info("discovery", extra={"item_id": item.id, "provider": provider.name, "cached": r["cached"],
                                 "candidates": len(r["candidates"]), "added": market["added"]})
    return {"provider": provider.name, "query": r["query"], "cached": r["cached"], "added": market["added"],
            "usage": month_usage(db, provider.name), "limit": int(settings_store.get(db, "serp_monthly_limit") or 0),
            "candidates": r["candidates"], "notes": r["notes"], "market": market}


async def compare(db: Session, item: Item, provider, *, force: bool = False,
                  client: httpx.AsyncClient | None = None, on_stage=None) -> dict:
    """Search and match, without saving anything: the candidates, the matching offers and notes.

    ``item`` may be unsaved (the Find page compares before anything is watched); searches are cached for a week, so
    watching right after a comparison costs no second search.
    """
    cfg = settings_store.get_all(db)
    if hasattr(provider, "location"):
        provider.location = cfg.get("shopping_location") or "Canada"
    query = build_query(item)
    candidates, cached = await run_search(db, item if item.id else None, provider, query, force, client)

    spec = ItemSpec.from_item(item)
    threshold = float(cfg["match_threshold"])
    use_llm = llm_match.enabled(db)
    out, seen = [], set()
    notes: list[str] = []
    offers: list[dict] = []

    async def consider(cand: Candidate, via: str) -> dict | None:
        url = normalize_url(cand.url)
        if url in seen:
            return None
        seen.add(url)
        result = match(spec, cand, threshold)
        ai = None
        if use_llm and result.accepted and result.method == "fuzzy" and llm_match.in_band(result.confidence):
            ai = await llm_match.check(db, spec, cand)
            if ai and not ai["same_product"]:
                result.accepted = False
                result.reasons = [*result.reasons, f"Claude: not the same product ({ai['reason']})"]
        store_link = _is_merchant_url(url)
        merchant = cand.merchant or (urlsplit(url).hostname or "")
        domain = domain_for_merchant(merchant)
        if domain is None and store_link:
            host = domain_of(url)
            domain = host if (host.endswith(".ca") or domain_for_merchant(host)) else None
            domain = domain_for_merchant(host) or domain
        kind = merchant_kind(merchant) if domain or store_link else "other"
        if kind == "store" and domain is None:
            kind = "other"  # not a store PriceWatch knows sells in Canada
        row = {"title": cand.title, "url": url, "merchant": merchant, "price_cents": cand.price_cents,
               "confidence": result.confidence, "method": result.method, "accepted": result.accepted,
               "reasons": result.reasons, "exclusions": result.exclusions, "ai": ai, "via": via,
               "token": (cand.extra or {}).get("immersive_token"), "kind": kind, "domain": domain,
               "status": ("matched" if result.accepted else "excluded" if result.exclusions else "low match")}
        if result.accepted and cand.price_cents and cand.condition in (None, "new"):
            offers.append({"merchant": merchant, "title": cand.title, "price_cents": cand.price_cents,
                           "shipping_cents": cand.shipping_cents, "url": url, "store_link": store_link,
                           "provider": via, "confidence": result.confidence, "domain": domain, "kind": kind,
                           "method": result.method, "reasons": result.reasons, "ai": ai,
                           "local": (cand.extra or {}).get("local")})
        out.append(row)
        return row

    wrong = rejected_listings(db, query, item.id)

    async def stage(name: str) -> None:
        if on_stage is not None:
            await on_stage(name, offers)

    for cand in candidates:
        if normalize_url(cand.url) in wrong:
            continue
        await consider(cand, provider.name)
    await stage("search")

    # Google Shopping hides store links behind its own product pages. Open the best matching products' store
    # lists (one search each, cached) so the stores' own product pages can be tracked.
    hidden = [r for r in out if not _is_merchant_url(r["url"]) and r["accepted"] and r.get("token")]
    hidden.sort(key=lambda r: -r["confidence"])
    if hidden and hasattr(provider, "expand"):
        for row in hidden[:EXPAND_MAX]:
            try:
                stores, _ = await run_search(db, item, _StoreList(provider, row["token"]),
                                             "stores:" + hashlib.sha1(row["token"].encode()).hexdigest()[:16],
                                             False, client)  # store lists change rarely: a week's cache is fine
            except DiscoveryError as exc:
                notes.append(f"store links: {exc}")
                break
            for cand in stores:
                cand.title = cand.title or row["title"]
                if normalize_url(cand.url) not in wrong:
                    await consider(cand, provider.name)
        await stage("stores")

    # eBay Canada (official API, optional): new fixed-price listings, shown with the marketplace sellers
    from ..serp.ebay import ebay_provider

    ebay = ebay_provider()
    if ebay is not None:
        try:
            listings, _ = await run_search(db, item if item.id else None, ebay, query, force, client)
            for cand in listings:
                if normalize_url(cand.url) not in wrong:
                    await consider(cand, "ebay")
        except DiscoveryError as exc:
            notes.append(f"eBay: {exc}")

    # still nothing with a real store link: ask Claude's web search, which returns the stores' own pages
    linked = [r for r in out if _is_merchant_url(r["url"]) and r["accepted"]]
    if not linked and provider.name != "claude":
        claude_web = get_provider("claude")
        if claude_web is not None and claude_web.name == "claude":
            try:
                extra, _ = await run_search(db, item, claude_web, query, force, client)
                for cand in extra:
                    if normalize_url(cand.url) not in wrong:
                        await consider(cand, "claude")
                await stage("claude")
            except DiscoveryError as exc:
                notes.append(f"Claude search: {exc}")

    # Claude sorts out bundles, accessories, refurbished units and marketplace sellers the matcher let through
    from . import classify

    labels = await classify.classify(db, spec, [o for o in offers if o["kind"] in ("store", "other")])
    for o in offers:
        lab = labels.get(o["url"])
        if lab and lab != "same":
            o["kind"] = lab
            o["reasons"] = [*o["reasons"], f"Claude: {lab}"]
    for r in out:
        lab = labels.get(r["url"])
        if lab and lab != "same":
            r["kind"], r["status"] = lab, f"excluded ({lab})"
    await stage("done")
    for r in out:
        r.pop("token", None)
    out.sort(key=lambda r: (not r["accepted"], -r["confidence"]))
    return {"query": query, "cached": cached, "candidates": out, "offers": offers, "notes": notes}


def drop_wrong_generation(db: Session, item: Item) -> int:
    """Hide watched stores found by search whose listing is another generation ("Switch" for a "Switch 2" item).

    Catches stores matched before the generation check existed; stores added by hand are left alone.
    """
    from .matching import generation_conflict

    want = " ".join(x for x in (item.name, item.model) if x)
    n = 0
    for src in item.sources:
        if src.status != "confirmed" or not src.discovered_via or not src.title:
            continue
        why = generation_conflict(want, src.title)
        if why:
            src.status = "rejected"
            src.last_error = f"Hidden: the listing is a different generation ({why})"
            n += 1
    if n:
        db.commit()
    return n


def rejected_listings(db: Session, query: str, item_id: int | None) -> set[str]:
    """Listings the household marked "not this product" for this item or this search."""
    from ..models import ListingFeedback

    q = select(ListingFeedback.url).where(ListingFeedback.verdict == "wrong")
    conds = [ListingFeedback.query == query.lower().strip()]
    if item_id:
        conds.append(ListingFeedback.item_id == item_id)
    from sqlalchemy import or_

    return {u for u in db.scalars(q.where(or_(*conds))).all()}


def best_per_store(offers: list[dict]) -> list[dict]:
    """The lowest offer per store (shipping included), cheapest first."""
    best: dict[str, dict] = {}
    for o in offers:
        k = _offer_key(o)
        cur = best.get(k)
        total = o["price_cents"] + (o["shipping_cents"] or 0)
        if cur is None or total < cur["_total"] or (total == cur["_total"] and o["store_link"]
                                                      and not cur["store_link"]):
            best[k] = {**o, "_total": total}
    return sorted(best.values(), key=lambda o: o["_total"])


def merchant_key(name: str) -> str:
    """One key per store: "Walmart.ca", "walmart.ca" and "Walmart" are the same shop."""
    n = (name or "").lower().strip()
    n = re.sub(r"^(www\.)", "", n)
    n = re.sub(r"\.(ca|com)$", "", n)
    n = re.sub(r"\s*(canada|ca)$", "", n).strip(" -:")
    return n or "?"


def _offer_key(o: dict) -> str:
    return o["domain"] or merchant_key(o["merchant"])


def save_offers(db: Session, item: Item, offers: list[dict], *, query: str = "") -> dict:
    """Keep the lowest price per store as the item's comparison, and track every known Canadian store.

    Each recognised store becomes a tracked store for the item (one per store), and the price seen in the search is
    recorded as its price history, so history, alerts and the buy advice cover every store, not just one link.
    """
    ranked = best_per_store(offers)
    db.query(MarketOffer).filter(MarketOffer.item_id == item.id).delete()
    now = utcnow()
    rows = []
    for o in ranked:
        row = MarketOffer(item_id=item.id, merchant=o["merchant"][:120], title=(o["title"] or "")[:500],
                          price_cents=o["price_cents"], shipping_cents=o["shipping_cents"], url=o["url"][:1000],
                          store_link=o["store_link"], provider=o["provider"][:30], confidence=o["confidence"],
                          seen_at=now, domain=o["domain"], kind=o["kind"], local_note=o.get("local"))
        db.add(row)
        rows.append(row)
    db.flush()
    added = 0
    for o in ranked:
        if o["kind"] == "store" and o["domain"]:
            added += _sync_store(db, item, o, query)
    db.commit()
    stores = [r for r in rows if r.kind == "store"]
    return {"stores": len(stores), "best_cents": stores[0].price_cents if stores else None, "added": added,
            "others": len(rows) - len(stores)}


def _sync_store(db: Session, item: Item, o: dict, query: str) -> int:
    """Create or update the item's tracked store for this offer and record the price. Returns 1 when new."""
    from ..models import Retailer
    from .checker import CONFIDENCE, record_observation, run_alerts

    domain = o["domain"]
    retailer = db.scalar(select(Retailer).where(Retailer.domain == domain))
    if retailer is None:
        retailer = get_or_create_retailer(db, o["url"], domain=domain)
    src = next((s for s in item.sources if s.retailer_id == retailer.id), None)
    url = normalize_url(o["url"])
    created = 0
    if src is None:
        if any(normalize_url(s.url) == url for s in item.sources):
            return 0
        src = SourceLink(item_id=item.id, retailer_id=retailer.id, url=url, title=(o["title"] or "")[:500],
                         status="confirmed", match_confidence=o["confidence"], match_method=o["method"],
                         discovered_via=o["provider"],
                         fetch_mode=None if o["store_link"] and retailer.fetch_mode != "search" else "search",
                         match_reasons={"reasons": o["reasons"], "serp_price_cents": o["price_cents"],
                                        "merchant": o["merchant"], "query": query, "ai": o["ai"]})
        db.add(src)
        db.flush()
        if src not in item.sources:
            item.sources.append(src)
        created = 1
    elif src.status == "rejected":
        return 0  # hidden by the household
    elif o["store_link"] and not _is_merchant_url(src.url) and not any(
            normalize_url(s.url) == url for s in item.sources):
        src.url = url  # found the store's own page: use it from now on
        if retailer.fetch_mode != "search":
            src.fetch_mode = None
    # the search price counts unless the store page itself was read in the last day (it is more exact)
    fresh_direct = (src.fetch_mode != "search" and src.last_success_at is not None
                    and src.last_success_at > utcnow() - timedelta(hours=24) and not created)
    if not fresh_direct:
        _, previous = record_observation(
            db, src, price_cents=o["price_cents"], was_price_cents=None, shipping_cents=o["shipping_cents"],
            in_stock=True, seller=o["merchant"][:100], method="search", parse_confidence=CONFIDENCE["search"])
        src.last_error = None
        db.flush()
        run_alerts(db, src, previous, None)
    return created


def market_summary(db: Session, item_ids: list[int]) -> dict[int, dict]:
    """Best price found online per item, with the store count and when it was seen."""
    out: dict[int, dict] = {}
    if not item_ids:
        return out
    for o in db.scalars(select(MarketOffer).where(MarketOffer.item_id.in_(item_ids))
                        .order_by(MarketOffer.item_id, MarketOffer.price_cents)).all():
        m = out.setdefault(o.item_id, {"best": None, "stores": 0, "seen_at": o.seen_at})
        if o.kind != "store":
            continue
        m["stores"] += 1
        if m["best"] is None:
            m["best"] = {"merchant": o.merchant, "price_cents": o.price_cents, "shipping_cents": o.shipping_cents,
                         "url": o.url, "store_link": o.store_link, "title": o.title}
    return out


def _within_budget(db: Session, provider) -> bool:
    """Spread paid searches evenly over the month: never run ahead of the monthly limit's daily pace."""
    import calendar

    if provider.name == "claude":
        return True  # the Claude spending cap applies instead
    limit = int(settings_store.get(db, "serp_monthly_limit") or 0)
    if not limit:
        return True
    now = utcnow()
    days = calendar.monthrange(now.year, now.month)[1]
    pace = limit * now.day / days
    return month_usage(db, provider.name) < pace


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


async def refresh_stale(db: Session, per_run: int = 5, days: float = 1) -> int:
    """Re-search active items about daily, a few per run, so prices across stores stay current.

    Paced against the monthly search limit, so the searches last the whole month.
    """
    provider = get_provider(None)
    if provider is None or not settings_store.get(db, "discover_on_add"):
        return 0
    if not _within_budget(db, provider):
        return 0
    cfg = settings_store.get_all(db)
    from . import events

    if events.sale_mode(cfg):
        days = min(days, 0.5)  # sale events move fast: twice a day
    since = utcnow() - timedelta(days=days)
    recent = set(db.scalars(select(SerpSearch.item_id).where(SerpSearch.created_at >= since,
                                                             SerpSearch.item_id.is_not(None))).all())
    due = [i for i in db.scalars(select(Item).where(Item.active.is_(True))).all() if i.id not in recent]
    from .summary import summarize_items

    summaries = summarize_items(db, due) if due else {}

    def urgency(i: Item) -> tuple:
        """Most useful first: hot items, items close to their target, then priority and the oldest search."""
        s = summaries.get(i.id) or {}
        best, target = s.get("best_price_cents"), i.target_price_cents
        near = bool(best and target and best <= target * 1.1)
        return (not i.hot, not near, i.priority, i.id)

    items = sorted(due, key=urgency)[:per_run]
    done = 0
    for item in items:
        if not _within_budget(db, provider):
            break
        try:
            await discover(db, item, force=True)
            done += 1
        except DiscoveryError as exc:
            log.info("weekly discovery stopped", extra={"reason": str(exc)})
            break
    return done
