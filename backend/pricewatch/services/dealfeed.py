"""RedFlagDeals Hot Deals feed: match threads to wishlist items as hints (never as price truth).

Polite: fetched through the same rate-limited, robots-respecting fetcher, every 15 minutes at most.
Only the title, link, retailer tag and quoted price are stored.
"""

import logging
import re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

from lxml import etree
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.base import parse_price
from ..models import DealFeedEntry, Item, Retailer, SourceLink
from ..timeutil import utcnow
from . import runtime, settings_store
from .matching import Candidate, ItemSpec, match

log = logging.getLogger(__name__)
TAG_RE = re.compile(r"^\s*\[([^\]]{2,60})\]\s*")
PRICE_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?")
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, recover=True)


def parse_feed(xml: str) -> list[dict]:
    """RSS 2.0 or Atom -> [{guid, title, link, published}]."""
    try:
        root = etree.fromstring(xml.encode("utf-8", errors="replace"), parser=_PARSER)
    except etree.XMLSyntaxError:
        return []
    if root is None:
        return []
    out = []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        guid = (it.findtext("guid") or link).strip()
        pub = it.findtext("pubDate")
        try:
            published = parsedate_to_datetime(pub).astimezone(tz=None).replace(tzinfo=None) if pub else None
        except (TypeError, ValueError):
            published = None
        if title and guid:
            out.append({"guid": guid, "title": title, "link": link, "published": published})
    for entry in root.iterfind(".//a:entry", ns):
        title = (entry.findtext("a:title", namespaces=ns) or "").strip()
        link_el = entry.find("a:link", ns)
        link = link_el.get("href") if link_el is not None else ""
        guid = (entry.findtext("a:id", namespaces=ns) or link).strip()
        upd = entry.findtext("a:updated", namespaces=ns) or entry.findtext("a:published", namespaces=ns)
        try:
            published = datetime.fromisoformat(upd.replace("Z", "+00:00")).replace(tzinfo=None) if upd else None
        except ValueError:
            published = None
        if title and guid:
            out.append({"guid": guid, "title": title, "link": link, "published": published})
    return out


def split_title(title: str) -> tuple[str | None, str, int | None]:
    """'[Best Buy] Sony WH-1000XM6 $399.99 (Reg $549)' -> ('Best Buy', 'Sony WH-1000XM6 ...', 39999)."""
    m = TAG_RE.match(title)
    tag = m.group(1).strip() if m else None
    rest = title[m.end():] if m else title
    pm = PRICE_RE.search(rest)
    return tag, rest.strip(), parse_price(pm.group(0)) if pm else None


def retailer_for_tag(db: Session, tag: str | None) -> Retailer | None:
    if not tag:
        return None
    t = re.sub(r"[^a-z0-9]", "", tag.lower())
    for r in db.scalars(select(Retailer)).all():
        names = {re.sub(r"[^a-z0-9]", "", r.name.lower().replace("canada", "")), r.domain.split(".")[0]}
        if any(n and (n == t or n in t or t in n) for n in names):
            return r
    return None


def _pairs(db: Session, text: str, threshold: float):
    cand = Candidate(title=text, url="https://forums.redflagdeals.com/")
    for item in db.scalars(select(Item).where(Item.active.is_(True))).all():
        spec = ItemSpec.from_item(item)
        spec.exclude_marketplace = False  # the thread link is RFD, not a marketplace
        yield item, spec, cand, match(spec, cand, threshold)


def match_items(db: Session, text: str, threshold: float) -> list[tuple[Item, float]]:
    from . import llm_match

    return [(item, r.confidence) for item, spec, cand, r in _pairs(db, text, threshold)
            if r.accepted and not llm_match.vetoed(db, spec, cand, r)]


