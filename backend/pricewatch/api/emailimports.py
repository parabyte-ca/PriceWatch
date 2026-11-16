"""Order emails read from the import mailbox."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user, require_admin
from ..config import get_settings
from ..db import get_db
from ..models import EmailImport, User
from ..services import emailimport, settings_store
from .items import _load_item

router = APIRouter(prefix="/api/email-imports", tags=["email-imports"])


def _out(r: EmailImport) -> dict:
    return {"id": r.id, "subject": r.subject, "received_at": r.received_at, "retailer_domain": r.retailer_domain,
            "order_ref": r.order_ref, "method": r.method, "status": r.status, "error": r.error,
            "lines": r.lines or []}


@router.get("")
def list_imports(db: Session = Depends(get_db), me: User = Depends(current_user)):
    s = get_settings()
    rows = db.scalars(select(EmailImport).where(EmailImport.user_id == me.id)
                      .order_by(EmailImport.created_at.desc()).limit(50)).all()
    return {"configured": emailimport.configured(), "enabled": bool(settings_store.get(db, "email_import_enabled")),
            "address": s.imap_user if emailimport.configured() else None, "imports": [_out(r) for r in rows]}


class LinkIn(BaseModel):
    line: int
    item_id: int


@router.post("/{import_id}/link")
def link_line(import_id: int, body: LinkIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    row = db.get(EmailImport, import_id)
    if row is None or row.user_id != me.id:
        raise HTTPException(404, "Import not found")
    item = _load_item(db, body.item_id, me, write=True)
    p = emailimport.link(db, row, body.line, item, me)
    return {"purchase_id": p.id if p else None, "import": _out(row)}


@router.post("/check")
async def check_now(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    if not emailimport.configured():
        raise HTTPException(409, "Set PRICEWATCH_IMAP_HOST, PRICEWATCH_IMAP_USER and PRICEWATCH_IMAP_PASSWORD in .env")
    try:
        return await asyncio.to_thread(emailimport.poll, db)
    except Exception as exc:  # noqa: BLE001 - show mailbox errors (login, folder) to the admin
        raise HTTPException(502, f"Mailbox: {type(exc).__name__}: {exc}") from exc
