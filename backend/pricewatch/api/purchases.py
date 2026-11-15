"""Purchases: record what you bought, see the protection window, claim drops, download proof."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import Item, ProofCapture, Purchase, SourceLink, User
from ..services import events, protection, settings_store
from .items import _load_item

router = APIRouter(prefix="/api", tags=["purchases"])


class PurchaseIn(BaseModel):
    source_id: int | None = None
    retailer_name: str | None = Field(default=None, max_length=200)
    price_cents: int = Field(ge=0)
    shipping_cents: int | None = Field(default=None, ge=0)
    purchased_on: date | None = None
    channel: str = Field(default="online", pattern=r"^(online|warehouse|store:[\w-]{1,30}|province:[A-Z]{2})$")
    badged: bool = False
    order_ref: str | None = Field(default=None, max_length=100)
    notes: str | None = None
    protection_days: int | None = Field(default=None, ge=0, le=365)
    stop_tracking: bool = True


class PurchaseUpdate(BaseModel):
    status: str | None = Field(default=None, pattern=r"^(watching|claimable|claimed|expired|closed)$")
    claimed_cents: int | None = Field(default=None, ge=0)
    protection_days: int | None = Field(default=None, ge=0, le=365)
    notes: str | None = None


def _out(db: Session, p: Purchase) -> dict:
    today = events.local_now().date()
    item = db.get(Item, p.item_id)
    proofs = db.scalars(select(ProofCapture).where(ProofCapture.purchase_id == p.id)).all()
    return {
        "id": p.id, "item_id": p.item_id, "item_name": item.name if item else None, "user_id": p.user_id,
        "retailer_name": p.retailer_name, "retailer_domain": p.retailer_domain, "channel": p.channel,
        "price_cents": p.price_cents, "shipping_cents": p.shipping_cents, "purchased_on": p.purchased_on.isoformat(),
        "protection_days": p.protection_days, "protection_basis": p.protection_basis,
        "protection_until": p.protection_until.isoformat() if p.protection_until else None,
        "days_left": (p.protection_until - today).days if p.protection_until else None,
        "badged": p.badged, "order_ref": p.order_ref, "notes": p.notes, "status": p.status,
        "lowest_seen_cents": p.lowest_seen_cents,
        "claimable_cents": (p.price_cents - p.lowest_seen_cents) if p.lowest_seen_cents is not None else None,
        "claimed_cents": p.claimed_cents, "proof_count": len(proofs),
    }


def _mine(db: Session, me: User, purchase_id: int) -> Purchase:
    p = db.get(Purchase, purchase_id)
    if p is None or p.user_id != me.id:
        raise HTTPException(404, "Purchase not found")
    return p


@router.get("/purchases")
def list_purchases(item_id: int | None = None, db: Session = Depends(get_db), me: User = Depends(current_user)):
    q = select(Purchase).where(Purchase.user_id == me.id)
    if item_id is not None:
        q = q.where(Purchase.item_id == item_id)
    return [_out(db, p) for p in db.scalars(q.order_by(Purchase.purchased_on.desc(), Purchase.id.desc())).all()]


@router.get("/items/{item_id}/protection-terms")
def preview_terms(item_id: int, source_id: int | None = None, purchased_on: date | None = None, badged: bool = False,
                  db: Session = Depends(get_db), me: User = Depends(current_user)):
    _load_item(db, item_id, me)
    src = db.get(SourceLink, source_id) if source_id else None
    domain = src.retailer.domain if src and src.retailer else None
    member = bool(settings_store.get(db, "my_best_buy_member", me.id))
    days, until, basis = protection.terms(db, domain, purchased_on or events.local_now().date(), member, badged)
    return {"days": days, "until": until.isoformat() if until else None, "basis": basis}


@router.post("/items/{item_id}/purchases", status_code=201)
def record_purchase(item_id: int, body: PurchaseIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    item = _load_item(db, item_id, me)
    src = None
    if body.source_id is not None:
        src = db.get(SourceLink, body.source_id)
        if src is None or src.item_id != item.id:
            raise HTTPException(404, "Source not found on this item")
    domain = src.retailer.domain if src and src.retailer else None
    name = body.retailer_name or (src.retailer.name if src and src.retailer else (src.title if src else None))
    if not name:
        raise HTTPException(422, "Choose the store you bought from")
    bought = body.purchased_on or events.local_now().date()
    member = bool(settings_store.get(db, "my_best_buy_member", me.id))
    days, until, basis = protection.terms(db, domain, bought, member, body.badged)
    if body.protection_days is not None:
        days = body.protection_days
        until = bought + timedelta(days=days) if days else None
        basis = f"{days}-day protection (entered by you)" if days else None
    p = Purchase(item_id=item.id, user_id=me.id, source_link_id=src.id if src else None, retailer_domain=domain,
                 retailer_name=name, channel=body.channel if not src else (src.channel or body.channel),
                 price_cents=body.price_cents, shipping_cents=body.shipping_cents, purchased_on=bought,
                 protection_days=days, protection_until=until, protection_basis=basis, badged=body.badged,
                 order_ref=body.order_ref, notes=body.notes,
                 status="watching" if until and until >= events.local_now().date() else "closed")
    db.add(p)
    if body.stop_tracking:
        item.active = False  # no more deal alerts; sources keep being checked while protection is open
    db.commit()
    return _out(db, p)


@router.patch("/purchases/{purchase_id}")
def update_purchase(purchase_id: int, body: PurchaseUpdate, db: Session = Depends(get_db),
                    me: User = Depends(current_user)):
    p = _mine(db, me, purchase_id)
    changes = body.model_dump(exclude_unset=True)
    if "protection_days" in changes:
        p.protection_days = changes.pop("protection_days")
        p.protection_until = p.purchased_on + timedelta(days=p.protection_days) if p.protection_days else None
        p.protection_basis = f"{p.protection_days}-day protection (entered by you)" if p.protection_days else None
    for k, v in changes.items():
        setattr(p, k, v)
    db.commit()
    return _out(db, p)


@router.delete("/purchases/{purchase_id}", status_code=204)
def delete_purchase(purchase_id: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    db.delete(_mine(db, me, purchase_id))
    db.commit()


@router.get("/purchases/{purchase_id}/proof")
def download_proof(purchase_id: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    p = _mine(db, me, purchase_id)
    data = protection.proof_zip(db, p)
    name = f"pricewatch-proof-{p.id}-{p.retailer_name.replace(' ', '-').lower()}.zip"
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/items/{item_id}/deals")
def item_deals(item_id: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    """Community threads matched to this item (RedFlagDeals), newest first."""
    from ..models import DealFeedEntry

    _load_item(db, item_id, me)
    rows = db.scalars(select(DealFeedEntry).where(DealFeedEntry.matched_item_id == item_id)
                      .order_by(DealFeedEntry.created_at.desc()).limit(20)).all()
    return [{"title": r.title, "url": r.url, "price_cents": r.price_cents, "retailer_domain": r.retailer_domain,
             "tracked_source_id": r.matched_source_id, "score": r.match_score,
             "published_at": r.published_at.isoformat() + "Z" if r.published_at else None} for r in rows]
