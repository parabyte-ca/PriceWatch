"""Deal intelligence primitives: lows, medians, history confidence, fake-sale flag, buy decision."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median


@dataclass
class Point:
    at: datetime
    price_cents: int  # landed (or plain price, depending on the caller)
    was_price_cents: int | None = None


def window_low(points: list[Point], now: datetime, days: int | None) -> int | None:
    pts = points if days is None else [p for p in points if p.at >= now - timedelta(days=days)]
    return min((p.price_cents for p in pts), default=None)


def low_since(points: list[Point], since: datetime) -> int | None:
    return min((p.price_cents for p in points if p.at >= since), default=None)


def median_since(points: list[Point], since: datetime) -> int | None:
    vals = [p.price_cents for p in points if p.at >= since]
    return int(median(vals)) if vals else None


def history_confidence(points: list[Point]) -> tuple[str, int]:
    """LOW under 14 days of observations, MEDIUM 14 to 59, HIGH 60+. Returns (level, days)."""
    if not points:
        return "LOW", 0
    days = (max(p.at for p in points) - min(p.at for p in points)).days
    if days >= 60:
        return "HIGH", days
    if days >= 14:
        return "MEDIUM", days
    return "LOW", days


def sale_start(points: list[Point]) -> datetime | None:
    """Time the current price level began (points sorted ascending)."""
    if not points:
        return None
    current = points[-1].price_cents
    start = points[-1].at
    for p in reversed(points):
        if p.price_cents != current:
            break
        start = p.at
    return start


def raised_before(points: list[Point], days: int = 14) -> bool:
    """True when the price went up during the `days` before the current price run began."""
    start = sale_start(points)
    if start is None:
        return False
    prior = [p for p in points if start - timedelta(days=days) <= p.at < start]
    return any(b.price_cents > a.price_cents for a, b in zip(prior, prior[1:], strict=False))


def fake_sale(current: int, was_price: int | None, price_before_tax: int | None, seasonal_low: int | None,
              offer_points: list[Point], buy_pct: float) -> tuple[bool, list[str]]:
    """A stated sale (was-price above the price) that is not near the observed seasonal low."""
    if not (was_price and price_before_tax and was_price > price_before_tax):
        return False, []
    reasons = []
    if seasonal_low and current > seasonal_low * (1 + buy_pct / 100):
        reasons.append(f"more than {buy_pct:g}% above the lowest price seen this season")
    if raised_before(offer_points):
        reasons.append("price was raised in the 14 days before this sale")
    return bool(reasons), reasons


@dataclass
class Decision:
    action: str  # BUY | BUY_AND_PROTECT | WAIT | NO_DATA
    badge: str
    reason: str


def decide(current: int | None, compare: int | None, target: int | None, seasonal_low: int | None,
           confidence: str, buy_pct: float, protect_pct: float, protection: str | None, is_fake: bool,
           horizon: str) -> Decision:
    if current is None:
        return Decision("NO_DATA", "NO DATA", "No price yet")
    if target is not None and compare is not None and compare <= target:
        return Decision("BUY", "BUY NOW", "At or below your target")
    if seasonal_low and confidence != "LOW":
        if current <= seasonal_low * (1 + buy_pct / 100):
            return Decision("BUY", "BUY NOW", f"Within {buy_pct:g}% of the seasonal low")
        if protection and current <= seasonal_low * (1 + protect_pct / 100):
            return Decision("BUY_AND_PROTECT", "BUY + PROTECT",
                            f"Within {protect_pct:g}% of the seasonal low and covered by {protection}")
    if is_fake:
        return Decision("WAIT", "FAKE SALE", f"Advertised sale is not a real low; wait for {horizon}")
    if confidence == "LOW":
        return Decision("WAIT", "WAIT", "Building price history (under 14 days); buy only at your target")
    return Decision("WAIT", "WAIT", f"Above the seasonal low; wait for {horizon}")
