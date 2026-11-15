"""Alerts: instant pushes for BUY / BUY + PROTECT transitions and back-in-stock, a daily digest for the rest.

ntfy targets get action buttons (Bought, Snooze 24h, Raise target) when PRICEWATCH_PUBLIC_URL is set;
every other Apprise target gets plain text.
"""

import logging
import re
from datetime import datetime, time, timedelta
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

import httpx
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..metrics import ALERTS_TOTAL
from ..models import Alert, Item, Retailer, SourceLink, User, UserItemPref
from ..timeutil import utcnow
from . import events, settings_store

log = logging.getLogger(__name__)

INSTANT_RULES = {"buy", "back_in_stock", "domain_blocked", "test", "protection"}
ACTION_MAX_AGE = 7 * 24 * 3600


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


# ---------- signed action links ----------

def _serializer() -> URLSafeTimedSerializer:
    from ..auth import load_secret_key

    return URLSafeTimedSerializer(load_secret_key(get_settings()), salt="pricewatch-action")


def action_token(item_id: int, action: str, user_id: int | None = None) -> str:
    return _serializer().dumps({"i": item_id, "a": action, "u": user_id})


def read_action_token(token: str) -> tuple[int, str, int | None] | None:
    try:
        data = _serializer().loads(token, max_age=ACTION_MAX_AGE)
    except BadSignature:
        return None
    return int(data["i"]), str(data["a"]), data.get("u")


# ---------- delivery ----------

NTFY_RE = re.compile(r"^ntfys?://", re.I)


def parse_ntfy(url: str) -> dict | None:
    """Apprise-style ntfy URL -> publish settings. ntfy://topic, ntfys://host/topic, ntfys://user:pass@host/topic,
    ntfys://tk_token@host/topic."""
    if not NTFY_RE.match(url):
        return None
    secure = url.lower().startswith("ntfys")
    parts = urlsplit(url)
    path = [p for p in parts.path.split("/") if p]
    auth = None
    if parts.username and parts.password:
        auth = ("basic", parts.username, parts.password)
    elif parts.username:
        auth = ("token", parts.username, None)
    host = parts.hostname
    if not path:  # ntfy://topic
        return {"base": "https://ntfy.sh", "topic": host, "auth": auth}
    netloc = host + (f":{parts.port}" if parts.port else "")
    return {"base": f"{'https' if secure else 'http'}://{netloc}", "topic": path[0], "auth": auth}


def ntfy_actions(alert: Alert) -> list[dict]:
    base = get_settings().public_url.rstrip("/")
    if not base or not alert.item_id:
        return []
    item_url = f"{base}/items/{alert.item_id}"
    return [
        {"action": "view", "label": "Bought", "url": f"{item_url}?action=bought", "clear": True},
        {"action": "http", "label": "Snooze 24h", "method": "POST",
         "url": f"{base}/api/actions/{quote(action_token(alert.item_id, 'snooze', alert.user_id))}", "clear": True},
        {"action": "view", "label": "Raise target", "url": f"{item_url}?action=target"},
    ]


def send_ntfy(cfg: dict, alert: Alert, client: httpx.Client | None = None) -> None:
    payload = {"topic": cfg["topic"], "title": alert.title, "message": alert.body,
               "priority": 4 if alert.rule_type in ("buy", "protection") else 3,
               "tags": ["shopping_cart"] if alert.rule_type == "buy" else []}
    if alert.url:
        payload["click"] = alert.url
    actions = ntfy_actions(alert)
    if actions:
        payload["actions"] = actions
    headers = {}
    auth = None
    if cfg["auth"] and cfg["auth"][0] == "token":
        headers["Authorization"] = f"Bearer {cfg['auth'][1]}"
    elif cfg["auth"]:
        auth = (cfg["auth"][1], cfg["auth"][2])
    own = client is None
    client = client or httpx.Client(timeout=15)
    try:
        resp = client.post(cfg["base"] + "/", json=payload, headers=headers, auth=auth)
        resp.raise_for_status()
    finally:
        if own:
            client.close()


def send_apprise(urls: list[str], title: str, body: str) -> tuple[bool, str | None]:
    import apprise

    ap = apprise.Apprise()
    for url in urls:
        ap.add(url)
    if len(ap) == 0:
        return False, "No valid notification URLs"
    ok = ap.notify(title=title, body=body)
    return bool(ok), None if ok else "Apprise reported a delivery failure"


