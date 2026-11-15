"""Build per-item summaries (best landed price, lows, badge) for the API and alerts."""

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Item, Observation, SourceLink
from ..pricing import effective_shipping, landed_price
from ..timeutil import utcnow
from . import settings_store
from .stats import Point, badge, fake_sale, window_low

HISTORY_DAYS = 400


def _source_landed(src: SourceLink, province: str) -> dict | None:
    if src.last_price_cents is None:
        return None
    retailer = src.retailer
    ship = effective_shipping(
        src.last_price_cents,
        src.last_shipping_cents,
        retailer.free_shipping_threshold_cents if retailer else None,
        retailer.default_shipping_cents if retailer else None,
    )
    return landed_price(src.last_price_cents, ship, province)


def summarize_items(db: Session, items: list[Item]) -> dict[int, dict]:
    if not items:
        return {}
    cfg = settings_store.get_all(db)
    province = cfg["province"]
    now = utcnow()
    ids = [i.id for i in items]
    obs_rows = db.execute(
        select(Observation.item_id, Observation.source_link_id, Observation.observed_at,
               Observation.price_cents, Observation.was_price_cents)
        .where(Observation.item_id.in_(ids), Observation.price_cents.is_not(None),
               Observation.observed_at >= now - timedelta(days=HISTORY_DAYS))
        .order_by(Observation.observed_at)
    ).all()
    by_source: dict[int, list[Point]] = defaultdict(list)
    manual_by_item: dict[int, list[Point]] = defaultdict(list)
    for item_id, src_id, at, price, was in obs_rows:
        p = Point(at, price, was)
        if src_id is None:
            manual_by_item[item_id].append(p)
        else:
            by_source[src_id].append(p)

    out: dict[int, dict] = {}
    for item in items:
        confirmed = [s for s in item.sources if s.status == "confirmed"]
        confirmed_ids = {s.id for s in confirmed}
        points = [p for s in confirmed for p in by_source.get(s.id, [])]
        all_points = sorted(points + manual_by_item.get(item.id, []), key=lambda p: p.at)
        best = None
        for src in confirmed:
            landed = _source_landed(src, province)
            if landed is None or src.last_in_stock is False:
                continue
            if best is None or landed["landed_cents"] < best["landed"]["landed_cents"]:
                best = {"source_id": src.id, "url": src.url, "retailer": src.retailer.name if src.retailer else None,
                        "landed": landed, "was_price_cents": src.last_was_price_cents}
        best_points = by_source.get(best["source_id"], []) if best else []
        fs = fake_sale(best_points, now, float(cfg["fake_sale_pct"]))
        low30 = window_low(all_points, now, 30)
        atl = window_low(all_points, now, None)
        best_price = best["landed"]["price_cents"] if best else None
        compare = None
        if best:
            compare = best["landed"]["landed_cents"] if cfg["target_basis"] == "landed" else best_price
        last_checked = max((s.last_checked_at for s in confirmed if s.last_checked_at), default=None)
        out[item.id] = {
            "best": best,
            "best_price_cents": best_price,
            "best_landed_cents": best["landed"]["landed_cents"] if best else None,
            "compare_cents": compare,
            "low_30_cents": low30,
            "low_60_cents": window_low(all_points, now, 60),
            "low_90_cents": window_low(all_points, now, 90),
            "all_time_low_cents": atl,
            "at_all_time_low": best_price is not None and atl is not None and best_price <= atl,
            "median_30_cents": fs["median_30_cents"],
            "real_discount_pct": fs["real_discount_pct"],
            "fake_sale": fs["fake"],
            "fake_sale_reasons": fs["reasons"],
            "badge": badge(best_price, compare, item.target_price_cents, low30, atl, fs["fake"],
                           len(all_points) >= 3, float(cfg["good_within_pct"])),
            "last_checked_at": last_checked,
            "source_count": len(confirmed_ids),
            "suggested_count": sum(1 for s in item.sources if s.status == "suggested"),
        }
    return out