def ingest(db: Session, entries: list[dict]) -> dict:
    from .alerts import money, raise_alert
    from .users import members_of

    threshold = float(settings_store.get(db, "deal_feed_threshold") or 82)
    stats = {"seen": len(entries), "new": 0, "matched": 0, "alerts": 0, "duplicates": 0}
    for e in entries:
        if db.scalar(select(DealFeedEntry.id).where(DealFeedEntry.guid == e["guid"][:500])):
            continue
        tag, text, price = split_title(e["title"])
        retailer = retailer_for_tag(db, tag)
        hits = match_items(db, text, threshold)
        stats["new"] += 1
        if not hits:
            db.add(DealFeedEntry(feed="rfd", guid=e["guid"][:500], title=e["title"][:500], url=e["link"],
                                 published_at=e["published"], retailer_domain=retailer.domain if retailer else None,
                                 price_cents=price))
            continue
        for item, score in hits[:3]:
            stats["matched"] += 1
            src = None
            if retailer:
                src = db.scalar(select(SourceLink).where(SourceLink.item_id == item.id,
                                                         SourceLink.retailer_id == retailer.id,
                                                         SourceLink.status == "confirmed"))
            # several threads about the same deal collapse into one alert
            since = utcnow() - timedelta(days=3)
            dup = db.scalar(select(DealFeedEntry.id).where(
                DealFeedEntry.matched_item_id == item.id, DealFeedEntry.created_at >= since,
                DealFeedEntry.retailer_domain == (retailer.domain if retailer else None),
                DealFeedEntry.price_cents == price))
            entry = DealFeedEntry(feed="rfd", guid=(e["guid"] if item is hits[0][0] else f"{e['guid']}#{item.id}")[:500],
                                  title=e["title"][:500], url=e["link"], published_at=e["published"],
                                  matched_item_id=item.id, match_score=score, price_cents=price,
                                  retailer_domain=retailer.domain if retailer else None,
                                  matched_source_id=src.id if src else None)
            db.add(entry)
            db.flush()
            if dup:
                stats["duplicates"] += 1
                continue
            tracked = ""
            if src is not None and src.last_price_cents is not None:
                tracked = f" You already track {retailer.name}: last seen {money(src.last_price_cents)}."
            for user in members_of(db, item.list_id):
                cfg = settings_store.get_all(db, user.id)
                alert = raise_alert(
                    db, item=item, rule="deal_feed", key=f"rfd:{entry.id}", user_id=user.id,
                    title=f"RFD thread: {item.name}" + (f" at {money(price)}" if price else ""),
                    body=f"{e['title']}{tracked} A forum post is a hint; PriceWatch confirms on its next check.",
                    url=e["link"], cfg=cfg, instant=bool(cfg.get("alert_deal_feed", True)))
                if alert:
                    stats["alerts"] += 1
            if src is not None:
                src.next_check_at = utcnow()  # confirm the deal with a real check soon
    db.commit()
    return stats


async def poll(db: Session) -> dict:
    cfg = settings_store.get_all(db)
    if not cfg.get("deal_feed_enabled", True):
        return {"enabled": False}
    result = await runtime.get_fetcher().fetch(cfg["deal_feed_url"], respect_robots=True, min_interval=60)
    if result.outcome != "ok" or not result.html:
        log.info("deal feed fetch failed", extra={"outcome": result.outcome, "error": result.error})
        return {"outcome": result.outcome, "error": result.error}
    entries = parse_feed(result.html)
    fresh = [e for e in entries if not db.scalar(select(DealFeedEntry.id).where(DealFeedEntry.guid == e["guid"][:500]))]
    from . import llm_match

    if llm_match.enabled(db):
        threshold = float(settings_store.get(db, "deal_feed_threshold") or 82)
        new = [e for e in entries if not db.scalar(select(DealFeedEntry.id).where(DealFeedEntry.guid == e["guid"][:500]))]
        pairs = [(spec, cand, r) for e in new for _item, spec, cand, r in _pairs(db, split_title(e["title"])[1], threshold)]
        await llm_match.prefetch(db, pairs)
    stats = ingest(db, entries)
    from . import deals

    try:
        stats["category_deals"] = await deals.match_rfd(db, fresh)
    except Exception:  # noqa: BLE001  categories never break the feed
        log.exception("category matching failed")
    return stats
