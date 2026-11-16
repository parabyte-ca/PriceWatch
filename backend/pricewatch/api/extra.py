"""Quick-add (import, share), notification actions, API token, policies, digest."""

import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user, require_admin
from ..db import get_db
from ..models import Item, PricePolicy, User, UserItemPref
from ..services import alerts, settings_store
from ..timeutil import utcnow
from .items import _load_item, _target_list, create_item_from_url

router = APIRouter(prefix="/api", tags=["extra"])
URL_RE = re.compile(r"https?://\S+")


class ImportIn(BaseModel):
    text: str = Field(max_length=100_000)
    hot: bool = False
    list_id: int | None = None


@router.post("/import")
async def import_list(body: ImportIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    """One URL or product name per line. URLs are tracked and filled in by their first check; names become items."""
    created, skipped = [], []
    list_id = _target_list(db, me, body.list_id)
    for raw in body.text.splitlines():
        line = raw.strip().strip(",;")
        if not line or line.startswith("#"):
            continue
        m = URL_RE.search(line)
        try:
            if m:
                item = await create_item_from_url(db, m.group(0), hot=body.hot, fetch_now=False, user=me,
                                                  list_id=list_id)
            else:
                item = Item(name=line[:300], hot=body.hot, list_id=list_id, added_by=me.id)
                db.add(item)
                db.commit()
            created.append({"id": item.id, "line": line[:200]})
        except HTTPException as exc:
            db.rollback()
            skipped.append({"line": line[:200], "reason": exc.detail})
    return {"created": created, "skipped": skipped}


class SnoozeIn(BaseModel):
    hours: int = Field(default=24, ge=1, le=24 * 30)


def set_snooze(db: Session, user_id: int, item_id: int, until) -> None:
    pref = db.get(UserItemPref, (user_id, item_id))
    if pref is None:
        pref = UserItemPref(user_id=user_id, item_id=item_id)
        db.add(pref)
    pref.snoozed_until = until
    db.commit()


@router.post("/items/{item_id}/snooze")
def snooze(item_id: int, body: SnoozeIn | None = None, db: Session = Depends(get_db),
           me: User = Depends(current_user)):
    """Snooze your own alerts for this item (others on a shared list are unaffected)."""
    _load_item(db, item_id, me)
    until = utcnow() + timedelta(hours=(body or SnoozeIn()).hours)
    set_snooze(db, me.id, item_id, until)
    return {"snoozed_until": until.isoformat() + "Z"}


@router.delete("/items/{item_id}/snooze")
def unsnooze(item_id: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    _load_item(db, item_id, me)
    set_snooze(db, me.id, item_id, None)
    return {"snoozed_until": None}


@router.api_route("/actions/{token}", methods=["GET", "POST"], response_class=HTMLResponse)
def action(token: str, db: Session = Depends(get_db)):
    """Signed one-tap actions from notifications (no login needed; links expire after 7 days)."""
    parsed = alerts.read_action_token(token)
    if not parsed:
        raise HTTPException(403, "This link has expired or is invalid")
    item_id, act, user_id = parsed
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "Item not found")
    user_id = user_id or settings_store._admin_id(db)
    if act == "snooze":
        set_snooze(db, user_id, item_id, utcnow() + timedelta(hours=24))
        return HTMLResponse(f"<p>Snoozed your alerts for {item.name} for 24 hours.</p>")
    raise HTTPException(400, "Unknown action")


class PolicyUpdate(BaseModel):
    competitor_match: bool | None = None
    own_price_adjustment: bool | None = None
    window_days: int | None = Field(default=None, ge=0, le=365)
    member_window_days: int | None = Field(default=None, ge=0, le=365)
    electronics_window_days: int | None = Field(default=None, ge=0, le=365)
    excluded_events: list[str] | None = None
    excludes_marketplace: bool | None = None
    event_guarantee: str | None = None
    verified: bool | None = None
    enabled: bool | None = None
    notes: str | None = None


def _policy_dict(p: PricePolicy) -> dict:
    return {k: getattr(p, k) for k in ("id", "domain", "competitor_match", "own_price_adjustment", "window_days",
                                       "member_window_days", "electronics_window_days", "excluded_events",
                                       "excludes_marketplace", "excludes_open_box", "event_guarantee", "verified",
                                       "enabled", "notes", "source_url")}


@router.get("/policies")
def list_policies(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [_policy_dict(p) for p in db.scalars(select(PricePolicy).order_by(PricePolicy.domain)).all()]


@router.patch("/policies/{policy_id}")
def update_policy(policy_id: int, body: PolicyUpdate, db: Session = Depends(get_db),
                  _: User = Depends(require_admin)):
    p = db.get(PricePolicy, policy_id)
    if p is None:
        raise HTTPException(404, "Policy not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    return _policy_dict(p)


@router.get("/digest/preview")
def digest_preview(db: Session = Depends(get_db), me: User = Depends(current_user)):
    title, body = alerts.build_digest(db, me.id)
    db.rollback()  # preview only: leave pending digest alerts untouched
    return {"title": title, "body": body}
