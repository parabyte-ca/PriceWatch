"""Shopping event calendar and Black Friday mode."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Item

# Event windows (local dates, inclusive) used for price-policy exclusions and the WAIT horizon.
EVENTS_2026 = {
    "black_friday": (date(2026, 11, 27), date(2026, 11, 27)),
    "black_friday_week": (date(2026, 11, 19), date(2026, 11, 30)),
    "cyber_monday": (date(2026, 11, 30), date(2026, 11, 30)),
    "cyber_week": (date(2026, 11, 30), date(2026, 12, 6)),
    "boxing_day": (date(2026, 12, 26), date(2026, 12, 26)),
    "boxing_week": (date(2026, 12, 26), date(2026, 12, 31)),
}
EVENT_LABELS = {
    "black_friday": "Black Friday", "black_friday_week": "Black Friday week", "cyber_monday": "Cyber Monday",
    "cyber_week": "Cyber Week", "boxing_day": "Boxing Day", "boxing_week": "Boxing Week", "prime_day": "Prime Day",
}


def tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def local_now(now_utc: datetime | None = None) -> datetime:
    now_utc = now_utc or datetime.now(ZoneInfo("UTC")).replace(tzinfo=None)
    return now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz())


def _parse_local(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=tz())


SALE_MODES = (
    ("Black Friday", "blackfriday_mode", "blackfriday_start", "blackfriday_end"),
    ("Boxing Week", "boxingweek_mode", "boxingweek_start", "boxingweek_end"),
)


def sale_windows(cfg: dict) -> list[tuple[str, datetime, datetime]]:
    """Enabled sale-mode windows as (name, start, end) in local time."""
    out = []
    for name, flag, start, end in SALE_MODES:
        if cfg.get(flag, True) and cfg.get(start) and cfg.get(end):
            out.append((name, _parse_local(cfg[start]), _parse_local(cfg[end])))
    return out


def sale_mode(cfg: dict, now_utc: datetime | None = None) -> str | None:
    """Name of the sale mode running now (Black Friday or Boxing Week), or None."""
    now = local_now(now_utc)
    for name, start, end in sale_windows(cfg):
        if start <= now <= end:
            return name
    return None


def blackfriday_active(cfg: dict, now_utc: datetime | None = None) -> bool:
    """True while any sale mode runs: 30-minute checks for top hot items, second digest, 2-hour alert window."""
    return sale_mode(cfg, now_utc) is not None


def blackfriday_item_ids(db: Session) -> set[int]:
    """Top-priority items polled every 30 minutes in Black Friday mode: hot items by priority, capped."""
    limit = get_settings().blackfriday_max_items
    rows = db.scalars(
        select(Item.id).where(Item.active.is_(True), Item.hot.is_(True)).order_by(Item.priority, Item.id).limit(limit)
    ).all()
    return set(rows)


def active_events(on: date) -> list[str]:
    return [name for name, (start, end) in EVENTS_2026.items() if start <= on <= end]


def season_start(cfg: dict, now_utc: datetime) -> datetime:
    """Seasonal window: since the configured season start or the last 90 days, whichever is longer."""
    configured = datetime.fromisoformat(cfg["season_start"])
    return min(configured, now_utc - timedelta(days=90))


def wait_horizon(on: date) -> str:
    if on <= date(2026, 11, 30):
        return "Cyber Monday (Nov 30)"
    if on <= date(2026, 12, 31):
        return "Boxing Week (Dec 26 to 31)"
    return "the next sale event"
