"""Weekly report: what moved this week, what to buy, what you saved. Sunday evening, per person.

The report is built from PriceWatch's own data. When the Claude match check is set up (ANTHROPIC_API_KEY and the
household setting), Claude Haiku adds a short plain-language summary on top; only item names, prices and verdicts
are sent. Without it the report is the same, minus that paragraph.
"""

import logging
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Alert, Item, Observation, Purchase, User
from ..timeutil import utcnow
from . import claude, events, llm_match, settings_store

log = logging.getLogger(__name__)
SEND_AT = time(18, 0)


def _money(cents: int | None) -> str:
    return "n/a" if cents is None else f"${cents / 100:,.2f}"


def facts(db: Session, user: User) -> dict:
    from .summary import summarize_items
    from .users import list_ids

    items = list(db.scalars(select(Item).where(Item.list_id.in_(list_ids(db, user)), Item.active.is_(True))).all())
    sums = summarize_items(db, items, user.id)
    week_ago = utcnow() - timedelta(days=7)
    moves = []
    for item in items:
        ids = [s.id for s in item.sources if s.status == "confirmed"] or [-1]
        then = db.scalar(select(Observation.price_cents).where(
            Observation.source_link_id.in_(ids), Observation.observed_at <= week_ago,
            Observation.condition == "new", Observation.seller_type == "first_party",
            Observation.price_cents.is_not(None)).order_by(Observation.observed_at.desc()).limit(1))
        now = sums[item.id]["best_price_cents"]
        if then and now and abs(now - then) >= max(100, then * 0.02):
            moves.append({"name": item.name, "from": then, "to": now})
    moves.sort(key=lambda m: m["to"] - m["from"])
    buy = [{"name": i.name, "price": sums[i.id]["best_landed_cents"], "retailer": (sums[i.id]["best"] or {}).get("retailer"),
            "badge": sums[i.id]["badge"]} for i in items if sums[i.id]["decision"] in ("BUY", "BUY_AND_PROTECT")]
    bought = db.scalars(select(Purchase).where(Purchase.user_id == user.id, Purchase.created_at >= week_ago)).all()
    claimable = db.scalars(select(Purchase).where(Purchase.user_id == user.id, Purchase.status == "claimable")).all()
    return {
        "items": len(items), "moves": moves[:10], "buy": buy[:10],
        "bought": [{"name": db.get(Item, p.item_id).name if db.get(Item, p.item_id) else "item",
                    "price": p.price_cents, "saved": max(0, (p.reference_cents or p.price_cents) - p.price_cents)}
                   for p in bought],
        "claimable": sum(p.price_cents - p.lowest_seen_cents for p in claimable if p.lowest_seen_cents is not None),
        "stale": sum(1 for i in items if sums[i.id]["stale"]),
        "next_event": events.wait_horizon(events.local_now().date()),
    }


def render(f: dict) -> str:
    lines = []
    if f["buy"]:
        lines.append("Buy now:")
        lines += [f"- {b['name']}: {_money(b['price'])} at {b['retailer']} ({b['badge']})" for b in f["buy"]]
    if f["moves"]:
        lines.append("Moved this week:")
        lines += [f"- {m['name']}: {_money(m['from'])} to {_money(m['to'])}" for m in f["moves"]]
    if f["bought"]:
        saved = sum(b["saved"] for b in f["bought"])
        lines.append(f"Bought this week: {len(f['bought'])}" + (f", {_money(saved)} under the usual price" if saved else ""))
    if f["claimable"]:
        lines.append(f"Still to claim: {_money(f['claimable'])} (see Bought).")
    if f["stale"]:
        lines.append(f"{f['stale']} item(s) have no good price check in 24 hours.")
    if not lines:
        lines.append(f"Quiet week: no big moves across {f['items']} items.")
    lines.append(f"Next: {f['next_event']}.")
    return "\n".join(lines)


def claude_summary(db: Session, text: str) -> str | None:
    """Two or three plain sentences from Claude Haiku, or None when not set up or on any error."""
    if not llm_match.enabled(db):
        return None
    import anthropic

    try:
        client = anthropic.Anthropic(api_key=claude.api_key(), timeout=30.0, max_retries=2)
        response = client.messages.create(
            model=get_settings().llm_match_model, max_tokens=2000, output_config={"effort": "low"},
            system=("You write a short weekly note for a household's price tracker. In two or three plain sentences, "
                    "say what matters most this week: what to buy now, notable drops, money to claim. Use only the "
                    "facts given; do not invent prices or advice. Canadian English, no headings, no lists."),
            messages=[{"role": "user", "content": text}],
        )
    except (anthropic.APIStatusError, anthropic.APIConnectionError):
        log.warning("weekly summary unavailable")
        return None
    if response.stop_reason == "refusal":
        return None
    out = "".join(b.text for b in response.content if b.type == "text").strip()
    return out or None


def build(db: Session, user: User) -> tuple[str, str]:
    body = render(facts(db, user))
    if user.role == "admin":
        from .health import summary_line

        body += "\n" + summary_line(db)
    note = claude_summary(db, body)
    return "PriceWatch weekly report", (f"{note}\n\n{body}" if note else body)


def maybe_send(db: Session, now_utc: datetime | None = None) -> list[Alert]:
    """Sunday from 18:00 local, once per person per week, if they have it on."""
    from .alerts import raise_alert

    local = events.local_now(now_utc)
    if local.weekday() != 6 or not (SEND_AT <= local.time() <= time(21, 0)):
        return []
    sent = []
    for user in db.scalars(select(User).where(User.active.is_(True))).all():
        cfg = settings_store.get_all(db, user.id)
        if not cfg.get("weekly_report_enabled", True):
            continue
        key = f"weekly:{local.date().isoformat()}"
        if db.scalar(select(Alert.id).where(Alert.dedup_key == f"u{user.id}:{key}")):
            continue
        title, body = build(db, user)
        alert = raise_alert(db, item=None, rule="weekly", key=key, title=title, body=body, cfg=cfg, user_id=user.id)
        if alert:
            sent.append(alert)
    return sent
