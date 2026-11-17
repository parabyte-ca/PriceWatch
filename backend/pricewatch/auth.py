"""Household accounts: username + password with a signed session cookie, per-person API tokens,
or "none" mode (reverse proxy handles auth; everyone acts as the admin)."""

import asyncio
import logging
import secrets
import time
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .config import Settings, get_settings
from .db import get_db, session_scope
from .models import User
from .services import users as users_svc

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

OPEN_PATHS = ("/api/auth/", "/healthz", "/api/actions/", "/api/shared/", "/api/photos/")
_failures: dict[str, list[float]] = defaultdict(list)


def load_secret_key(settings: Settings) -> str:
    if settings.secret_key:
        return settings.secret_key
    path: Path = settings.data_dir / ".secret_key"
    if path.is_file():
        return path.read_text().strip()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(48)
    path.write_text(key)
    path.chmod(0o600)
    return key


def _resolve_user_id(request: Request) -> int | None:
    s = get_settings()
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        db = session_scope()
        try:
            user = users_svc.user_by_token(db, header[7:].strip())
            return user.id if user else None
        finally:
            db.close()
    if s.auth_mode != "password":
        db = session_scope()
        try:
            return db.scalar(select(User.id).where(User.role == "admin", User.active.is_(True)).order_by(User.id))
        finally:
            db.close()
    uid = request.session.get("uid")
    return int(uid) if uid else None


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        protected = path.startswith("/api/") or path == "/metrics"
        request.state.user_id = None
        if protected and not path.startswith(OPEN_PATHS):
            uid = _resolve_user_id(request)
            if uid is None:
                return JSONResponse({"detail": "Not authenticated"}, status_code=401)
            request.state.user_id = uid
        elif path.startswith("/api/auth/"):
            request.state.user_id = _resolve_user_id(request)
        return await call_next(request)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    uid = getattr(request.state, "user_id", None)
    user = db.get(User, uid) if uid else None
    if user is None or not user.active:
        raise HTTPException(401, "Not authenticated")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Only the household admin can change this")
    return user


def bootstrap() -> None:
    db = session_scope()
    try:
        users_svc.ensure_admin(db)
    finally:
        db.close()


def user_out(user: User) -> dict:
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role,
            "has_token": bool(user.api_token_hash), "active": user.active}


class LoginIn(BaseModel):
    username: str = "admin"
    password: str


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    uid = getattr(request.state, "user_id", None)
    user = db.get(User, uid) if uid else None
    configured = db.scalar(select(User.id).where(User.password_hash.is_not(None)).limit(1)) is not None
    if user is None:
        return {"authenticated": False, "mode": s.auth_mode, "configured": configured}
    return {"authenticated": True, "mode": s.auth_mode, "configured": True, "user": user_out(user)}


@router.post("/login")
async def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    if s.auth_mode != "password":
        return {"authenticated": True}
    client = request.client.host if request.client else "?"
    recent = [t for t in _failures[client] if t > time.monotonic() - 900]
    _failures[client] = recent
    if len(recent) >= 10:
        raise HTTPException(429, "Too many attempts; wait 15 minutes")
    user = db.scalar(select(User).where(User.username == body.username.strip().lower(), User.active.is_(True)))
    if user is None or not users_svc.verify_password(body.password, user.password_hash):
        if user is not None and user.password_hash is None:
            raise HTTPException(503, "This account has no password yet; set PRICEWATCH_ADMIN_PASSWORD or ask the admin")
        _failures[client].append(time.monotonic())
        await asyncio.sleep(1.0)
        log.warning("failed login", extra={"client": client})
        raise HTTPException(401, "Wrong username or password")
    request.session["uid"] = user.id
    return {"authenticated": True, "user": user_out(user)}


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"authenticated": False}
