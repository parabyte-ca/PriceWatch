"""Sale-mode readiness: a checklist an admin can run before Black Friday or Boxing Week.

Each check returns ok, warn or fail with a plain sentence. The load check is a dry run: it estimates how many
requests each store would get per hour with the sale-mode schedule and compares that with the polite per-store
spacing, so overloaded stores show up before the rush instead of during it.
"""

import shutil
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import FetchRun, Item, PushSubscription, Retailer, SourceLink, User
from ..timeutil import utcnow
from . import events, settings_store


def _check(key: str, status: str, title: str, detail: str = "") -> dict:
    return {"key": key, "status": status, "title": title, "detail": detail}


def load_plan(db: Session, cfg: dict) -> list[dict]:
    """Expected requests per hour per store with the sale-mode schedule, against polite capacity."""
    s = get_settings()
    hot_ids = events.blackfriday_item_ids(db)
    rows = db.execute(select(SourceLink, Item).join(Item, Item.id == SourceLink.item_id).where(
        SourceLink.status == "confirmed", Item.active.is_(True))).all()
    per_hour: dict[str, float] = defaultdict(float)
    retailers = {r.id: r for r in db.scalars(select(Retailer)).all()}
    for src, item in rows:
        r = retailers.get(src.retailer_id)
        mode = src.fetch_mode or (r.fetch_mode if r else "auto")
        if mode in ("manual", "changedetection", "keepa") or src.url.startswith("manual://"):
            continue
        minutes = (s.blackfriday_interval_minutes if item.id in hot_ids
                   else s.hot_interval_minutes if item.hot else s.default_interval_minutes)
        per_hour[r.domain if r else src.url] += 60 / max(5, minutes)
    out = []
    for domain, rate in sorted(per_hour.items(), key=lambda kv: -kv[1]):
        r = next((x for x in retailers.values() if x.domain == domain), None)
        spacing = max(s.min_domain_interval, (r.min_interval_seconds or 0) if r else 0) * (1 + s.domain_jitter / 2)
        capacity = 3600 / spacing if spacing else 3600
        out.append({"domain": domain, "requests_per_hour": round(rate, 1), "capacity_per_hour": round(capacity, 1),
                    "load_pct": round(rate / capacity * 100, 1), "browser": bool(r and r.fetch_mode == "browser")})
    return out


