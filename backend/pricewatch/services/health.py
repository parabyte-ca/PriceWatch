"""Health check: which stores and sources are failing, and how much of the search and Claude budgets is used.

Shown on the System page and summarised in the admin's weekly report, so a quietly broken store or a budget about to
run out is noticed before Black Friday rather than during it.
"""

import calendar
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import DealFeedEntry, FetchRun, Item, Retailer, SourceLink
from ..serp import available_providers
from ..timeutil import utcnow
from . import claude, settings_store


def report(db: Session) -> dict:
    now = utcnow()
    week = now - timedelta(days=7)
    issues: list[str] = []

    # stores: success rate of the last week's checks (search-priced stores are judged by their search prices)
    stores = []
    rows = db.execute(select(FetchRun.domain, FetchRun.status, func.count())
                      .where(FetchRun.started_at >= week).group_by(FetchRun.domain, FetchRun.status)).all()
    by_domain: dict[str, dict[str, int]] = {}
    for domain, st, n in rows:
        by_domain.setdefault(domain, {})[st] = n
    paused = {r.domain: r.backoff_until for r in db.scalars(select(Retailer)).all()
              if r.backoff_until and r.backoff_until > now}
    for domain, counts in sorted(by_domain.items()):
        total = sum(counts.values())
        ok = counts.get("ok", 0) + counts.get("not_modified", 0) + counts.get("excluded", 0)
        rate = round(ok * 100 / total) if total else None
        stores.append({"domain": domain, "checks": total, "success_pct": rate, "paused": domain in paused})
        if total >= 5 and rate is not None and rate < 50:
            issues.append(f"{domain}: only {rate}% of {total} checks worked this week")
    for d in paused:
        if d not in by_domain:
            stores.append({"domain": d, "checks": 0, "success_pct": None, "paused": True})

    # watched stores with no price for over a day
    stale_cut = now - timedelta(hours=24)
    stale = db.scalars(select(SourceLink).join(Item, Item.id == SourceLink.item_id).where(
        Item.active.is_(True), SourceLink.status == "confirmed", ~SourceLink.url.startswith("manual://"),
        (SourceLink.last_success_at.is_(None)) | (SourceLink.last_success_at < stale_cut))).all()
    if stale:
        issues.append(f"{len(stale)} watched store(s) have no fresh price for over a day")

    # items with no price at all
    no_price = [i.name for i in db.scalars(select(Item).where(Item.active.is_(True))).all()
                if not any(s.status == "confirmed" and s.last_price_cents is not None for s in i.sources)]
    if no_price:
        issues.append(f"{len(no_price)} item(s) have no price yet")

    # search budget: used against the month's pace
    from .discovery import month_usage

    limit = int(settings_store.get(db, "serp_monthly_limit") or 0)
    days = calendar.monthrange(now.year, now.month)[1]
    searches = []
    for name in available_providers():
        if name == "claude":
            continue
        used = month_usage(db, name)
        pace = round(limit * now.day / days) if limit else None
        searches.append({"provider": name, "used": used, "limit": limit or None, "pace": pace})
        if limit and used >= limit:
            issues.append(f"{name}: the monthly search limit is used up ({used}/{limit}); prices pause until next month")
        elif limit and used > limit * 0.9:
            issues.append(f"{name}: {used} of {limit} searches used this month")
    if not available_providers():
        issues.append("No search provider: add SERPAPI_KEY or a Claude key, or prices across stores cannot refresh")

    # Claude spending
    cfg = claude.config(db)
    spent = claude.spend(db)
    cap = cfg["monthly_cap_usd"] or None
    claude_info = {"key": bool(claude.api_key()), "spent_usd": spent["usd"], "cap_usd": cap,
                   "checks": spent["checks"], "searches": spent["searches"]}
    if cap and spent["usd"] >= cap * 0.9:
        issues.append(f"Claude: US${spent['usd']:.2f} of the US${cap:.0f} monthly cap used")

    # the forum feed
    last_feed = db.scalar(select(func.max(DealFeedEntry.created_at)))
    if settings_store.get(db, "deal_feed_enabled") and (last_feed is None or last_feed < now - timedelta(hours=6)):
        issues.append("RedFlagDeals feed: no new threads in 6 hours")

    # backups
    backups = sorted((get_settings().data_dir / "backups").glob("pricewatch-*"), key=lambda p: p.stat().st_mtime)
    last_backup = backups[-1].stat().st_mtime if backups else None
    if last_backup is None or (now.timestamp() - last_backup) > 2 * 86400:
        issues.append("No database backup in the last 2 days")

    return {"ok": not issues, "issues": issues, "stores": stores, "stale_sources": len(stale),
            "items_without_price": no_price[:10], "searches": searches, "claude": claude_info,
            "deal_feed_last": last_feed, "last_backup_epoch": last_backup}


def summary_line(db: Session) -> str:
    r = report(db)
    if r["ok"]:
        return "Health: all good."
    return "Health: " + "; ".join(r["issues"][:5]) + "."
