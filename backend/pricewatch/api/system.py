"""Settings, retailers, alerts, system health."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .. import __version__
from ..config import get_settings
from ..db import get_db
from ..models import Alert, FetchRun, Item, Retailer, SourceLink
from ..pricing import PROVINCE_TAX
from ..schemas import AlertOut, RetailerOut, RetailerUpdate
from ..serp import available_providers
from ..services import alerts, settings_store
from ..services.discovery import month_usage
from ..timeutil import utcnow

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/settings")
def get_settings_api(db: Session = Depends(get_db)):
    values = settings_store.public_view(settings_store.get_all(db))
    values["provinces"] = {k: {"name": v[0], "rate": float(v[1])} for k, v in PROVINCE_TAX.items()}
    values["timezone"] = get_settings().timezone
    return values


@router.patch("/settings")
def patch_settings(body: dict, db: Session = Depends(get_db)):
    body = {k: v for k, v in body.items() if k in settings_store.DEFAULTS}
    if "province" in body and str(body["province"]).upper() not in PROVINCE_TAX:
        raise HTTPException(422, "Unknown province")
    if "province" in body:
        body["province"] = str(body["province"]).upper()
    if "notify_urls" in body:
        urls = body["notify_urls"]
        if not isinstance(urls, list) or not all(isinstance(u, str) for u in urls):
            raise HTTPException(422, "notify_urls must be a list of strings")
        # masked values coming back from the UI mean "keep the existing URL"
        current = settings_store.get(db, "notify_urls") or []
        masked = {settings_store.mask_url(u): u for u in current}
        body["notify_urls"] = [masked.get(u, u) for u in urls if u.strip()]
    numeric = {"match_threshold": (50, 100), "serp_monthly_limit": (0, 100000), "alert_drop_pct": (1, 90),
               "fake_sale_pct": (0, 50), "good_within_pct": (0, 50)}
    for key, (lo, hi) in numeric.items():
        if key in body:
            try:
                value = float(body[key])
            except (TypeError, ValueError) as exc:
                raise HTTPException(422, f"{key} must be a number") from exc
            if not lo <= value <= hi:
                raise HTTPException(422, f"{key} must be between {lo} and {hi}")
    for key in ("quiet_hours_start", "quiet_hours_end"):
        if key in body:
            try:
                alerts._parse_hhmm(body[key])
            except (ValueError, AttributeError) as exc:
                raise HTTPException(422, f"{key} must be HH:MM") from exc
    values = settings_store.update(db, body)
    return settings_store.public_view(values)


@router.post("/settings/test-alert")
def test_alert(db: Session = Depends(get_db)):
    alert = Alert(rule_type="test", dedup_key=f"test:{utcnow().isoformat()}", title="PriceWatch CA test alert",
                  body="If you can read this, notifications work.")
    db.add(alert)
    db.flush()
    alerts.deliver(db, alert, force=True)
    return AlertOut.model_validate(alert)


@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(limit: int = 100, db: Session = Depends(get_db)):
    return db.scalars(select(Alert).order_by(Alert.created_at.desc()).limit(min(limit, 500))).all()


@router.get("/retailers", response_model=list[RetailerOut])
def list_retailers(db: Session = Depends(get_db)):
    return db.scalars(select(Retailer).order_by(Retailer.name)).all()


@router.patch("/retailers/{retailer_id}", response_model=RetailerOut)
def update_retailer(retailer_id: int, body: RetailerUpdate, db: Session = Depends(get_db)):
    r = db.get(Retailer, retailer_id)
    if r is None:
        raise HTTPException(404, "Retailer not found")
    changes = body.model_dump(exclude_unset=True)
    if changes.pop("clear_backoff", None):
        r.backoff_until = None
        r.backoff_seconds = 0
    for key, value in changes.items():
        setattr(r, key, value)
    db.commit()
    return r


@router.get("/system")
def system(db: Session = Depends(get_db)):
    now = utcnow()
    s = get_settings()

    def health(since):
        rows = db.execute(
            select(
                FetchRun.domain,
                func.count(FetchRun.id),
                func.sum(case((FetchRun.status.in_(["ok", "not_modified"]), 1), else_=0)),
                func.max(FetchRun.started_at),
                func.avg(FetchRun.duration_ms),
            ).where(FetchRun.started_at >= since).group_by(FetchRun.domain)
        ).all()
        return {
            d: {"total": t, "ok": int(ok or 0), "success_rate": round((ok or 0) / t * 100, 1) if t else None,
                "last": last.isoformat() + "Z" if last else None, "avg_ms": int(avg or 0)}
            for d, t, ok, last, avg in rows
        }

    day, week = health(now - timedelta(days=1)), health(now - timedelta(days=7))
    domains = sorted(set(day) | set(week))
    retailers = {r.domain: r for r in db.scalars(select(Retailer)).all()}
    recent = db.scalars(select(FetchRun).order_by(FetchRun.started_at.desc()).limit(50)).all()
    return {
        "version": __version__,
        "time": now.isoformat() + "Z",
        "timezone": s.timezone,
        "scheduler_enabled": s.scheduler_enabled,
        "browser_enabled": s.browser_enabled,
        "items": db.scalar(select(func.count(Item.id)).where(Item.active.is_(True))),
        "sources": db.scalar(select(func.count(SourceLink.id)).where(SourceLink.status == "confirmed")),
        "due_now": db.scalar(select(func.count(SourceLink.id)).where(
            SourceLink.status == "confirmed", SourceLink.next_check_at <= now)),
        "search_providers": [
            {"name": n, "used_this_month": month_usage(db, n),
             "limit": int(settings_store.get(db, "serp_monthly_limit") or 0)} for n in available_providers()
        ],
        "domains": [
            {"domain": d, "day": day.get(d), "week": week.get(d),
             "backoff_until": (retailers[d].backoff_until.isoformat() + "Z")
             if d in retailers and retailers[d].backoff_until else None}
            for d in domains
        ],
        "recent_runs": [
            {"id": r.id, "source_link_id": r.source_link_id, "domain": r.domain,
             "started_at": r.started_at.isoformat() + "Z", "duration_ms": r.duration_ms, "status": r.status,
             "http_status": r.http_status, "method": r.method, "error": r.error}
            for r in recent
        ],
    }
