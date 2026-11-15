"""Household accounts, lists, membership and friend codes."""

import hashlib
import hmac
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Item, ListInvite, ListMember, User, WishList
from ..timeutil import utcnow

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
INVITE_DAYS = 7
ROLES_WRITE = ("owner", "editor")


# ---------- passwords and tokens ----------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        _, n, r, p, salt, digest = stored.split("$")
        calc = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                              dklen=len(bytes.fromhex(digest)))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calc.hex(), digest)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_api_token(user: User) -> str:
    token = secrets.token_urlsafe(32)
    user.api_token_hash = token_hash(token)
    return token


def user_by_token(db: Session, token: str) -> User | None:
    if not token:
        return None
    return db.scalar(select(User).where(User.api_token_hash == token_hash(token), User.active.is_(True)))


# ---------- bootstrap ----------

def create_user(db: Session, username: str, display_name: str, password: str | None, role: str = "member",
                list_name: str | None = None) -> User:
    user = User(username=username.strip().lower(), display_name=display_name.strip() or username, role=role,
                password_hash=hash_password(password) if password else None)
    db.add(user)
    db.flush()
    lst = WishList(name=list_name or f"{user.display_name}'s list", owner_id=user.id)
    db.add(lst)
    db.flush()
    db.add(ListMember(list_id=lst.id, user_id=user.id, role="owner"))
    db.flush()
    return user


def ensure_admin(db: Session) -> User:
    """First start: create the admin. Upgrades: give the migrated admin the password from .env."""
    s = get_settings()
    admin = db.scalar(select(User).where(User.role == "admin").order_by(User.id).limit(1))
    if admin is None:
        admin = create_user(db, s.admin_username, s.admin_username.title(), s.admin_password, role="admin",
                            list_name="My list")
    elif admin.password_hash is None and s.admin_password:
        admin.password_hash = hash_password(s.admin_password)
    # items created before accounts existed (or by tests) land in the admin's first list
    orphan = db.scalars(select(Item).where(Item.list_id.is_(None))).all()
    if orphan:
        default = default_list(db, admin)
        for item in orphan:
            item.list_id = default.id
            item.added_by = item.added_by or admin.id
    db.commit()
    return admin


# ---------- lists and access ----------

def memberships(db: Session, user: User) -> list[ListMember]:
    return list(db.scalars(select(ListMember).where(ListMember.user_id == user.id).order_by(ListMember.list_id)).all())


def list_ids(db: Session, user: User) -> list[int]:
    return [m.list_id for m in memberships(db, user)]


def default_list(db: Session, user: User) -> WishList:
    m = db.scalar(select(ListMember).where(ListMember.user_id == user.id)
                  .order_by((ListMember.role != "owner"), ListMember.list_id).limit(1))
    if m is None:
        lst = WishList(name=f"{user.display_name}'s list", owner_id=user.id)
        db.add(lst)
        db.flush()
        db.add(ListMember(list_id=lst.id, user_id=user.id, role="owner"))
        db.flush()
        return lst
    return db.get(WishList, m.list_id)


def role_in(db: Session, user: User, list_id: int | None) -> str | None:
    if list_id is None:
        return None
    m = db.scalar(select(ListMember).where(ListMember.user_id == user.id, ListMember.list_id == list_id))
    return m.role if m else None


def can_read(db: Session, user: User, item: Item) -> bool:
    return role_in(db, user, item.list_id) is not None


def can_write(db: Session, user: User, item_or_list_id) -> bool:
    list_id = item_or_list_id.list_id if isinstance(item_or_list_id, Item) else item_or_list_id
    return role_in(db, user, list_id) in ROLES_WRITE


def members_of(db: Session, list_id: int | None) -> list[User]:
    if list_id is None:
        return list(db.scalars(select(User).where(User.role == "admin", User.active.is_(True))).all())
    return list(db.scalars(select(User).join(ListMember, ListMember.user_id == User.id)
                           .where(ListMember.list_id == list_id, User.active.is_(True))).all())


# ---------- friend codes ----------

def _code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    return f"PW-{raw[:4]}-{raw[4:]}"


def normalise_code(code: str) -> str:
    raw = "".join(c for c in code.upper() if c.isalnum())
    raw = raw[2:] if raw.startswith("PW") else raw
    return f"PW-{raw[:4]}-{raw[4:8]}"


def create_invite(db: Session, user: User, list_id: int, role: str = "editor") -> tuple[str, ListInvite]:
    code = _code()
    inv = ListInvite(list_id=list_id, code_hash=token_hash(code), role=role, created_by=user.id,
                     expires_at=utcnow() + timedelta(days=INVITE_DAYS))
    db.add(inv)
    db.flush()
    return code, inv


class InviteError(Exception):
    pass


def redeem_invite(db: Session, user: User, code: str) -> WishList:
    inv = db.scalar(select(ListInvite).where(ListInvite.code_hash == token_hash(normalise_code(code))))
    if inv is None or inv.used_at is not None or inv.expires_at < utcnow():
        raise InviteError("That code is not valid. Codes work once and expire after 7 days.")
    if role_in(db, user, inv.list_id):
        raise InviteError("You are already a member of that list.")
    db.add(ListMember(list_id=inv.list_id, user_id=user.id, role=inv.role))
    inv.used_by, inv.used_at = user.id, utcnow()
    db.flush()
    return db.get(WishList, inv.list_id)
