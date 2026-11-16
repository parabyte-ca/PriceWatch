"""People (household accounts), lists, membership and friend codes."""

import time
from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import current_user, require_admin, user_out
from ..db import get_db
from ..models import Item, ListInvite, ListMember, User, WishList
from ..services import users as users_svc
from ..timeutil import utcnow

router = APIRouter(prefix="/api", tags=["accounts"])
_join_attempts: dict[int, list[float]] = defaultdict(list)
USERNAME = r"^[a-z0-9._-]{2,40}$"


# ---------- people ----------

class UserCreate(BaseModel):
    username: str = Field(pattern=USERNAME)
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=200)
    role: str = Field(default="member", pattern=r"^(admin|member)$")


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    role: str | None = Field(default=None, pattern=r"^(admin|member)$")
    active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=200)


class PasswordChange(BaseModel):
    current: str
    new: str = Field(min_length=8, max_length=200)


@router.get("/users")
def list_users(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(User).order_by(User.id)).all()
    if user.role == "admin":
        return [user_out(u) for u in rows]
    return [{"id": u.id, "display_name": u.display_name} for u in rows if u.active]


@router.post("/users", status_code=201)
def create_user(body: UserCreate, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        u = users_svc.create_user(db, body.username, body.display_name, body.password, role=body.role)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "That username is taken") from exc
    return user_out(u)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, me: User = Depends(current_user), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found")
    changes = body.model_dump(exclude_unset=True)
    if me.role != "admin":
        if u.id != me.id or set(changes) - {"display_name"}:
            raise HTTPException(403, "You can only change your own display name")
    if u.id == me.id and (changes.get("role") == "member" or changes.get("active") is False):
        admins = db.scalar(select(func.count(User.id)).where(User.role == "admin", User.active.is_(True)))
        if admins <= 1:
            raise HTTPException(409, "Keep at least one active admin")
    if "password" in changes:
        u.password_hash = users_svc.hash_password(changes.pop("password"))
    for k, v in changes.items():
        setattr(u, k, v)
    db.commit()
    return user_out(u)


@router.post("/me/password")
def change_password(body: PasswordChange, me: User = Depends(current_user), db: Session = Depends(get_db)):
    if not users_svc.verify_password(body.current, me.password_hash):
        raise HTTPException(403, "Current password is wrong")
    me.password_hash = users_svc.hash_password(body.new)
    db.commit()
    return {"ok": True}


@router.post("/me/token")
def rotate_token(me: User = Depends(current_user), db: Session = Depends(get_db)):
    """Create (or replace) your personal API token. Shown once."""
    token = users_svc.new_api_token(me)
    db.commit()
    return {"token": token}


@router.delete("/me/token")
def revoke_token(me: User = Depends(current_user), db: Session = Depends(get_db)):
    me.api_token_hash = None
    db.commit()
    return {"ok": True}


# ---------- lists ----------

class ListIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    occasion: str | None = Field(default=None, max_length=120)
    recipient: str | None = Field(default=None, max_length=120)
    event_date: date | None = None
    budget_cents: int | None = Field(default=None, ge=0)


class ListUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    occasion: str | None = Field(default=None, max_length=120)
    recipient: str | None = Field(default=None, max_length=120)
    event_date: date | None = None
    budget_cents: int | None = Field(default=None, ge=0)


class InviteIn(BaseModel):
    role: str = Field(default="editor", pattern=r"^(editor|viewer)$")


class JoinIn(BaseModel):
    code: str = Field(min_length=6, max_length=20)


def _list_or_404(db: Session, list_id: int) -> WishList:
    lst = db.get(WishList, list_id)
    if lst is None:
        raise HTTPException(404, "List not found")
    return lst


def _list_out(db: Session, lst: WishList, me: User) -> dict:
    members = db.execute(select(ListMember, User).join(User, User.id == ListMember.user_id)
                         .where(ListMember.list_id == lst.id).order_by(ListMember.id)).all()
    count = db.scalar(select(func.count(Item.id)).where(Item.list_id == lst.id, Item.active.is_(True)))
    my_role = next((m.role for m, u in members if u.id == me.id), None)
    from ..services.savings import list_spent

    spent = list_spent(db, lst.id)
    return {"id": lst.id, "name": lst.name, "role": my_role, "items": count, "shared": len(members) > 1,
            "occasion": lst.occasion, "recipient": lst.recipient,
            "event_date": lst.event_date.isoformat() if lst.event_date else None,
            "budget_cents": lst.budget_cents, "spent_cents": spent,
            "remaining_cents": (lst.budget_cents - spent) if lst.budget_cents is not None else None,
            "members": [{"user_id": u.id, "display_name": u.display_name, "role": m.role} for m, u in members]}


