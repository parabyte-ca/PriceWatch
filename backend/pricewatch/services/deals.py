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

from ..models import CategoryDeal, DealCategory, DealFeedEntry, DealSighting, Item, Observation, SourceLink, User
from ..timeutil import utcnow
from . import claude, events, settings_store, users

log = logging.getLogger(__name__)
PRESETS = ["TVs", "Laptops", "Home electronics", "Kitchen accessories", "Small appliances", "Women's clothing",
           "Men's clothing", "Toys and games", "Video games", "3D printers", "Tools", "Headphones"]
SHOW_DAYS = 10  # deals shown on Home
KEEP_DAYS = 400  # kept for the per-category forecast


# ---------- deal score and price history ----------

def url_key(url: str) -> str:
    import hashlib

    from .matching import normalize_url

    return hashlib.sha256(normalize_url(url or "").encode()).hexdigest()


def record_sighting(db: Session, url: str, price_cents: int | None) -> None:
    if price_cents and url:
        db.add(DealSighting(url_key=url_key(url), price_cents=price_cents))


def history(db: Session, url: str) -> dict:
    rows = db.execute(select(DealSighting.seen_at, DealSighting.price_cents)
                      .where(DealSighting.url_key == url_key(url)).order_by(DealSighting.seen_at)).all()
    prices = [p for _, p in rows]
    if not prices:
        return {"points": [], "low_cents": None, "high_cents": None, "typical_cents": None, "count": 0}
    srt = sorted(prices)
    return {"points": [{"at": at, "price_cents": p} for at, p in rows], "low_cents": srt[0], "high_cents": srt[-1],
            "typical_cents": srt[len(srt) // 2], "count": len(prices)}


def score(*, discount_pct: float | None, price_cents: int | None, low_cents: int | None, sightings: int,
          trusted_store: bool, source: str, age_hours: float) -> int:
    """0 to 100: how good a deal looks. Discount counts most; being the lowest price seen, a known Canadian store,
    a vetted source (forum threads are voted on) and freshness add to it."""
    pts = min(max(discount_pct or 0, 0), 60) / 60 * 50
    if price_cents and low_cents and sightings >= 2:
        pts += 20 if price_cents <= low_cents else (10 if price_cents <= low_cents * 1.05 else 0)
    if trusted_store:
        pts += 10
    if source == "rfd":
        pts += 8
    pts += 10 if age_hours <= 24 else (5 if age_hours <= 72 else 0)
    if price_cents:
        pts += 2
    return max(0, min(100, round(pts)))


def score_deal(db: Session, d: CategoryDeal) -> int:
    from .retailers import domain_for_merchant

    h = history(db, d.url)
    age = (utcnow() - d.seen_at).total_seconds() / 3600 if d.seen_at else 0
    return score(discount_pct=d.discount_pct, price_cents=d.price_cents, low_cents=h["low_cents"],
                 sightings=h["count"], trusted_store=bool(d.store and domain_for_merchant(d.store)), source=d.source,
                 age_hours=age)


OG_IMAGE = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](https://[^"\']+)["\']', re.I)


async def thread_images(db: Session, deals: list[CategoryDeal], limit: int = 4) -> int:
    """The preview picture of new forum deals (one polite page visit each, a few per poll)."""
    from . import runtime

    n = 0
    for d in [x for x in deals if not x.image_url][:limit]:
        try:
            res = await runtime.get_fetcher().fetch(d.url, respect_robots=True, min_interval=20)
        except Exception:  # noqa: BLE001
            continue
        m = OG_IMAGE.search(res.html or "") if res.outcome == "ok" else None
        if m:
            d.image_url = m.group(1)[:1000]
            n += 1
    db.commit()
    return n


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
        pct = round((high - current) * 100 / high, 1)
        lows = [p for _t, p in pts]
        out.append({"item_id": src.item_id, "item": src.item.name, "store": src.retailer.name if src.retailer else None,
                    "url": src.url, "price_cents": current, "was_cents": high, "drop_pct": pct, "seen_at": at,
                    "image": src.item.image_url,
                    "score": score(discount_pct=pct, price_cents=current, low_cents=min(lows), sightings=len(lows),
                                   trusted_store=True, source="watch", age_hours=(now - at).total_seconds() / 3600)})
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
    new_deals: list[CategoryDeal] = []
    for e, ids in zip(entries, found, strict=True):
        tag, _text, price = split_title(e["title"])
        for cid in ids:
            if db.scalar(select(CategoryDeal.id).where(CategoryDeal.category_id == cid, CategoryDeal.url == e["link"])):
                continue
            d = CategoryDeal(category_id=cid, title=e["title"][:500], url=e["link"][:1000], store=tag,
                             price_cents=price, source="rfd", seen_at=utcnow())
            db.add(d)
            new_deals.append(d)
            added += 1
        record_sighting(db, e["link"], price)
    db.commit()
    for d in new_deals:
        d.score = score_deal(db, d)
    db.commit()
    if new_deals:
        await thread_images(db, new_deals)
    return added


def search_due(cat: DealCategory, cfg: dict) -> bool:
    from .plan import live_day

    hours = 6 if live_day() else 24 if events.sale_mode(cfg) or _sale_season() else 24 * 7
    return cat.last_search_at is None or cat.last_search_at < utcnow() - timedelta(hours=hours)


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

    key = f"deals:{cat_key(cat.name)}"
    try:
        cands, _ = await run_search(db, None, _OnSale(), key[:300], True, client)  # due: always fresh
    except DiscoveryError as exc:
        log.info("category search skipped: %s", exc)
        return 0
    for c in cands:
        record_sighting(db, c.url, c.price_cents)
    added = 0
    # one search serves everyone following a category of the same name, each with their own discount and price rules
    for each in same_name(db, cat):
        each.last_search_at = utcnow()
        added += _keep(db, each, cands)
    db.commit()
    return added


def cat_key(name: str) -> str:
    return " ".join(name.lower().split())


def same_name(db: Session, cat: DealCategory) -> list[DealCategory]:
    """This category and everyone else's with the same name ("3D printers" and "3d  printers" match)."""
    key = cat_key(cat.name)
    others = [c for c in db.scalars(select(DealCategory).where(DealCategory.active.is_(True))).all()
              if c.id != cat.id and cat_key(c.name) == key]
    return [cat, *others]


def copy_from_others(db: Session, cat: DealCategory) -> int:
    """A newly followed category starts with the recent deals of anyone already following the same category."""
    others = same_name(db, cat)[1:]
    if not others:
        return 0
    seen = {u for (u,) in db.execute(select(CategoryDeal.url).where(CategoryDeal.category_id == cat.id)).all()}
    copied = 0
    for o in others:
        for d in db.scalars(select(CategoryDeal).where(CategoryDeal.category_id == o.id,
                                                       CategoryDeal.seen_at >= utcnow() - timedelta(days=SHOW_DAYS))
                            ).all():
            pct = d.discount_pct
            if d.url in seen or (cat.max_price_cents and d.price_cents and d.price_cents > cat.max_price_cents):
                continue
            if d.source == "google_shopping" and pct is not None and pct < (cat.min_discount_pct or 0):
                continue
            seen.add(d.url)
            db.add(CategoryDeal(category_id=cat.id, title=d.title, url=d.url, store=d.store, price_cents=d.price_cents,
                                was_cents=d.was_cents, source=d.source, seen_at=d.seen_at, image_url=d.image_url,
                                score=d.score))
            copied += 1
    searched = [o.last_search_at for o in others if o.last_search_at]
    if searched:
        cat.last_search_at = max(searched)
    db.commit()
    return copied


def _keep(db: Session, cat: DealCategory, cands: list) -> int:
    """Add the search listings that meet this category's discount and price rules."""
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
        d = CategoryDeal(category_id=cat.id, title=c.title[:500], url=url[:1000], store=(c.merchant or "")[:120],
                         price_cents=c.price_cents, was_cents=was, source="google_shopping", seen_at=utcnow(),
                         image_url=(c.extra or {}).get("image"))
        db.add(d)
        db.flush()
        d.score = score_deal(db, d)
        added += 1
    return added


async def refresh_categories(db: Session, per_run: int = 2) -> int:
    """Scheduled: run due category searches (paced to the monthly search limit) and prune old deals."""
    from ..serp import get_provider
    from .discovery import _within_budget

    db.query(CategoryDeal).filter(CategoryDeal.seen_at < utcnow() - timedelta(days=KEEP_DAYS)).delete()
    db.commit()
    # categories someone else in the household also follows: share their recent deals with an empty one
    since = utcnow() - timedelta(days=SHOW_DAYS)
    for cat in db.scalars(select(DealCategory).where(DealCategory.active.is_(True))).all():
        if not db.scalar(select(CategoryDeal.id).where(CategoryDeal.category_id == cat.id,
                                                       CategoryDeal.seen_at >= since).limit(1)):
            copy_from_others(db, cat)
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


def _window(d) -> str:
    """Which sale window a day falls in (local dates)."""
    m, day = d.month, d.day
    if m == 11 and 20 <= day <= 28:
        return "Black Friday week"
    if (m == 11 and day >= 29) or (m == 12 and day <= 2):
        return "Cyber Monday"
    if m == 12 and day >= 26:
        return "Boxing Week"
    if m == 12 and 15 <= day <= 25:
        return "before Christmas"
    return "regular weeks"


def forecast(db: Session, cat: DealCategory, min_deals: int = 8) -> dict | None:
    """When this category's discounts have been deepest, from the deals PriceWatch has seen (kept 10 days, so this
    compares windows as they pass). None until there is enough to say anything."""
    rows = db.scalars(select(CategoryDeal).where(CategoryDeal.category_id == cat.id)).all()
    by: dict[str, list[int]] = {}
    for d in rows:
        if d.discount_pct:
            by.setdefault(_window(events.local_now(d.seen_at).date()), []).append(d.discount_pct)
    seen = sum(len(v) for v in by.values())
    if seen < min_deals:
        return None
    avg = {w: round(sum(v) / len(v)) for w, v in by.items() if len(v) >= 3}
    if not avg:
        return None
    best = max(avg, key=avg.get)
    text = f"Deepest discounts so far: {best} (about {avg[best]}% off on average"
    others = [f"{w} {p}%" for w, p in sorted(avg.items(), key=lambda x: -x[1]) if w != best]
    text += f"; {', '.join(others)})" if others else ")"
    return {"best_window": best, "averages": avg, "deals": seen, "text": text + f", from {seen} deals."}


def category_deals(db: Session, user: User, per_category: int = 6) -> list[dict]:
    cats = db.scalars(select(DealCategory).where(DealCategory.user_id == user.id).order_by(DealCategory.name)).all()
    out = []
    for c in cats:
        deals = db.scalars(select(CategoryDeal).where(CategoryDeal.category_id == c.id,
                                                      CategoryDeal.dismissed.is_(False),
                                                      CategoryDeal.seen_at >= utcnow() - timedelta(days=SHOW_DAYS))
                           .order_by(CategoryDeal.seen_at.desc()).limit(40)).all()
        for d in deals:
            d.score = score_deal(db, d)  # freshness changes: rescore on read
        deals = sorted(deals, key=lambda d: (-(d.score or 0), -d.seen_at.timestamp()))[:per_category]
        out.append({"id": c.id, "name": c.name, "min_discount_pct": c.min_discount_pct, "forecast": forecast(db, c),
                    "max_price_cents": c.max_price_cents, "active": c.active,
                    "last_search_at": c.last_search_at,
                    "deals": [{"id": d.id, "title": d.title, "url": d.url, "store": d.store,
                               "price_cents": d.price_cents, "was_cents": d.was_cents,
                               "discount_pct": d.discount_pct, "source": d.source, "seen_at": d.seen_at,
                               "image": d.image_url, "score": d.score}
                              for d in deals]})
    return out



def live_digest(db: Session, now_utc=None) -> int:
    """On live sale days: once an hour, tell each person which of their items dropped in the last hour."""
    from .alerts import money, raise_alert

    now = now_utc or utcnow()
    local = events.local_now(now)
    sent = 0
    for user in db.scalars(select(User).where(User.active.is_(True))).all():
        moved = [d for d in todays_drops(db, user, limit=10, min_pct=2.0) if d["seen_at"] >= now - timedelta(hours=1)]
        if not moved:
            continue
        body = "\n".join(f"- {d['item']}: {money(d['price_cents'])} at {d['store']} (-{d['drop_pct']:g}%)" for d in moved)
        a = raise_alert(db, item=None, rule="live", key=f"live:{local:%Y-%m-%d-%H}", user_id=user.id,
                        title=f"{len(moved)} price drop{'s' if len(moved) > 1 else ''} in the last hour", body=body,
                        url="/")
        sent += bool(a)
    return sent
