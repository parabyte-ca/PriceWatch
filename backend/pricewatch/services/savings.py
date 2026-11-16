"""Spend and savings per person and per list, from purchases."""

from collections import defaultdict
from datetime import timedelta
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Item, Observation, Purchase, User, WishList
from ..timeutil import utcnow


def reference_price(db: Session, item_id: int) -> tuple[int | None, str | None]:
    """Median first-party new price (before tax) over the last 60 days: what 'normal' looked like when you bought."""
    since = utcnow() - timedelta(days=60)
    prices = db.scalars(select(Observation.price_cents).where(
        Observation.item_id == item_id, Observation.price_cents.is_not(None), Observation.observed_at >= since,
        Observation.condition == "new", Observation.seller_type == "first_party")).all()
    if len(prices) < 3:
        return None, None
    return int(median(prices)), "60-day median"


def summary(db: Session, user_ids: list[int], list_ids: list[int]) -> dict:
    rows = db.execute(select(Purchase, Item).join(Item, Item.id == Purchase.item_id)
                      .where(Purchase.user_id.in_(user_ids) | Item.list_id.in_(list_ids))).all()
    names = {u.id: u.display_name for u in db.scalars(select(User)).all()}
    lists = {lst.id: lst for lst in db.scalars(select(WishList).where(WishList.id.in_(list_ids))).all()}

    def blank():
        return {"purchases": 0, "spent_cents": 0, "saved_vs_median_cents": 0, "claimed_cents": 0, "claimable_cents": 0}

    total, by_person, by_list = blank(), defaultdict(blank), defaultdict(blank)
    recent = []
    for p, item in rows:
        if p.user_id not in user_ids and item.list_id not in list_ids:
            continue
        spent = p.price_cents + (p.shipping_cents or 0)
        saved = max(0, (p.reference_cents or p.price_cents) - p.price_cents)
        claimable = (p.price_cents - p.lowest_seen_cents) if p.status == "claimable" and p.lowest_seen_cents else 0
        for bucket in (total, by_person[p.user_id], by_list[item.list_id]):
            bucket["purchases"] += 1
            bucket["spent_cents"] += spent
            bucket["saved_vs_median_cents"] += saved
            bucket["claimed_cents"] += p.claimed_cents or 0
            bucket["claimable_cents"] += claimable
        recent.append({"item": item.name, "retailer": p.retailer_name, "date": p.purchased_on.isoformat(),
                       "price_cents": p.price_cents, "reference_cents": p.reference_cents, "saved_cents": saved,
                       "claimed_cents": p.claimed_cents, "person": names.get(p.user_id)})
    recent.sort(key=lambda r: r["date"], reverse=True)
    return {
        "total": total,
        "by_person": [{"user_id": uid, "name": names.get(uid), **v} for uid, v in by_person.items()],
        "by_list": [{"list_id": lid, "name": lists[lid].name if lid in lists else "Other",
                     "budget_cents": lists[lid].budget_cents if lid in lists else None, **v}
                    for lid, v in by_list.items()],
        "recent": recent[:30],
    }


def list_spent(db: Session, list_id: int) -> int:
    rows = db.execute(select(Purchase.price_cents, Purchase.shipping_cents).join(Item, Item.id == Purchase.item_id)
                      .where(Item.list_id == list_id)).all()
    return sum(p + (s or 0) for p, s in rows)
