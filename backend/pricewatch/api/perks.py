"""Retailer perks (cash back, gift cards, card offers): household data, admin edits."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user, require_admin
from ..db import get_db
from ..models import RetailerPerk, User

router = APIRouter(prefix="/api/perks", tags=["perks"])


class PerkIn(BaseModel):
    retailer_domain: str = Field(min_length=3, max_length=200, pattern=r"^[a-z0-9.-]+$")
    kind: str = Field(pattern=r"^(cashback|giftcard|card|other)$")
    label: str = Field(min_length=1, max_length=120)
    percent: float | None = Field(default=None, ge=0, le=50)
    notes: str | None = None
    url: str | None = Field(default=None, max_length=500)
    valid_until: date | None = None
    active: bool = True


def _out(p: RetailerPerk) -> dict:
    return {"id": p.id, "retailer_domain": p.retailer_domain, "kind": p.kind, "label": p.label, "percent": p.percent,
            "notes": p.notes, "url": p.url, "valid_until": p.valid_until.isoformat() if p.valid_until else None,
            "active": p.active}


@router.get("")
def list_perks(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [_out(p) for p in db.scalars(select(RetailerPerk).order_by(RetailerPerk.retailer_domain)).all()]


@router.post("", status_code=201)
def add_perk(body: PerkIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    p = RetailerPerk(**body.model_dump())
    db.add(p)
    db.commit()
    return _out(p)


@router.patch("/{perk_id}")
def edit_perk(perk_id: int, body: PerkIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    p = db.get(RetailerPerk, perk_id)
    if p is None:
        raise HTTPException(404, "Perk not found")
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    db.commit()
    return _out(p)


@router.delete("/{perk_id}", status_code=204)
def delete_perk(perk_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    p = db.get(RetailerPerk, perk_id)
    if p is None:
        raise HTTPException(404, "Perk not found")
    db.delete(p)
    db.commit()
