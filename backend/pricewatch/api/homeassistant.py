"""Home Assistant: compact JSON for REST sensors (use a personal API token as a Bearer header)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..auth import current_user
from ..config import get_settings
from ..db import get_db
from ..models import Item, Purchase, SourceLink, User
from ..services import events, settings_store
from ..services.summary import summarize_items
from ..services.users import list_ids
from ..timeutil import utcnow

router = APIRouter(prefix="/api/ha", tags=["home-assistant"])


def _dollars(cents: int | None) -> float | None:
    return round(cents / 100, 2) if cents is not None else None


def _row(item: Item, s: dict) -> dict:
    base = get_settings().public_url.rstrip("/")
    return {
        "id": item.id, "name": item.name, "badge": s["badge"], "decision": s["decision"],
        "price": _dollars(s["best_landed_cents"]), "price_before_tax": _dollars(s["best_price_cents"]),
        "seasonal_low": _dollars(s["seasonal_low_cents"]), "target": _dollars(item.target_price_cents),
        "retailer": (s["best"] or {}).get("retailer"), "store_url": (s["best"] or {}).get("url"),
        "url": f"{base}/items/{item.id}" if base else f"/items/{item.id}",
        "confidence": s["history_confidence"], "stale": s["stale"], "hot": item.hot,
    }


def _items(db: Session, me: User) -> list[Item]:
    return list(db.scalars(select(Item).options(selectinload(Item.sources).selectinload(SourceLink.retailer))
                           .where(Item.list_id.in_(list_ids(db, me)), Item.active.is_(True))
                           .order_by(Item.priority, Item.name)).all())


@router.get("/summary")
def summary(db: Session = Depends(get_db), me: User = Depends(current_user)):
    """State = number of items to buy now. Attributes carry counts, claimable money and every item."""
    items = _items(db, me)
    sums = summarize_items(db, items, me.id)
    rows = [_row(i, sums[i.id]) for i in items]
    claim = db.scalars(select(Purchase).where(Purchase.user_id == me.id, Purchase.status == "claimable")).all()
    claimable = sum(p.price_cents - p.lowest_seen_cents for p in claim if p.lowest_seen_cents is not None)
    buy = [r for r in rows if r["decision"] == "BUY"]
    protect = [r for r in rows if r["decision"] == "BUY_AND_PROTECT"]
    return {
        "state": len(buy) + len(protect),
        "buy": len(buy), "buy_and_protect": len(protect),
        "wait": sum(1 for r in rows if r["decision"] == "WAIT"),
        "stale": sum(1 for r in rows if r["stale"]),
        "claimable": _dollars(claimable), "claims": len(claim),
        "sale_mode": events.sale_mode(settings_store.get_all(db)),
        "buy_now": [r["name"] for r in buy + protect],
        "items": rows,
        "updated": utcnow().isoformat() + "Z",
    }


@router.get("/items/{item_id}")
def item(item_id: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    found = next((i for i in _items(db, me) if i.id == item_id), None)
    if found is None:
        raise HTTPException(404, "Item not found")
    return _row(found, summarize_items(db, [found], me.id)[found.id])
