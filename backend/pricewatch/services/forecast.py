"""Will it get cheaper? A plain, explainable estimate from this item's own price history and the sale calendar.

Not a prediction model: it counts how often and how far the price has dropped, looks at the recent trend and how far
the price sits above its usual level, and checks whether a sale event is still ahead. The answer is a chance
(low, medium, high), a likely low if it does drop, and the reasons, so a person can judge it.
"""

from datetime import date, timedelta
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Item, Observation
from ..timeutil import utcnow
from . import events

MIN_DAYS = 10


def daily_lows(db: Session, item: Item, days: int = 120) -> list[tuple[date, int]]:
    """Lowest first-party new price (before tax) per day across the item's confirmed stores."""
    since = utcnow() - timedelta(days=days)
    ids = [s.id for s in item.sources if s.status == "confirmed"] or [-1]
    rows = db.execute(select(func.date(Observation.observed_at), func.min(Observation.price_cents)).where(
        Observation.source_link_id.in_(ids), Observation.price_cents.is_not(None), Observation.observed_at >= since,
        Observation.condition == "new", Observation.seller_type == "first_party")
        .group_by(func.date(Observation.observed_at)).order_by(func.date(Observation.observed_at))).all()
    return [(d if isinstance(d, date) else date.fromisoformat(str(d)), int(p)) for d, p in rows]


def next_event(today: date) -> tuple[str, date] | None:
    upcoming = [(events.EVENT_LABELS.get(k, k), start) for k, (start, _end) in events.EVENTS_2026.items()
                if start > today and k in ("black_friday", "cyber_monday", "boxing_day")]
    return min(upcoming, key=lambda e: e[1]) if upcoming else None


def estimate(series: list[tuple[date, int]], today: date) -> dict:
    if len(series) < MIN_DAYS:
        return {"chance": None, "reasons": [f"Needs at least {MIN_DAYS} days of prices (has {len(series)})."],
                "likely_low_cents": None, "next_event": None}
    prices = [p for _, p in series]
    current, low = prices[-1], min(prices)
    usual = int(median(prices[-60:]))
    drops = [(a - b) / a for a, b in zip(prices, prices[1:], strict=False) if b < a * 0.97]
    typical_drop = median(drops) if drops else 0.0
    recent = prices[-14:]
    trend = (recent[-1] - recent[0]) / recent[0] if recent[0] else 0.0
    ev = next_event(today)
    score, reasons = 0, []
    if ev:
        days = (ev[1] - today).days
        score += 2 if days <= 14 else 1
        reasons.append(f"{ev[0]} is {days} day{'s' if days != 1 else ''} away.")
    if current > usual * 1.05:
        score += 2
        reasons.append(f"Now {round((current / usual - 1) * 100)}% above its usual ${usual / 100:,.2f}.")
    elif current <= low:
        score -= 2
        reasons.append("Already at the lowest price seen.")
    if len(drops) >= 3:
        score += 1
        reasons.append(f"Dropped {len(drops)} times in {len(series)} days, typically {round(typical_drop * 100)}%.")
    elif not drops:
        score -= 1
        reasons.append("The price has not dropped in this history.")
    if trend < -0.02:
        score += 1
        reasons.append("Trending down over two weeks.")
    elif trend > 0.02:
        reasons.append("Trending up over two weeks.")
    chance = "high" if score >= 4 else "medium" if score >= 2 else "low"
    likely = min(low, round(current * (1 - typical_drop))) if drops and chance != "low" else None
    return {"chance": chance, "likely_low_cents": likely, "usual_cents": usual, "current_cents": current,
            "next_event": {"name": ev[0], "date": ev[1].isoformat()} if ev else None, "reasons": reasons,
            "days": len(series)}


def for_item(db: Session, item: Item, today: date | None = None) -> dict:
    today = today or events.local_now().date()
    out = estimate(daily_lows(db, item), today)
    out["note"] = "An estimate from this item's own history and the sale calendar, not a promise."
    return out


