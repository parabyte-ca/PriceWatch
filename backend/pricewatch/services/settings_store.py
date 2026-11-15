"""Settings stored in the database, with defaults. Secrets are masked when read for the UI."""

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import SettingKV, User, UserSetting

DEFAULTS: dict = {
    "province": "ON",
    "target_basis": "price",  # price (before tax) | landed (after tax and shipping)
    "quiet_hours_enabled": False,
    "quiet_hours_start": "22:00",
    "quiet_hours_end": "07:30",
    "target_bypasses_quiet_hours": True,
    "notify_urls": [],
    "alert_target": True,
    "alert_drop": False,
    "alert_drop_pct": 10.0,
    "alert_all_time_low": False,
    "alert_back_in_stock": True,
    "alert_source_failing": False,
    "alert_domain_blocked": True,
    "fake_sale_pct": 5.0,
    "good_within_pct": 3.0,
    "browser_fallback": True,
    "match_threshold": 85.0,
    "auto_confirm_gtin": False,
    "serp_monthly_limit": 200,
    "discover_on_add": True,
    "season_start": "2026-10-01",
    "blackfriday_mode": True,
    "blackfriday_start": "2026-11-26T00:00",
    "blackfriday_end": "2026-12-01T23:59",
    "buy_within_pct": 2.0,
    "protect_within_pct": 5.0,
    "digest_enabled": True,
    "digest_time": "07:30",
    "digest_time_blackfriday": "19:30",
    "my_best_buy_member": False,
    "tax_overrides": {},
}

SECRET_KEYS = {"notify_urls"}

# Per-person settings (each household member has their own); everything else is household-wide.
USER_KEYS = {
    "province", "target_basis", "quiet_hours_enabled", "quiet_hours_start", "quiet_hours_end",
    "target_bypasses_quiet_hours", "notify_urls", "alert_target", "alert_drop", "alert_drop_pct",
    "alert_all_time_low", "alert_back_in_stock", "alert_source_failing", "alert_domain_blocked",
    "digest_enabled", "digest_time", "digest_time_blackfriday", "my_best_buy_member",
}


def _admin_id(db: Session) -> int | None:
    return db.query(User.id).filter(User.role == "admin").order_by(User.id).limit(1).scalar()


def get_all(db: Session, user_id: int | None = None) -> dict:
    """Defaults, then household settings, then the person's own settings (admin when no user is given)."""
    values = dict(DEFAULTS)
    for row in db.query(SettingKV).all():
        if row.key in DEFAULTS:
            values[row.key] = row.value
    uid = user_id if user_id is not None else _admin_id(db)
    if uid is not None:
        for row in db.query(UserSetting).filter(UserSetting.user_id == uid).all():
            if row.key in USER_KEYS:
                values[row.key] = row.value
    return values


def get(db: Session, key: str, user_id: int | None = None):
    if key in USER_KEYS:
        return get_all(db, user_id).get(key)
    row = db.get(SettingKV, key)
    return row.value if row is not None else DEFAULTS.get(key)


def update(db: Session, changes: dict, user_id: int | None = None) -> dict:
    uid = user_id if user_id is not None else _admin_id(db)
    for key, value in changes.items():
        if key not in DEFAULTS:
            raise KeyError(key)
        if key in USER_KEYS and uid is not None:
            row = db.get(UserSetting, (uid, key))
            if row is None:
                db.add(UserSetting(user_id=uid, key=key, value=value))
            else:
                row.value = value
            continue
        row = db.get(SettingKV, key)
        if row is None:
            db.add(SettingKV(key=key, value=value))
        else:
            row.value = value
    db.commit()
    return get_all(db, uid)


def notify_urls(db: Session, user_id: int | None = None) -> list[str]:
    """The person's own URLs. URLs from .env belong to the admin (server owner)."""
    uid = user_id if user_id is not None else _admin_id(db)
    urls = [u for u in (get(db, "notify_urls", uid) or []) if u]
    if uid is None or uid == _admin_id(db):
        urls += [u.strip() for u in get_settings().notify_urls.split(",") if u.strip()]
    return list(dict.fromkeys(urls))


def mask_url(url: str) -> str:
    """Hide everything after the scheme and host, enough to recognise the target."""
    scheme, sep, rest = url.partition("://")
    if not sep:
        return "***"
    host = rest.split("/", 1)[0].split("@")[-1]
    return f"{scheme}://{host}/***"


def public_view(values: dict) -> dict:
    out = dict(values)
    out["notify_urls"] = [mask_url(u) for u in values.get("notify_urls") or []]
    out["env_notify_urls"] = [
        mask_url(u.strip()) for u in get_settings().notify_urls.split(",") if u.strip()
    ]
    return out
