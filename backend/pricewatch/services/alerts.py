"""Alert evaluation, de-duplication, quiet hours and delivery through Apprise."""

import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..metrics import ALERTS_TOTAL
from ..models import Alert, Item, SourceLink
from ..timeutil import utcnow
from . import settings_store

log = logging.getLogger(__name__)


def money(cents: int | None) -> str:
    if cents is None:
        return "n/a"
    return f"${cents / 100:,.2f}"


def _parse_hhmm(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


def in_quiet_hours(cfg: dict, now_utc: datetime | None = None) -> bool:
    if not cfg.get("quiet_hours_enabled"):
        return False
    tz = ZoneInfo(get_settings().timezone)
    now_utc = now_utc or utcnow()
    local = now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz).time()
    start, end = _parse_hhmm(cfg["quiet_hours_start"]), _parse_hhmm(cfg["quiet_hours_end"])
    if start <= end:
        return start <= local < end
    return local >= start or local < end


def send_apprise(urls: list[str], title: str, body: str) -> tuple[bool, str | None]:
    import apprise

    ap = apprise.Apprise()
    for url in urls:
        ap.add(url)
    if len(ap) == 0:
        return False, "No valid notification URLs"
    ok = ap.notify(title=title, body=body)
    return bool(ok), None if ok else "Apprise reported a delivery failure"


def deliver(db: Session, alert: Alert, cfg: dict | None = None, force: bool = False) -> Alert:
    cfg = cfg or settings_store.get_all(db)
    bypass = alert.rule_type in ("target", "test") and cfg.get("target_bypasses_quiet_hours", True)
    if not force and not bypass and in_quiet_hours(cfg):
        alert.status = "deferred"
        db.commit()
        return alert
    urls = settings_store.notify_urls(db)
    if not urls:
        alert.status = "logged"
        alert.error = "No notification URLs configured"
    else:
        body = alert.body + (f"\n{alert.url}" if alert.url else "")
        try:
            ok, err = send_apprise(urls, alert.title, body)
        except Exception as exc:  # noqa: BLE001
            ok, err = False, f"{type(exc).__name__}: {exc}"
        alert.status = "sent" if ok else "failed"
        alert.error = err
        if ok:
            alert.sent_at = utcnow()
    ALERTS_TOTAL.labels(rule=alert.rule_type, status=alert.status).inc()
    log.info("alert", extra={"rule": alert.rule_type, "status": alert.status, "key": alert.dedup_key})
    db.commit()
    return alert


def raise_alert(db: Session, *, item: Item | None, rule: str, key: str, title: str, body: str,
                url: str | None = None, cfg: dict | None = None) -> Alert | None:
    """Create and deliver an alert unless one with the same de-duplication key exists."""
    exists = db.scalar(select(Alert.id).where(Alert.dedup_key == key).limit(1))
    if exists:
        return None
    alert = Alert(item_id=item.id if item else None, rule_type=rule, dedup_key=key,
                  title=title, body=body, url=url)
    db.add(alert)
    db.flush()
    return deliver(db, alert, cfg)


def evaluate_item(db: Session, item: Item, summary: dict, *, source: SourceLink | None = None,
                  previous_price: int | None = None, previous_in_stock: bool | None = None,
                  previous_atl: int | None = None) -> list[Alert]:
    """Check alert triggers for an item after a new observation or a target change."""
    cfg = settings_store.get_all(db)
    raised: list[Alert] = []
    best = summary.get("best")

    def add(alert: Alert | None) -> None:
        if alert:
            raised.append(alert)

    if (cfg["alert_target"] and best and item.target_price_cents is not None
            and summary["compare_cents"] is not None and summary["compare_cents"] <= item.target_price_cents):
        basis = "landed" if cfg["target_basis"] == "landed" else "price"
        add(raise_alert(
            db, item=item, rule="target",
            key=f"target:{item.id}:{summary['compare_cents']}",
            title=f"BUY NOW: {item.name} at {money(best['landed']['price_cents'])}",
            body=(f"{best['retailer'] or 'Retailer'}: {money(best['landed']['price_cents'])} "
                  f"({money(best['landed']['landed_cents'])} landed in {cfg['province']}). "
                  f"Your target ({basis}) is {money(item.target_price_cents)}."),
            url=best["url"], cfg=cfg))

    if source is None or source.last_price_cents is None:
        return raised
    price = source.last_price_cents
    store = source.retailer.name if source.retailer else "source"

    if (cfg["alert_drop"] and previous_price and price < previous_price
            and (previous_price - price) / previous_price * 100 >= float(cfg["alert_drop_pct"])):
        pct = (previous_price - price) / previous_price * 100
        add(raise_alert(
            db, item=item, rule="drop_pct", key=f"drop:{source.id}:{price}",
            title=f"Price drop {pct:.0f}%: {item.name}",
            body=f"{store}: {money(previous_price)} to {money(price)}.", url=source.url, cfg=cfg))

    if (cfg["alert_all_time_low"] and previous_atl is not None and price < previous_atl
            and source.last_in_stock is not False):
        add(raise_alert(
            db, item=item, rule="all_time_low", key=f"atl:{item.id}:{price}",
            title=f"New all-time low: {item.name} at {money(price)}",
            body=f"{store}: {money(price)} (previous low {money(previous_atl)}).", url=source.url, cfg=cfg))

    if cfg["alert_back_in_stock"] and previous_in_stock is False and source.last_in_stock is True:
        add(raise_alert(
            db, item=item, rule="back_in_stock",
            key=f"stock:{source.id}:{utcnow():%Y-%m-%d}",
            title=f"Back in stock: {item.name}",
            body=f"{store} has it again at {money(price)}.", url=source.url, cfg=cfg))
    return raised


def check_failing_sources(db: Session, hours: int = 24) -> list[Alert]:
    cfg = settings_store.get_all(db)
    if not cfg["alert_source_failing"]:
        return []
    cutoff = utcnow() - timedelta(hours=hours)
    rows = db.scalars(
        select(SourceLink).where(SourceLink.status == "confirmed", SourceLink.consecutive_failures > 0)
    ).all()
    raised = []
    for src in rows:
        since = src.last_success_at or src.created_at
        if since > cutoff or not src.item.active:
            continue
        alert = raise_alert(
            db, item=src.item, rule="source_failing", key=f"fail:{src.id}:{since:%Y-%m-%dT%H}",
            title=f"Source failing: {src.item.name}",
            body=(f"{src.retailer.name if src.retailer else src.url} has failed for more than {hours} hours. "
                  f"Last error: {src.last_error or 'unknown'}"),
            url=src.url, cfg=cfg)
        if alert:
            raised.append(alert)
    return raised


def flush_deferred(db: Session) -> int:
    cfg = settings_store.get_all(db)
    if in_quiet_hours(cfg):
        return 0
    rows = db.scalars(select(Alert).where(Alert.status == "deferred")).all()
    for alert in rows:
        deliver(db, alert, cfg, force=True)
    return len(rows)
