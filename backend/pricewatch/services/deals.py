"""Deals for Home: today's biggest drops on watched items, matching RedFlagDeals threads, and deals in categories.

Categories are kinds of products ("TVs", "kitchen accessories", "3D printers"), not specific items. Deals for them come
from two places:
- the RedFlagDeals Hot Deals feed PriceWatch already reads (free): each new thread is sorted into the household's
  categories by Claude Haiku (titles only), or by the category's words when there is no Claude key;
- a Google Shopping "on sale" search per category (SerpApi), about daily during sale events (Black Friday week,
  Boxing Week) and weekly otherwise, paced to the monthly search limit. Only listings showing a was-price at least the
  category's minimum discount are kept.
"""

import logging
import re
from datetime import timedelta

import httpx
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CategoryDeal, DealCategory, DealFeedEntry, Item, Observation, SourceLink, User
from ..timeutil import utcnow
from . import claude, events, settings_store, users

log = logging.getLogger(__name__)
PRESETS = ["TVs", "Laptops", "Home electronics", "Kitchen accessories", "Small appliances", "Women's clothing",
           "Men's clothing", "Toys and games", "Video games", "3D printers", "Tools", "Headphones"]
KEEP_DAYS = 10


# ---------- today's drops on watched items ----------

def todays_drops(db: Session, user: User, limit: int = 8, min_pct: float = 3.0) -> list[dict]:
    """Stores whose latest price is below their highest price of the previous week, biggest drop first."""
    ids = users.list_ids(db, user)
    now = utcnow()
    since = now - timedelta(days=8)
    rows = db.execute(
        select(Observation.source_link_id, Observation.observed_at, Observation.price_cents)
        .join(SourceLink, SourceLink.id == Observation.source_link_id)
        .join(Item, Item.id == SourceLink.item_id)
        .where(Item.list_id.in_(ids or [-1]), Item.active.is_(True), SourceLink.status == "confirmed",
               Observation.price_cents.is_not(None), Observation.observed_at >= since)
        .order_by(Observation.observed_at)).all()
    by_src: dict[int, list] = {}
    for sid, at, price in rows:
        by_src.setdefault(sid, []).append((at, price))
    out = []
    for sid, pts in by_src.items():
        at, current = pts[-1]
        if at < now - timedelta(hours=36):
            continue  # not a today price
        before = [p for t, p in pts if t < at - timedelta(hours=12)]
        if not before:
            continue
        high = max(before)
        if high <= current or (high - current) * 100 / high < min_pct:
            continue
        src = db.get(SourceLink, sid)
        out.append({"item_id": src.item_id, "item": src.item.name, "store": src.retailer.name if src.retailer else None,
                    "url": src.url, "price_cents": current, "was_cents": high,
                    "drop_pct": round((high - current) * 100 / high, 1), "seen_at": at})
    out.sort(key=lambda d: -d["drop_pct"])
    best: dict[int, dict] = {}
    for d in out:  # one row per item: its biggest drop
        best.setdefault(d["item_id"], d)
    return list(best.values())[:limit]


def matched_threads(db: Session, user: User, days: int = 3, limit: int = 6) -> list[dict]:
    ids = users.list_ids(db, user)
    rows = db.execute(
        select(DealFeedEntry, Item.name).join(Item, Item.id == DealFeedEntry.matched_item_id)
        .where(Item.list_id.in_(ids or [-1]), DealFeedEntry.created_at >= utcnow() - timedelta(days=days))
        .order_by(DealFeedEntry.created_at.desc()).limit(limit)).all()
    return [{"item_id": e.matched_item_id, "item": name, "title": e.title, "url": e.url, "price_cents": e.price_cents,
             "seen_at": e.created_at} for e, name in rows]


# ---------- categories ----------

def _words(name: str) -> list[str]:
    stop = {"and", "for", "the", "of", "accessories", "products", "stuff", "things"}
    out = []
    for w in re.findall(r"[a-z0-9']+", name.lower().replace("'s", "")):
        if w in stop or len(w) < 2:
            continue
        out.append(w[:-1] if w.endswith("s") and not w.endswith("ss") and len(w) >= 3 else w)  # tvs -> tv
    return out


def keyword_match(category: str, title: str) -> bool:
    words = _words(category)
    t = title.lower()
    return bool(words) and all(re.search(rf"\b{re.escape(w)}s?\b", t) for w in words)


class Sorted(BaseModel):
    n: int
    categories: list[int]


class SortedAll(BaseModel):
    threads: list[Sorted]


async def sort_into_categories(cats: list[DealCategory], titles: list[str], *, client_factory=None) -> list[set[int]]:
    """For each title, the ids of the categories it belongs to (Claude when available, else the category's words)."""
    if not cats or not titles:
        return [set() for _ in titles]
    left = claude.budget_left()
    if not claude.api_key() or (left is not None and left < 0.02):
        return [{c.id for c in cats if keyword_match(c.name, t)} for t in titles]
    import anthropic

    listing = "\n".join(f"{n}. {t}" for n, t in enumerate(titles, 1))
    cat_text = "\n".join(f"{c.id}: {c.name}" for c in cats)
    api = (client_factory or (lambda: anthropic.AsyncAnthropic(api_key=claude.api_key(), timeout=60.0,
                                                               max_retries=1)))()
    try:
        resp = await api.messages.parse(
            model=claude.PRICE_MODEL, max_tokens=4000, output_config={"effort": "low"},
            system="Sort Canadian deal-forum thread titles into the shopper's product categories. A title belongs "
                   "to a category only if the product on sale is clearly of that kind. Most titles fit none. Return "
                   "every title by its number with the matching category ids (often an empty list).",
            messages=[{"role": "user", "content": f"Categories:\n{cat_text}\n\nThreads:\n{listing}"}],
            output_format=SortedAll)
        claude.record_spend(claude.cost_usd(claude.PRICE_MODEL, getattr(resp, "usage", None)))
        parsed = resp.parsed_output
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
        log.warning("category sort failed: %s", type(exc).__name__)
        return [{c.id for c in cats if keyword_match(c.name, t)} for t in titles]
    finally:
        await api.close()
    valid = {c.id for c in cats}
    out = [set() for _ in titles]
    for row in (parsed.threads if parsed else []):
        if 1 <= row.n <= len(titles):
            out[row.n - 1] = {i for i in row.categories if i in valid}
    return out