def send_all(urls: list[str], alert: Alert) -> tuple[bool, str | None]:
    errors, sent = [], 0
    others = []
    for url in urls:
        cfg = parse_ntfy(url)
        if cfg:
            try:
                send_ntfy(cfg, alert)
                sent += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"ntfy: {type(exc).__name__}")
        else:
            others.append(url)
    if others:
        body = alert.body + (f"\n{alert.url}" if alert.url else "")
        ok, err = send_apprise(others, alert.title, body)
        sent += 1 if ok else 0
        if err:
            errors.append(err)
    return sent > 0, "; ".join(errors) or None


def deliver(db: Session, alert: Alert, cfg: dict | None = None, force: bool = False) -> Alert:
    cfg = cfg or settings_store.get_all(db, alert.user_id)
    bypass = alert.rule_type in ("buy", "test", "protection") and cfg.get("target_bypasses_quiet_hours", True)
    if not force and not bypass and in_quiet_hours(cfg):
        alert.status = "deferred"
        db.commit()
        return alert
    urls = settings_store.notify_urls(db, alert.user_id)
    if not urls:
        alert.status = "logged"
        alert.error = "No notification URLs configured"
    else:
        try:
            ok, err = send_all(urls, alert)
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
                url: str | None = None, cfg: dict | None = None, instant: bool = True,
                user_id: int | None = None) -> Alert | None:
    """Create an alert for one person unless one with the same key exists. Non-instant alerts wait for the digest."""
    if user_id is None:
        user_id = settings_store._admin_id(db)
    key = f"u{user_id}:{key}"
    exists = db.scalar(select(Alert.id).where(Alert.dedup_key == key).limit(1))
    if exists:
        return None
    alert = Alert(item_id=item.id if item else None, rule_type=rule, dedup_key=key, title=title, body=body, url=url,
                  user_id=user_id)
    db.add(alert)
    db.flush()
    if not instant:
        alert.status = "digest"
        db.commit()
        return alert
    return deliver(db, alert, cfg)


def _recent(db: Session, item_id: int, rule: str, hours: float, user_id: int | None) -> bool:
    since = utcnow() - timedelta(hours=hours)
    return db.scalar(select(Alert.id).where(Alert.item_id == item_id, Alert.rule_type == rule,
                                            Alert.user_id == user_id, Alert.created_at >= since).limit(1)) is not None


def snoozed(db: Session, user_id: int, item: Item) -> bool:
    pref = db.get(UserItemPref, (user_id, item.id))
    if pref and (pref.muted or (pref.snoozed_until and pref.snoozed_until > utcnow())):
        return True
    return False


def evaluate_item(db: Session, item: Item, summary: dict | None = None, *, source: SourceLink | None = None,
                  previous_price: int | None = None, previous_in_stock: bool | None = None,
                  previous_atl: int | None = None) -> list[Alert]:
    """Alerts after a new observation or a target change, for every member of the item's list."""
    from .summary import summarize_items
    from .users import members_of

    raised: list[Alert] = []
    for user in members_of(db, item.list_id):
        if snoozed(db, user.id, item):
            continue
        user_summary = summarize_items(db, [item], user.id)[item.id]
        raised += _evaluate_for(db, user, item, user_summary, source, previous_price, previous_in_stock, previous_atl)
    return raised


