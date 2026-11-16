"""Basket optimiser and sale mode."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import Item, User
from ..services import basket, events, settings_store
from ..services.users import list_ids

router = APIRouter(prefix="/api", tags=["planning"])


class BasketIn(BaseModel):
    item_ids: list[int] | None = Field(default=None, max_length=60)
    list_id: int | None = None
    use_perks: bool = True


@router.post("/basket")
def plan_basket(body: BasketIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    """Cheapest way to buy these items across stores, counting free-shipping thresholds, tax and perks."""
    mine = list_ids(db, me)
    if body.list_id is not None and body.list_id not in mine:
        raise HTTPException(404, "List not found")
    q = select(Item).where(Item.list_id.in_([body.list_id] if body.list_id else mine))
    if body.item_ids:
        q = q.where(Item.id.in_(body.item_ids))
    else:
        q = q.where(Item.active.is_(True))
    items = db.scalars(q.order_by(Item.priority, Item.id)).all()
    if len(items) > 60:
        raise HTTPException(422, "Pick 60 items or fewer")
    return basket.optimise(db, items, me.id, body.use_perks)


@router.get("/sale-mode")
def sale_mode(db: Session = Depends(get_db), _: User = Depends(current_user)):
    cfg = settings_store.get_all(db)
    return {"active": events.sale_mode(cfg),
            "windows": [{"name": n, "start": a.isoformat(), "end": b.isoformat()} for n, a, b in events.sale_windows(cfg)]}


