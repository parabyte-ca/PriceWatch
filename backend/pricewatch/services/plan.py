"""Black Friday plan: the items you mean to buy, a budget, and for each item when and where to buy it.

Advice per item comes from what PriceWatch already knows: the buy verdict (at target or near the season's low), the
item's own "will it get cheaper?" estimate and the sale calendar. On Black Friday and Cyber Monday mornings the plan is
sent as a checklist with the best store for each item.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Item, User
from . import events, forecast, settings_store, users

LIVE_DAYS = ("black_friday", "cyber_monday", "boxing_day")


def get(db: Session, user: User) -> dict:
    raw = settings_store.get(db, "bf_plan", user.id) or {}
    return {"budget_cents": raw.get("budget_cents"), "item_ids": [int(i) for i in raw.get("item_ids") or []]}


def save(db: Session, user: User, budget_cents: int | None, item_ids: list[int]) -> dict:
    allowed = set(users.list_ids(db, user))
    ok = [i.id for i in db.scalars(select(Item).where(Item.id.in_(item_ids or [-1]))).all() if i.list_id in allowed]
    settings_store.update(db, {"bf_plan": {"budget_cents": budget_cents, "item_ids": ok}}, user.id)
    return get(db, user)


def live_day(today: date | None = None) -> str | None:
    """Black Friday, Cyber Monday or Boxing Day today (local), else None."""
    today = today or events.local_now().date()
    for key in LIVE_DAYS:
        start, end = events.EVENTS_2026[key]
        if start <= today <= end:
            return events.EVENT_LABELS.get(key, key)
    return None


def _advice(summary: dict, fc: dict) -> tuple[str, str]:
    """(when, sentence): "now", an event name, or "anytime"."""
    best = summary.get("best") or {}
    store = best.get("retailer") or "the cheapest store"
    if summary.get("best_price_cents") is None:
        return "unknown", "No price yet: PriceWatch is still looking for it."
    if summary.get("decision") in ("BUY", "BUY_AND_PROTECT"):
        extra = " with price protection" if summary["decision"] == "BUY_AND_PROTECT" else ""
        return "now", f"Buy now at {store}{extra}: {summary.get('decision_reason', 'a good price')}."
    ev = fc.get("next_event")
    if ev and fc.get("chance") in ("high", "medium"):
        likely = fc.get("likely_low_cents")
        guess = f", maybe around ${likely / 100:,.2f}" if likely else ""
        return ev["name"], f"Wait for {ev['name']} ({ev['date']}){guess}; {fc['chance']} chance of a lower price."
    return "anytime", f"Unlikely to drop much: buy at {store} when it suits you."


def build(db: Session, user: User, today: date | None = None) -> dict:
    from .summary import summarize_items

    p = get(db, user)
    items = [i for i in db.scalars(select(Item).where(Item.id.in_(p["item_ids"] or [-1]))).all()]
    order = {iid: n for n, iid in enumerate(p["item_ids"])}
    items.sort(key=lambda i: order.get(i.id, 0))
    sums = summarize_items(db, items, user.id)
    rows, now_total, expected_total = [], 0, 0
    for i in items:
        s = sums[i.id]
        fc = forecast.for_item(db, i, today)
        when, text = _advice(s, fc)
        landed = s.get("best_landed_cents")
        price = s.get("best_price_cents")
        expected = fc.get("likely_low_cents") if when not in ("now", "unknown") and fc.get("likely_low_cents") else price
        if landed:
            now_total += landed
            ratio = (landed / price) if price else 1  # keep tax and shipping on the expected price
            expected_total += round((expected or price) * ratio)
        best = s.get("best") or {}
        rows.append({"item_id": i.id, "name": i.name, "image_url": i.image_url, "when": when, "advice": text,
                     "store": best.get("retailer"), "url": best.get("url"), "price_cents": price,
                     "landed_cents": landed, "expected_cents": expected, "target_cents": i.target_price_cents,
                     "decision": s.get("decision")})
    budget = p["budget_cents"]
    return {"budget_cents": budget, "items": rows, "total_now_cents": now_total,
            "total_expected_cents": expected_total,
            "left_cents": (budget - now_total) if budget is not None else None,
            "events": [{"name": events.EVENT_LABELS.get(k, k), "date": events.EVENTS_2026[k][0].isoformat()}
                       for k in LIVE_DAYS]}


def checklist_text(plan: dict, day: str) -> str:
    lines = [f"{day} checklist:"]
    for r in plan["items"]:
        price = f" ${r['price_cents'] / 100:,.2f}" if r["price_cents"] else ""
        mark = "BUY" if r["when"] in ("now", day) else "wait" if r["when"] not in ("anytime", "unknown") else "ok"
        lines.append(f"- [{mark}] {r['name']}{(' at ' + r['store']) if r['store'] else ''}{price}")
    if plan["budget_cents"] is not None:
        lines.append(f"Total now ${plan['total_now_cents'] / 100:,.2f} with tax, budget "
                     f"${plan['budget_cents'] / 100:,.2f} (left ${plan['left_cents'] / 100:,.2f}).")
    return "\n".join(lines)


def send_checklists(db: Session, now_utc=None) -> int:
    """Scheduled: on a live sale day after 07:00 local, send each person their plan once."""
    from .alerts import raise_alert

    local = events.local_now(now_utc)
    day = live_day(local.date())
    if not day or local.hour < 7:
        return 0
    sent = 0
    for user in db.scalars(select(User).where(User.active.is_(True))).all():
        p = build(db, user, local.date())
        if not p["items"]:
            continue
        a = raise_alert(db, item=None, rule="plan", key=f"plan:{local.date().isoformat()}", user_id=user.id,
                        title=f"Your {day} plan", body=checklist_text(p, day), url="/plan")
        sent += bool(a)
    return sent