def run(db: Session) -> dict:
    s = get_settings()
    cfg = settings_store.get_all(db)
    now = utcnow()
    checks = []

    windows = events.sale_windows(cfg)
    local = events.local_now()
    upcoming = [(n, a, b) for n, a, b in windows if b >= local]
    if upcoming:
        n, a, b = upcoming[0]
        checks.append(_check("sale_mode", "ok", f"{n} mode is on",
                             f"{a:%a %b %d %H:%M} to {b:%a %b %d %H:%M}; top {s.blackfriday_max_items} hot items "
                             f"every {s.blackfriday_interval_minutes} minutes."))
    else:
        checks.append(_check("sale_mode", "warn", "No sale mode coming up",
                             "Turn on Black Friday or Boxing Week mode in Settings for faster checks."))

    checks.append(_check("scheduler", "ok" if s.scheduler_enabled else "fail",
                         "Scheduler running" if s.scheduler_enabled else "Scheduler is off",
                         "" if s.scheduler_enabled else "PRICEWATCH_SCHEDULER_ENABLED is false: nothing is checked."))

    hot = db.scalars(select(Item).where(Item.active.is_(True), Item.hot.is_(True))).all()
    no_src = [i.name for i in hot if not any(x.status == "confirmed" for x in i.sources)]
    checks.append(_check("hot_sources", "warn" if no_src else "ok",
                         f"{len(no_src)} hot item(s) with no confirmed store" if no_src
                         else f"All {len(hot)} hot items have a confirmed store",
                         ", ".join(no_src[:8])))
    if len(hot) > s.blackfriday_max_items:
        checks.append(_check("hot_count", "warn", f"{len(hot)} hot items, only {s.blackfriday_max_items} get "
                             "30-minute checks", "The rest are checked every 2 hours; lower priority numbers win."))

    stale = db.scalars(select(SourceLink).join(Item, Item.id == SourceLink.item_id).where(
        SourceLink.status == "confirmed", Item.active.is_(True), ~SourceLink.url.startswith("manual://"),
        (SourceLink.last_success_at.is_(None)) | (SourceLink.last_success_at < now - timedelta(hours=24)))).all()
    checks.append(_check("stale", "warn" if stale else "ok",
                         f"{len(stale)} store link(s) without a good check in 24 hours" if stale
                         else "Every store link checked successfully in the last 24 hours",
                         ", ".join(sorted({(x.retailer.domain if x.retailer else x.url) for x in stale})[:10])))

    rows = db.execute(select(FetchRun.domain, func.count(FetchRun.id),
                             func.sum(case((FetchRun.status.in_(["ok", "not_modified"]), 1), else_=0)))
                      .where(FetchRun.started_at >= now - timedelta(days=2)).group_by(FetchRun.domain)).all()
    weak = [f"{d} {round((ok or 0) / t * 100)}%" for d, t, ok in rows if t >= 3 and (ok or 0) / t < 0.8]
    backoff = [r.domain for r in db.scalars(select(Retailer).where(Retailer.backoff_until > now)).all()]
    if backoff:
        checks.append(_check("blocked", "fail", f"{len(backoff)} store(s) paused after blocks",
                             ", ".join(backoff) + ". Try browser mode, changedetection.io, or log prices by hand."))
    checks.append(_check("success", "warn" if weak else "ok",
                         f"{len(weak)} store(s) under 80% success (48 h)" if weak else "Stores answering well (48 h)",
                         ", ".join(weak)))

    plan = load_plan(db, cfg)
    over = [p for p in plan if p["load_pct"] > 100]
    tight = [p for p in plan if 70 < p["load_pct"] <= 100]
    if over:
        checks.append(_check("load", "fail", f"{len(over)} store(s) would fall behind in sale mode",
                             "; ".join(f"{p['domain']} needs {p['requests_per_hour']}/h, polite limit "
                                       f"{p['capacity_per_hour']}/h" for p in over)
                             + ". Make fewer items hot, or remove duplicate links for that store."))
    else:
        checks.append(_check("load", "warn" if tight else "ok",
                             "Sale-mode load is close to the polite limit" if tight
                             else "Sale-mode load fits within polite limits",
                             "; ".join(f"{p['domain']} {p['load_pct']}%" for p in tight)))

    if s.browser_enabled:
        b = db.execute(select(func.count(FetchRun.id), func.sum(case((FetchRun.status == "ok", 1), else_=0)))
                       .where(FetchRun.method == "browser", FetchRun.started_at >= now - timedelta(days=2))).one()
        total, ok = b[0] or 0, b[1] or 0
        if total and ok == 0:
            checks.append(_check("browser", "fail", "Browser checks are all failing",
                                 "Check that the browser container is running (docker compose ps)."))
        else:
            checks.append(_check("browser", "ok", "Browser sidecar enabled",
                                 f"{ok} of {total} browser checks succeeded in 48 hours." if total else ""))

    users = db.scalars(select(User).where(User.active.is_(True))).all()
    quiet = []
    for u in users:
        urls = settings_store.notify_urls(db, u.id)
        pushes = db.scalar(select(func.count(PushSubscription.id)).where(PushSubscription.user_id == u.id))
        if not urls and not pushes:
            quiet.append(u.display_name)
    checks.append(_check("notify", "warn" if quiet else "ok",
                         f"{len(quiet)} person(s) would get no alerts" if quiet else "Everyone can receive alerts",
                         ("No notification URL or app notifications: " + ", ".join(quiet)) if quiet else ""))

    backups = sorted((s.data_dir / "backups").glob("*.sqlite")) + sorted((s.data_dir / "backups").glob("*.db"))
    newest = max((p.stat().st_mtime for p in backups), default=None)
    age_h = (datetime.now(UTC).timestamp() - newest) / 3600 if newest else None
    checks.append(_check("backup", "ok" if age_h is not None and age_h < 36 else "warn",
                         f"Latest backup {age_h:.0f} hours old" if age_h is not None else "No backup yet",
                         "A copy is also taken automatically in the 6 hours before each sale mode starts."))

    try:
        free_gb = shutil.disk_usage(s.data_dir).free / 1e9
        checks.append(_check("disk", "ok" if free_gb > 1 else "warn", f"{free_gb:.1f} GB free for data"))
    except OSError:
        pass

    order = {"fail": 0, "warn": 1, "ok": 2}
    checks.sort(key=lambda c: order[c["status"]])
    overall = checks[0]["status"] if checks else "ok"
    return {"overall": overall, "checks": checks, "load": plan[:20], "generated_at": now.isoformat() + "Z"}
