"""Receipt photo: Claude reads the store, date and lines, suggests which of your items each line is, and you confirm.

Two steps on purpose: nothing is recorded until you press Save, because in-store receipts shorten names
("NINTENDO SW2 CNSL") and a wrong guess would start price protection on the wrong item.
"""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import Retailer, User
from ..services import claude
from ..services.emailimport import _visible_items, record_line
from ..services.retailers import domain_for_merchant

router = APIRouter(prefix="/api", tags=["receipts"])


class ReceiptLine(BaseModel):
    name: str
    price_cents: int | None = Field(description="price paid for one unit before tax, in cents")
    quantity: int = 1
    item_id: int | None = Field(description="the id of the shopper's item this line is, or null")


class Receipt(BaseModel):
    is_receipt: bool
    store: str | None
    date: str | None = Field(description="YYYY-MM-DD")
    lines: list[ReceiptLine]


class PhotoIn(BaseModel):
    image_b64: str = Field(min_length=100, max_length=6_000_000)
    media_type: str = Field(default="image/jpeg", pattern=r"^image/(jpeg|png|webp)$")


@router.post("/purchases/receipt/read")
async def read_receipt(body: PhotoIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    import anthropic

    key = claude.api_key()
    if not key:
        raise HTTPException(409, "Reading receipts needs a Claude key (Household admin)")
    left = claude.budget_left()
    if left is not None and left < 0.02:
        raise HTTPException(409, "This month's Claude spending cap is reached")
    items = [i for i in _visible_items(db, me) if i.active][:150]
    catalogue = "\n".join(f"{i.id}: {i.name}" + (f" ({i.brand})" if i.brand else "") for i in items) or "(none)"
    api = anthropic.AsyncAnthropic(api_key=key, timeout=90.0, max_retries=1)
    try:
        resp = await api.messages.parse(
            model=claude.PRICE_MODEL, max_tokens=4000, output_config={"effort": "low"},
            system=("Read a Canadian store receipt photo: the store, the purchase date and each product line with the "
                    "unit price before tax in cents. Skip taxes, totals, payments, deposits, eco fees and discounts "
                    "lines (apply an item's own instant discount to its price). For each line, give the id of the "
                    "shopper's item it is (receipts shorten names) or null when none fits. If it is not a receipt, "
                    "say so."),
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": body.media_type, "data": body.image_b64}},
                {"type": "text", "text": f"The shopper's items:\n{catalogue}"}]}],
            output_format=Receipt)
        claude.record_spend(claude.cost_usd(claude.PRICE_MODEL, getattr(resp, "usage", None)))
        r: Receipt | None = resp.parsed_output
    except anthropic.APIStatusError as exc:
        raise HTTPException(502, f"Claude could not read the receipt (HTTP {exc.status_code})") from exc
    except anthropic.APIConnectionError as exc:
        raise HTTPException(502, "Could not reach api.anthropic.com") from exc
    finally:
        await api.close()
    if r is None or not r.is_receipt:
        return {"is_receipt": False, "lines": []}
    valid = {i.id for i in items}
    return {"is_receipt": True, "store": r.store, "domain": domain_for_merchant(r.store or ""), "date": r.date,
            "lines": [{"name": ln.name[:200], "price_cents": ln.price_cents, "quantity": ln.quantity,
                       "item_id": ln.item_id if ln.item_id in valid else None} for ln in r.lines[:60]]}


class SaveLine(BaseModel):
    item_id: int
    price_cents: int = Field(ge=1)
    name: str | None = None


class SaveIn(BaseModel):
    store: str | None = Field(default=None, max_length=120)
    date: dt.date | None = None
    lines: list[SaveLine] = Field(min_length=1, max_length=60)


@router.post("/purchases/receipt/save")
def save_receipt(body: SaveIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    """Record the confirmed lines as purchases (price protection starts for each)."""
    from ..timeutil import utcnow

    allowed = {i.id: i for i in _visible_items(db, me)}
    domain = domain_for_merchant(body.store or "")
    retailer = db.scalar(select(Retailer).where(Retailer.domain == domain)) if domain else None
    bought = body.date or utcnow().date()
    saved = 0
    for ln in body.lines:
        item = allowed.get(ln.item_id)
        if item is None:
            raise HTTPException(404, "Item not found")
        p = record_line(db, me, item, retailer, {"price_cents": ln.price_cents, "score": 1.0}, bought, None)
        if p is not None:
            p.notes = "Recorded from a receipt photo"
            if retailer is None and body.store:
                p.retailer_name = body.store[:120]
            saved += 1
    db.commit()
    return {"saved": saved, "skipped": len(body.lines) - saved}