def _evaluate_for(db: Session, user: User, item: Item, summary: dict, source: SourceLink | None,
                  previous_price: int | None, previous_in_stock: bool | None,
                  previous_atl: int | None) -> list[Alert]:
    cfg = settings_store.get_all(db, user.id)
    raised: list[Alert] = []
    best = summary.get("best")
    bf = events.blackfriday_active(cfg)
    uid = user.id

    def add(alert: Alert | None) -> None:
        if alert:
            raised.append(alert)

    if cfg["alert_target"] and best and summary["decision"] in ("BUY", "BUY_AND_PROTECT"):
        landed = best["landed"]["landed_cents"]
        if not (bf and _recent(db, item.id, "buy", 2, uid)):
            label = "BUY NOW" if summary["decision"] == "BUY" else "BUY + PROTECT"
            add(raise_alert(
                db, item=item, rule="buy", key=f"buy:{item.id}:{summary['decision']}:{landed}", user_id=uid,
                title=f"{label}: {item.name} at {money(best['landed']['price_cents'])}",
                body=(f"{best['retailer'] or 'Retailer'}: {money(best['landed']['price_cents'])} "
                      f"({money(landed)} landed in {cfg['province']}). {summary['decision_reason']}. "
                      f"Seasonal low {money(summary['seasonal_low_cents'])}, history {summary['history_confidence']}."
                      + (f" Target {money(item.target_price_cents)}." if item.target_price_cents else "")),
                url=best["url"], cfg=cfg))

    if source is None or source.last_price_cents is None:
        return raised
    price = source.last_price_cents
    store = source.retailer.name if source.retailer else "source"

    if cfg["alert_back_in_stock"] and previous_in_stock is False and source.last_in_stock is True:
        add(raise_alert(
            db, item=item, rule="back_in_stock", key=f"stock:{source.id}:{utcnow():%Y-%m-%d}", user_id=uid,
            title=f"Back in stock: {item.name}", body=f"{store} has it again at {money(price)}.",
            url=source.url, cfg=cfg))

    if previous_price and price < previous_price and \
            (previous_price - price) / previous_price * 100 >= float(cfg["alert_drop_pct"]):
        pct = (previous_price - price) / previous_price * 100
        add(raise_alert(
            db, item=item, rule="drop_pct", key=f"drop:{source.id}:{price}", user_id=uid,
            title=f"Price drop {pct:.0f}%: {item.name}", body=f"{store}: {money(previous_price)} to {money(price)}.",
            url=source.url, cfg=cfg, instant=bool(cfg["alert_drop"])))

    if previous_atl is not None and price < previous_atl and source.last_in_stock is not False:
        add(raise_alert(
            db, item=item, rule="all_time_low", key=f"atl:{item.id}:{price}", user_id=uid,
            title=f"New low: {item.name} at {money(price)}",
            body=f"{store}: {money(price)} (previous low {money(previous_atl)}).",
            url=source.url, cfg=cfg, instant=bool(cfg["alert_all_time_low"])))
    return raised


def domain_blocked(db: Session, retailer: Retailer) -> Alert | None:
    """Operational alert: goes to the household admins."""
    sent = None
    for admin in db.scalars(select(User).where(User.role == "admin", User.active.is_(True))).all():
        sent = _domain_blocked_for(db, retailer, admin.id) or sent
    return sent


def _domain_blocked_for(db: Session, retailer: Retailer, user_id: int) -> Alert | None:
    cfg = settings_store.get_all(db, user_id)
    until = events.local_now(retailer.backoff_until) if retailer.backoff_until else None
    return raise_alert(
        db, item=None, rule="domain_blocked", user_id=user_id, key=f"blocked:{retailer.domain}:{utcnow():%Y-%m-%dT%H}",
        title=f"{retailer.name} is blocking checks",
        body=(f"{retailer.consecutive_blocks} blocked fetches in a row on {retailer.domain}. Paused until "
              f"{until:%a %H:%M}" if until else f"{retailer.consecutive_blocks} blocked fetches on {retailer.domain}.")
        + " Add prices by hand meanwhile.",
        cfg=cfg, instant=bool(cfg.get("alert_domain_blocked", True)))


def check_failing_sources(db: Session, hours: int = 24) -> list[Alert]:
    from .users import members_of

    cutoff = utcnow() - timedelta(hours=hours)
    rows = db.scalars(
        select(SourceLink).where(SourceLink.status == "confirmed", SourceLink.consecutive_failures > 0)
    ).all()
    raised = []
    for src in rows:
        since = src.last_success_at or src.created_at
        if since > cutoff or not src.item.active:
            continue
        for user in members_of(db, src.item.list_id):
            cfg = settings_store.get_all(db, user.id)
            alert = raise_alert(
                db, item=src.item, rule="source_failing", key=f"fail:{src.id}:{since:%Y-%m-%dT%H}", user_id=user.id,
                title=f"Source failing: {src.item.name}",
                body=(f"{src.retailer.name if src.retailer else src.url} has failed for more than {hours} hours. "
                      f"Last error: {src.last_error or 'unknown'}"),
                url=src.url, cfg=cfg, instant=bool(cfg["alert_source_failing"]))
            if alert:
                raised.append(alert)
    return raised


