"""Per-item summaries: best landed price, seasonal low, confidence, decision, price-match opportunities."""

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Item, Observation, PricePolicy, SourceLink, UserItemPref
from ..pricing import effective_shipping, landed_price
from ..timeutil import utcnow
from . import events, settings_store
from .perks import active_perks, after_perks
from .policies import events_excluded_today, protection
from .stats import Point, decide, fake_sale, history_confidence, low_since, median_since, window_low

HISTORY_DAYS = 400


def _ship(src: SourceLink, price: int, shipping: int | None) -> int | None:
    r = src.retailer
    return effective_shipping(price, shipping, r.free_shipping_threshold_cents if r else None,
                              r.default_shipping_cents if r else None)


def _source_landed(src: SourceLink, province: str, tax_overrides: dict | None = None) -> dict | None:
    if src.last_price_cents is None:
        return None
    return landed_price(src.last_price_cents, _ship(src, src.last_price_cents, src.last_shipping_cents), province,
                        tax_overrides)


def _offer_counts(item: Item, condition: str | None, seller_type: str | None) -> bool:
    from .checker import counts_for_item

    return counts_for_item(item, condition or "new", seller_type or "first_party") is None


def summarize_items(db: Session, items: list[Item], user_id: int | None = None) -> dict[int, dict]:
    """Summaries as seen by one person (their province, target basis and snoozes)."""
    if not items:
        return {}
    if user_id is None:
        user_id = settings_store._admin_id(db)
    cfg = settings_store.get_all(db, user_id)
    snoozes = {p.item_id: p for p in db.scalars(select(UserItemPref).where(
        UserItemPref.user_id == user_id, UserItemPref.item_id.in_([i.id for i in items]))).all()} if user_id else {}
    province = cfg["province"]
    overrides = cfg.get("tax_overrides") or {}
    buy_pct, protect_pct = float(cfg["buy_within_pct"]), float(cfg["protect_within_pct"])
    now = utcnow()
    local = events.local_now(now)
    today = local.date()
    horizon_text = events.wait_horizon(today)
    horizon_day = today if today > events.EVENTS_2026["cyber_monday"][1] else events.EVENTS_2026["cyber_monday"][1]
    season_since = events.season_start(cfg, now)
    policies = {p.domain: p for p in db.scalars(select(PricePolicy)).all()}
    member = bool(cfg.get("my_best_buy_member"))

    ids = [i.id for i in items]
    rows = db.execute(
        select(Observation.item_id, Observation.source_link_id, Observation.observed_at, Observation.price_cents,
               Observation.was_price_cents, Observation.shipping_cents, Observation.condition,
               Observation.seller_type)
        .where(Observation.item_id.in_(ids), Observation.price_cents.is_not(None),
               Observation.observed_at >= now - timedelta(days=HISTORY_DAYS))
        .order_by(Observation.observed_at)
    ).all()
    item_by_id = {i.id: i for i in items}
    src_by_id = {s.id: s for i in items for s in i.sources}
    by_source: dict[int, list[Point]] = defaultdict(list)  # landed, counted offers only
    for item_id, src_id, at, price, was, ship, cond, seller_type in rows:
        src = src_by_id.get(src_id)
        if src is None or src.status != "confirmed" or not _offer_counts(item_by_id[item_id], cond, seller_type):
            continue
        landed = landed_price(price, _ship(src, price, ship), province, overrides)["landed_cents"]
        by_source[src_id].append(Point(at, landed, was))

    from .discovery import market_summary

    market = market_summary(db, ids)
    out: dict[int, dict] = {}
    for item in items:
        confirmed = [s for s in item.sources if s.status == "confirmed"]
        counted = [s for s in confirmed if _offer_counts(item, s.last_condition, s.last_seller_type)]
        all_points = sorted((p for s in counted for p in by_source.get(s.id, [])), key=lambda p: p.at)

        offers = []
        for src in counted:
            landed = _source_landed(src, province, overrides)
            if landed is None or src.last_in_stock is False:
                continue
            offers.append((src, landed))
        offers.sort(key=lambda o: o[1]["landed_cents"])
        best = None
        if offers:
            src, landed = offers[0]
            best = {"source_id": src.id, "url": src.url, "retailer": src.retailer.name if src.retailer else src.title,
                    "domain": src.retailer.domain if src.retailer else None, "landed": landed,
                    "was_price_cents": src.last_was_price_cents, "channel": src.channel}
            perks = active_perks(db, best["domain"])
            if perks:
                best.update(after_perks(landed["landed_cents"], perks))

        best_points = by_source.get(best["source_id"], []) if best else []
        current = best["landed"]["landed_cents"] if best else None
        best_price = best["landed"]["price_cents"] if best else None
        compare = (current if cfg["target_basis"] == "landed" else best_price) if best else None
        seasonal_low = low_since(all_points, season_since)
        confidence, history_days = history_confidence(best_points or all_points)
        median_60 = median_since(all_points, now - timedelta(days=60))
        real_discount = round((median_60 - current) / median_60 * 100, 1) if median_60 and current else None
        is_fake, fake_reasons = fake_sale(current or 0, best["was_price_cents"] if best else None, best_price,
                                          seasonal_low, best_points, buy_pct)
        policy = policies.get(best["domain"]) if best else None
        protected = protection(policy, today, horizon_day, member)
        decision = decide(current, compare, item.target_price_cents, seasonal_low, confidence, buy_pct,
                          protect_pct, protected, is_fake, horizon_text)

        opportunities = []
        for src, landed in offers:
            pol = policies.get(src.retailer.domain) if src.retailer else None
            if not (pol and pol.enabled and pol.competitor_match):
                continue
            cheaper = [(o, ol) for o, ol in offers if o.retailer_id != src.retailer_id
                       and ol["subtotal_cents"] < landed["subtotal_cents"]]
            if not cheaper:
                continue
            o, ol = cheaper[0]
            caveats = []
            excluded_now = events_excluded_today(pol, today)
            if excluded_now:
                caveats.append(f"{src.retailer.name} excludes {', '.join(excluded_now)} prices; "
                               "the lower price may not qualify")
            if pol.excludes_marketplace and (o.last_seller_type or "").startswith("marketplace"):
                continue
            opportunities.append({
                "at": src.retailer.name, "at_source_id": src.id, "match_to": o.retailer.name if o.retailer else o.title,
                "match_url": o.url, "price_cents": ol["price_cents"],
                "saving_cents": landed["subtotal_cents"] - ol["subtotal_cents"], "caveats": caveats,
                "policy_notes": pol.notes,
            })

        last_checked = max((s.last_checked_at for s in confirmed if s.last_checked_at), default=None)
        last_success = max((s.last_success_at for s in confirmed if s.last_success_at), default=None)
        out[item.id] = {
            "best": best,
            "best_price_cents": best_price,
            "best_landed_cents": current,
            "compare_cents": compare,
            "seasonal_low_cents": seasonal_low,
            "distance_to_low_pct": round((current - seasonal_low) / seasonal_low * 100, 1)
            if current and seasonal_low else None,
            "history_confidence": confidence,
            "history_days": history_days,
            "low_30_cents": window_low(all_points, now, 30),
            "low_60_cents": window_low(all_points, now, 60),
            "low_90_cents": window_low(all_points, now, 90),
            "all_time_low_cents": window_low(all_points, now, None),
            "at_all_time_low": current is not None and seasonal_low is not None and current <= seasonal_low,
            "median_60_cents": median_60,
            "real_discount_pct": real_discount,
            "fake_sale": is_fake,
            "fake_sale_reasons": fake_reasons,
            "decision": decision.action,
            "decision_reason": decision.reason,
            "badge": decision.badge,
            "protection": protected if decision.action == "BUY_AND_PROTECT" else None,
            "price_match": opportunities,
            "last_checked_at": last_checked,
            "stale": last_success is None or last_success < now - timedelta(hours=24),
            "snoozed": bool(item.id in snoozes and (snoozes[item.id].muted or (
                snoozes[item.id].snoozed_until and snoozes[item.id].snoozed_until > now))),
            "source_count": len(confirmed),
            "suggested_count": sum(1 for s in item.sources if s.status == "suggested"),
            "market": market.get(item.id),
        }
    return out
