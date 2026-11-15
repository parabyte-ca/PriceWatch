"""Deal intelligence: lows, median, real discount, fake-sale flag, status badge."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median


@dataclass
class Point:
    at: datetime
    price_cents: int
    was_price_cents: int | None = None


def window_low(points: list[Point], now: datetime, days: int | None) -> int | None:
    pts = points if days is None else [p for p in points if p.at >= now - timedelta(days=days)]
    return min((p.price_cents for p in pts), default=None)


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


def baseline_median(points: list[Point], now: datetime, days: int = 30) -> tuple[int | None, int]:
    """Median of prices in the window, excluding the current price run. Returns (median, sample count)."""
    start = sale_start(points)
    window = [p.price_cents for p in points if p.at >= now - timedelta(days=days) and (start is None or p.at < start)]
    if not window:
        return None, 0
    return int(median(window)), len(window)


def raised_before(points: list[Point], days: int = 14) -> bool:
    """True when the price went up during the `days` before the current price run began."""
    start = sale_start(points)
    if start is None:
        return False
    prior = [p for p in points if start - timedelta(days=days) <= p.at < start]
    return any(b.price_cents > a.price_cents for a, b in zip(prior, prior[1:], strict=False))


def fake_sale(points: list[Point], now: datetime, pct: float, min_samples: int = 3) -> dict:
    """Assess the current price on one source. A 'sale' is a stated was-price above the price."""
    result = {"claims_sale": False, "fake": False, "reasons": [], "median_30_cents": None,
              "real_discount_pct": None, "enough_history": False}
    if not points:
        return result
    latest = points[-1]
    med, n = baseline_median(points, now)
    result["median_30_cents"] = med
    result["enough_history"] = n >= min_samples
    if med:
        result["real_discount_pct"] = round((med - latest.price_cents) / med * 100, 1)
    result["claims_sale"] = bool(latest.was_price_cents and latest.was_price_cents > latest.price_cents)
    if not result["claims_sale"]:
        return result
    if result["enough_history"] and med and latest.price_cents > med * (1 - pct / 100):
        result["fake"] = True
        result["reasons"].append(f"not {pct:g}% below the observed 30-day median")
    if raised_before(points):
        result["fake"] = True
        result["reasons"].append("price was raised in the 14 days before this sale")
    return result


def badge(
    best_cents: int | None,
    compare_cents: int | None,
    target_cents: int | None,
    low_30: int | None,
    all_time_low: int | None,
    is_fake: bool,
    enough_history: bool,
    good_within_pct: float,
) -> str:
    """compare_cents is the value compared to the target (price or landed, per setting)."""
    if best_cents is None:
        return "NO DATA"
    if target_cents is not None and compare_cents is not None and compare_cents <= target_cents:
        return "BUY NOW"
    if is_fake:
        return "FAKE SALE"
    if enough_history:
        ref = min(x for x in (low_30, all_time_low) if x is not None) if (low_30 or all_time_low) else None
        if ref is not None and best_cents <= ref * (1 + good_within_pct / 100):
            return "GOOD"
    return "WAIT"