def flush_deferred(db: Session) -> int:
    count = 0
    for alert in db.scalars(select(Alert).where(Alert.status == "deferred")).all():
        cfg = settings_store.get_all(db, alert.user_id)
        if in_quiet_hours(cfg):
            continue
        deliver(db, alert, cfg, force=True)
        count += 1
    return count


# ---------- digest ----------

def build_digest(db: Session, user_id: int | None = None) -> tuple[str, str]:
    from .summary import summarize_items
    from .users import list_ids

    if user_id is None:
        user_id = settings_store._admin_id(db)
    user = db.get(User, user_id) if user_id else None
    q = select(Item).where(Item.active.is_(True))
    if user is not None:
        q = q.where(Item.list_id.in_(list_ids(db, user)))
    items = list(db.scalars(q).all())
    summaries = summarize_items(db, items, user_id)
    local = events.local_now()
    with_data = [(i, summaries[i.id]) for i in items if summaries[i.id]["distance_to_low_pct"] is not None]
    with_data.sort(key=lambda x: (x[1]["decision"] not in ("BUY", "BUY_AND_PROTECT"), x[1]["distance_to_low_pct"]))
    lines = []
    if with_data:
        lines.append("Closest to the seasonal low:")
        for item, s in with_data[:10]:
            lines.append(f"- {s['badge']}: {item.name} {money(s['best_landed_cents'])} landed, "
                         f"{s['distance_to_low_pct']:+.1f}% vs low {money(s['seasonal_low_cents'])} "
                         f"({s['history_confidence']}, {s['best']['retailer'] if s['best'] else ''})")
    opps = [(i, s) for i, s in ((i, summaries[i.id]) for i in items) if s["price_match"]]
    if opps:
        lines.append("Price match opportunities:")
        for item, s in opps[:5]:
            o = s["price_match"][0]
            lines.append(f"- {item.name}: ask {o['at']} to match {o['match_to']} at {money(o['price_cents'])}")
    stale = [i for i in items if summaries[i.id]["stale"] and summaries[i.id]["source_count"]]
    if stale:
        lines.append(f"No successful check in 24 hours ({len(stale)}): " + ", ".join(i.name for i in stale[:8]))
    blocked = db.scalars(select(Retailer).where(Retailer.backoff_until > utcnow())).all()
    if blocked and user is not None and user.role == "admin":
        lines.append("Paused domains: " + ", ".join(f"{r.domain} until {events.local_now(r.backoff_until):%a %H:%M}"
                                                     for r in blocked))
    pending = db.scalars(select(Alert).where(Alert.status == "digest", Alert.user_id == user_id)).all()
    if pending:
        lines.append("Other changes:")
        lines.extend(f"- {a.title}" for a in pending[:10])
        for a in pending:
            a.status = "in_digest"
    if not lines:
        lines.append("Nothing to report yet. Add items and let history build.")
    title = f"PriceWatch digest, {local:%a %b} {local.day}"
    return title, "\n".join(lines)


def maybe_send_digest(db: Session, now_utc: datetime | None = None) -> list[Alert]:
    sent = []
    for user in db.scalars(select(User).where(User.active.is_(True))).all():
        alert = _maybe_digest_for(db, user.id, now_utc)
        if alert:
            sent.append(alert)
    return sent


def _maybe_digest_for(db: Session, user_id: int, now_utc: datetime | None = None) -> Alert | None:
    cfg = settings_store.get_all(db, user_id)
    if not cfg.get("digest_enabled", True):
        return None
    local = events.local_now(now_utc)
    slots = [("am", cfg["digest_time"])]
    if events.blackfriday_active(cfg, now_utc):
        slots.append(("pm", cfg["digest_time_blackfriday"]))
    for slot, hhmm in slots:
        at = _parse_hhmm(hhmm)
        if local.time() < at or local.time() > (datetime.combine(local.date(), at) + timedelta(hours=3)).time():
            continue
        key = f"digest:{local.date().isoformat()}:{slot}"
        if db.scalar(select(Alert.id).where(Alert.dedup_key == f"u{user_id}:{key}")):
            continue
        title, body = build_digest(db, user_id)
        return raise_alert(db, item=None, rule="digest", key=key, title=title, body=body, cfg=cfg, user_id=user_id)
    return None
