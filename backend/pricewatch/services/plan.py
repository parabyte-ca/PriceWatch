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
                       for k in LIVE_DAYS],
            "search_budget": search_budget(db, today)}


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


LIVE_HOURS = (7, 23)  # live re-checks run from 07:00 to 23:00 local on sale days
INTERVALS = (1, 2, 3, 4, 6, 8)  # hours between re-checks of one item, tried in order
QUIET = ("Nothing dropped lately. On sale days this note comes once an hour, "
         "only when something dropped.")


def _live_dates_left(today: date) -> list[tuple[str, date]]:
    """This month's live sale days from today on."""
    out = []
    for key in LIVE_DAYS:
        start, end = events.EVENTS_2026[key]
        d = start
        while d <= end:
            if d >= today and (d.year, d.month) == (today.year, today.month):
                out.append((events.EVENT_LABELS.get(key, key), d))
            d = date.fromordinal(d.toordinal() + 1)
    return out


def search_budget(db: Session, today: date | None = None) -> dict | None:
    """Will this month's search limit last through the sale days left, and how often can items be re-checked?

    None when no search provider or no monthly limit is set. Each item re-check is about one search (store lists
    are cached for a week); each deal category is searched every 6 hours on sale days.
    """
    import calendar

    from ..models import DealCategory
    from ..serp import get_provider
    from .discovery import month_usage

    provider = get_provider(None)
    limit = int(settings_store.get(db, "serp_monthly_limit") or 0)
    if provider is None or provider.name == "claude" or not limit:
        return None
    today = today or events.local_now().date()
    used = month_usage(db, provider.name)
    left = max(0, limit - used)
    items = len(db.scalars(select(Item.id).where(Item.active.is_(True))).all())
    cats = len(db.scalars(select(DealCategory.id).where(DealCategory.active.is_(True))).all())
    live = _live_dates_left(today)
    month_days = calendar.monthrange(today.year, today.month)[1]
    normal_days = max(0, month_days - today.day + 1 - len(live))
    reserve = normal_days * min(items * 2, limit / month_days)  # ordinary days keep their even pace
    hours = LIVE_HOURS[1] - LIVE_HOURS[0]

    def cost(interval: int) -> int:
        per_day = min(items * (hours // interval), 30 * hours) + cats * 4
        return per_day * len(live)

    spare = left - reserve
    interval = next((h for h in INTERVALS if cost(h) <= spare), None)
    return {"limit": limit, "used": used, "left": left, "items": items, "categories": cats,
            "live_days": [{"name": n, "date": d.isoformat()} for n, d in live],
            "hourly_cost": cost(1), "reserve": round(reserve), "interval_hours": interval or INTERVALS[-1],
            "fits_hourly": interval == 1, "short_by": max(0, round(cost(1) - spare)),
            "enough": interval is not None}


def live_interval_hours(db: Session) -> int:
    b = search_budget(db)
    return b["interval_hours"] if b else 1


async def practice(db: Session, user: User) -> dict:
    """A rehearsal of a sale day, now: the checklist, a re-check of up to 3 plan items and a note of recent drops."""
    from ..serp import get_provider
    from ..timeutil import utcnow
    from .alerts import money, raise_alert
    from .deals import todays_drops
    from .discovery import DiscoveryError, _under_limit, discover

    stamp = utcnow().strftime("%Y%m%d%H%M%S")
    p = build(db, user)
    if not p["items"]:
        return {"ok": False, "message": "Pick at least one item first."}
    day = live_day() or "Black Friday"
    sent = raise_alert(db, item=None, rule="plan", key=f"plan-practice:{stamp}", user_id=user.id,
                       title=f"Practice: your {day} plan", body=checklist_text(p, day), url="/plan")
    refreshed = 0
    provider = get_provider(None)
    if provider is not None:
        for row in p["items"][:3]:
            item = db.get(Item, row["item_id"])
            if item is None or not _under_limit(db, provider):
                break
            try:
                await discover(db, item, force=True)
                refreshed += 1
            except DiscoveryError:
                break
    drops = todays_drops(db, user, limit=10, min_pct=2.0)
    body = "\n".join(f"- {d['item']}: {money(d['price_cents'])} at {d['store']} (-{d['drop_pct']:g}%)"
                     for d in drops) or QUIET
    raise_alert(db, item=None, rule="live", key=f"live-practice:{stamp}", user_id=user.id,
                title=f"Practice: {len(drops)} recent price drop{'' if len(drops) == 1 else 's'}", body=body, url="/")
    status = sent.status if sent else "not sent"
    return {"ok": status == "sent", "status": status, "refreshed": refreshed, "drops": len(drops),
            "message": ("Two practice notifications sent." if status == "sent" else
                        "Notifications were only logged: set up ntfy or app notifications in Settings." if status == "logged"
                        else "Sending failed: check the notification settings."),
            "budget": search_budget(db)}
