"""Crowd signals from a RedFlagDeals thread's comments, set against PriceWatch's own price history.

Rule-based extraction (keywords and quoted prices); no usernames or post text are stored, only counts,
quoted prices and coupon codes. Threads are fetched through the polite fetcher (robots, rate limits),
at most every 2 hours while the thread is under 7 days old.
"""

import logging
import re
from datetime import timedelta

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.base import parse_price
from ..models import DealFeedEntry, Item
from ..timeutil import utcnow
from . import runtime

log = logging.getLogger(__name__)

SIGNALS = {
    "all_time_low": re.compile(r"\b(atl|all[- ]time low|lowest (price )?(ever|i'?ve seen|seen)|best price (ever|i'?ve seen)|"
                               r"never (seen|been) (it )?(this|that) (low|cheap))\b", re.I),
    "wait": re.compile(r"\b(wait (for|until|till)|boxing (day|week)|was cheaper|cheaper (last|in) (year|month|week)|"
                       r"will (go|drop) (lower|further)|not a (good )?deal|meh|overpriced|been lower|"
                       r"price (was|went) (lower|down) (before|last))\b", re.I),
    "price_match_ok": re.compile(r"\b(pm'?d|price ?match(ed)? (worked|successful|approved|no problem|fine)|"
                                 r"got (them|it|best buy|staples|walmart) to (price ?)?match)\b", re.I),
    "price_match_refused": re.compile(r"\b(refused|denied|wouldn'?t|won'?t|declined|rejected) (to )?(price ?)?match|"
                                      r"pm (denied|refused|rejected)\b", re.I),
    "out_of_stock": re.compile(r"\b(oos|out of stock|sold out|no stock|backordered?)\b", re.I),
    "expired": re.compile(r"\b(dead|expired|deal (is )?over|no longer (available|on sale)|price (went|is) back up)\b", re.I),
}
COUPON_RE = re.compile(r"\b(?:code|coupon|promo)\s*[:=]?\s*([A-Z0-9]{5,16})\b")
PRICE_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?")
POST_SELECTORS = (".post_content", ".content", "[itemprop='text']", ".post-body", ".message-body", "article .body")


def extract_posts(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    for sel in POST_SELECTORS:
        found = soup.select(sel)
        if len(found) >= 1:
            return [f.get_text(" ", strip=True) for f in found if f.get_text(strip=True)]
    return [p.get_text(" ", strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 20]


def summarize(posts: list[str]) -> dict:
    counts = {k: 0 for k in SIGNALS}
    quoted: list[int] = []
    coupons: set[str] = set()
    for text in posts:
        for key, rx in SIGNALS.items():
            if rx.search(text):
                counts[key] += 1
        quoted += [c for c in (parse_price(m) for m in PRICE_RE.findall(text)) if c and 100 <= c <= 10_000_000]
        coupons.update(c for c in COUPON_RE.findall(text) if not c.isdigit())
    verdict = "mixed"
    if counts["expired"] >= 2 or counts["out_of_stock"] >= 3:
        verdict = "likely over"
    elif counts["all_time_low"] > counts["wait"] and counts["all_time_low"] >= 1:
        verdict = "crowd says good price"
    elif counts["wait"] > counts["all_time_low"] and counts["wait"] >= 1:
        verdict = "crowd says wait"
    elif not any(counts.values()):
        verdict = "no clear signal"
    return {"posts": len(posts), "signals": counts, "lowest_quoted_cents": min(quoted) if quoted else None,
            "coupons": sorted(coupons)[:5], "verdict": verdict}


def compare(summary: dict, seasonal_low_cents_before_tax: int | None) -> str | None:
    """Disagreement between the crowd and our own history, as a sentence (or None)."""
    low = summary.get("lowest_quoted_cents")
    if summary.get("verdict") == "crowd says good price" and seasonal_low_cents_before_tax and low \
            and seasonal_low_cents_before_tax < low * 0.98:
        return (f"The thread calls it a low, but PriceWatch saw ${seasonal_low_cents_before_tax / 100:,.2f} earlier "
                "this season.")
    if summary.get("verdict") == "crowd says wait" and seasonal_low_cents_before_tax and low \
            and low <= seasonal_low_cents_before_tax:
        return "The thread says wait, but this is at or below the lowest price PriceWatch has seen this season."
    return None


async def refresh(db: Session, limit: int = 10) -> int:
    """Re-read recent matched threads (under 7 days old, not checked in 2 hours)."""
    from .summary import summarize_items

    now = utcnow()
    rows = db.scalars(select(DealFeedEntry).where(
        DealFeedEntry.matched_item_id.is_not(None), DealFeedEntry.created_at >= now - timedelta(days=7),
        (DealFeedEntry.summary_checked_at.is_(None)) | (DealFeedEntry.summary_checked_at < now - timedelta(hours=2)),
    ).order_by(DealFeedEntry.created_at.desc()).limit(limit)).all()
    done = 0
    for e in rows:
        if not e.url:
            continue
        res = await runtime.get_fetcher().fetch(e.url, respect_robots=True, min_interval=60)
        e.summary_checked_at = utcnow()
        if res.outcome != "ok" or not res.html:
            db.commit()
            continue
        summ = summarize(extract_posts(res.html))
        item = db.get(Item, e.matched_item_id)
        if item is not None:
            s = summarize_items(db, [item])[item.id]
            # seasonal low is landed; compare against quoted (pre-tax) prices using the best offer's tax ratio
            low = s.get("seasonal_low_cents")
            best = s.get("best")
            if low and best and best["landed"]["landed_cents"]:
                ratio = best["landed"]["price_cents"] / best["landed"]["landed_cents"]
                low = round(low * ratio)
            summ["vs_history"] = compare(summ, low)
        e.summary = summ
        db.commit()
        done += 1
    return done