async def match_rfd(db: Session, entries: list[dict]) -> int:
    """Sort new RedFlagDeals threads into everyone's categories. Returns how many deals were added."""
    from .dealfeed import split_title

    cats = db.scalars(select(DealCategory).where(DealCategory.active.is_(True))).all()
    if not cats or not entries:
        return 0
    titles = [e["title"] for e in entries]
    found = await sort_into_categories(cats, titles)
    added = 0
    for e, ids in zip(entries, found, strict=True):
        tag, _text, price = split_title(e["title"])
        for cid in ids:
            if db.scalar(select(CategoryDeal.id).where(CategoryDeal.category_id == cid, CategoryDeal.url == e["link"])):
                continue
            db.add(CategoryDeal(category_id=cid, title=e["title"][:500], url=e["link"][:1000], store=tag,
                                price_cents=price, source="rfd"))
            added += 1
    db.commit()
    return added


def search_due(cat: DealCategory, cfg: dict) -> bool:
    days = 1 if events.sale_mode(cfg) or _sale_season() else 7
    return cat.last_search_at is None or cat.last_search_at < utcnow() - timedelta(days=days)


def _sale_season() -> bool:
    """Black Friday week through Cyber Monday, and Boxing Week."""
    d = events.local_now(utcnow()).date()
    return (d.month == 11 and d.day >= 20) or (d.month == 12 and (d.day <= 2 or d.day >= 20))


async def search_category(db: Session, cat: DealCategory, client: httpx.AsyncClient | None = None) -> int:
    """One Google Shopping "on sale" search for the category; keeps listings with a real was-price discount."""
    from ..serp import get_provider
    from .discovery import DiscoveryError, run_search

    provider = get_provider("serpapi")
    if provider is None or not hasattr(provider, "on_sale"):
        return 0

    class _OnSale:
        name = provider.name

        async def search(self, query, client):
            return await provider.on_sale(query, client)

    key = f"deals:{cat.name.lower()}"
    try:
        cands, _ = await run_search(db, None, _OnSale(), key[:300], True, client)  # due: always fresh
    except DiscoveryError as exc:
        log.info("category search skipped: %s", exc)
        return 0
    cat.last_search_at = utcnow()
    added = 0
    for c in cands:
        was = (c.extra or {}).get("old_price_cents")
        if not (c.price_cents and was and was > c.price_cents):
            continue
        pct = (was - c.price_cents) * 100 / was
        if pct < (cat.min_discount_pct or 0) or (cat.max_price_cents and c.price_cents > cat.max_price_cents):
            continue
        url = c.url
        if db.scalar(select(CategoryDeal.id).where(CategoryDeal.category_id == cat.id, CategoryDeal.url == url)):
            continue
        db.add(CategoryDeal(category_id=cat.id, title=c.title[:500], url=url[:1000], store=(c.merchant or "")[:120],
                            price_cents=c.price_cents, was_cents=was, source="google_shopping"))
        added += 1
    db.commit()
    return added


async def refresh_categories(db: Session, per_run: int = 2) -> int:
    """Scheduled: run due category searches (paced to the monthly search limit) and prune old deals."""
    from ..serp import get_provider
    from .discovery import _within_budget

    db.query(CategoryDeal).filter(CategoryDeal.seen_at < utcnow() - timedelta(days=KEEP_DAYS)).delete()
    db.commit()
    provider = get_provider("serpapi")
    if provider is None:
        return 0
    cfg = settings_store.get_all(db)
    done = 0
    for cat in db.scalars(select(DealCategory).where(DealCategory.active.is_(True))
                          .order_by(DealCategory.last_search_at.is_not(None), DealCategory.last_search_at)).all():
        if done >= per_run or not _within_budget(db, provider):
            break
        if search_due(cat, cfg):
            await search_category(db, cat)
            done += 1
    return done


def category_deals(db: Session, user: User, per_category: int = 6) -> list[dict]:
    cats = db.scalars(select(DealCategory).where(DealCategory.user_id == user.id).order_by(DealCategory.name)).all()
    out = []
    for c in cats:
        deals = db.scalars(select(CategoryDeal).where(CategoryDeal.category_id == c.id,
                                                      CategoryDeal.dismissed.is_(False))
                           .order_by(CategoryDeal.seen_at.desc()).limit(40)).all()
        deals = sorted(deals, key=lambda d: (-(d.discount_pct or 0), -d.seen_at.timestamp()))[:per_category]
        out.append({"id": c.id, "name": c.name, "min_discount_pct": c.min_discount_pct,
                    "max_price_cents": c.max_price_cents, "active": c.active,
                    "last_search_at": c.last_search_at,
                    "deals": [{"id": d.id, "title": d.title, "url": d.url, "store": d.store,
                               "price_cents": d.price_cents, "was_cents": d.was_cents,
                               "discount_pct": d.discount_pct, "source": d.source, "seen_at": d.seen_at}
                              for d in deals]})
    return out