@router.get("/lists")
def my_lists(me: User = Depends(current_user), db: Session = Depends(get_db)):
    return [_list_out(db, db.get(WishList, m.list_id), me) for m in users_svc.memberships(db, me)]


@router.post("/lists", status_code=201)
def create_list(body: ListIn, me: User = Depends(current_user), db: Session = Depends(get_db)):
    lst = WishList(name=body.name.strip(), owner_id=me.id, occasion=body.occasion, recipient=body.recipient,
                   event_date=body.event_date, budget_cents=body.budget_cents)
    db.add(lst)
    db.flush()
    db.add(ListMember(list_id=lst.id, user_id=me.id, role="owner"))
    db.commit()
    return _list_out(db, lst, me)


@router.patch("/lists/{list_id}")
def rename_list(list_id: int, body: ListUpdate, me: User = Depends(current_user), db: Session = Depends(get_db)):
    lst = _list_or_404(db, list_id)
    if users_svc.role_in(db, me, list_id) != "owner":
        raise HTTPException(403, "Only the list owner can change it")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(lst, k, v.strip() if isinstance(v, str) else v)
    db.commit()
    return _list_out(db, lst, me)


@router.delete("/lists/{list_id}", status_code=204)
def delete_list(list_id: int, me: User = Depends(current_user), db: Session = Depends(get_db)):
    lst = _list_or_404(db, list_id)
    if users_svc.role_in(db, me, list_id) != "owner":
        raise HTTPException(403, "Only the list owner can delete it")
    if db.scalar(select(func.count(Item.id)).where(Item.list_id == list_id)):
        raise HTTPException(409, "Move or delete the items first; deleting a list never deletes price history silently")
    if len(users_svc.memberships(db, me)) <= 1:
        raise HTTPException(409, "Keep at least one list")
    db.delete(lst)
    db.commit()


@router.post("/lists/{list_id}/invites", status_code=201)
def invite(list_id: int, body: InviteIn | None = None, me: User = Depends(current_user), db: Session = Depends(get_db)):
    _list_or_404(db, list_id)
    if users_svc.role_in(db, me, list_id) != "owner":
        raise HTTPException(403, "Only the list owner can invite people")
    code, inv = users_svc.create_invite(db, me, list_id, (body or InviteIn()).role)
    db.commit()
    return {"code": code, "role": inv.role, "expires_at": inv.expires_at.isoformat() + "Z"}


@router.post("/lists/join")
def join(body: JoinIn, me: User = Depends(current_user), db: Session = Depends(get_db)):
    now = time.monotonic()
    attempts = [t for t in _join_attempts[me.id] if t > now - 3600]
    _join_attempts[me.id] = attempts
    if len(attempts) >= 10:
        raise HTTPException(429, "Too many tries; wait an hour")
    _join_attempts[me.id].append(now)
    try:
        lst = users_svc.redeem_invite(db, me, body.code)
    except users_svc.InviteError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return _list_out(db, lst, me)


@router.delete("/lists/{list_id}/members/{user_id}", status_code=204)
def remove_member(list_id: int, user_id: int, me: User = Depends(current_user), db: Session = Depends(get_db)):
    _list_or_404(db, list_id)
    my_role = users_svc.role_in(db, me, list_id)
    if my_role is None or (user_id != me.id and my_role != "owner"):
        raise HTTPException(403, "Only the owner can remove someone; anyone can leave")
    m = db.scalar(select(ListMember).where(ListMember.list_id == list_id, ListMember.user_id == user_id))
    if m is None:
        raise HTTPException(404, "Not a member")
    if m.role == "owner":
        raise HTTPException(409, "The owner cannot leave their own list; delete it or give it away first")
    db.delete(m)
    db.commit()


@router.get("/lists/{list_id}/invites")
def list_invites(list_id: int, me: User = Depends(current_user), db: Session = Depends(get_db)):
    if users_svc.role_in(db, me, list_id) != "owner":
        raise HTTPException(403, "Only the list owner can see invites")
    rows = db.scalars(select(ListInvite).where(ListInvite.list_id == list_id, ListInvite.used_at.is_(None),
                                               ListInvite.expires_at > utcnow())).all()
    return [{"id": i.id, "role": i.role, "expires_at": i.expires_at.isoformat() + "Z"} for i in rows]
