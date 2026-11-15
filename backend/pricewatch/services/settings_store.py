"""Settings stored in the database, with defaults. Secrets are masked when read for the UI."""

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import SettingKV

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
    "api_token": "",
}

SECRET_KEYS = {"notify_urls", "api_token"}


def get_all(db: Session) -> dict:
    values = dict(DEFAULTS)
    for row in db.query(SettingKV).all():
        values[row.key] = row.value
    return values


def get(db: Session, key: str):
    row = db.get(SettingKV, key)
    return row.value if row is not None else DEFAULTS.get(key)


def update(db: Session, changes: dict) -> dict:
    for key, value in changes.items():
        if key not in DEFAULTS:
            raise KeyError(key)
        row = db.get(SettingKV, key)
        if row is None:
            db.add(SettingKV(key=key, value=value))
        else:
            row.value = value
    db.commit()
    return get_all(db)


def notify_urls(db: Session) -> list[str]:
    urls = [u for u in (get(db, "notify_urls") or []) if u]
    env = [u.strip() for u in get_settings().notify_urls.split(",") if u.strip()]
    return list(dict.fromkeys(urls + env))


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
    token = values.get("api_token") or ""
    out["api_token"] = f"{token[:4]}...{token[-4:]}" if token else ""
    out["env_notify_urls"] = [
        mask_url(u.strip()) for u in get_settings().notify_urls.split(",") if u.strip()
    ]
    return out
