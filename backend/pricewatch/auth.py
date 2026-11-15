"""Single-admin password auth with a signed session cookie, or "none" for reverse proxy auth."""

import asyncio
import hmac
import logging
import secrets
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .config import Settings, get_settings
from .schemas import LoginIn

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

OPEN_PATHS = ("/api/auth/", "/healthz", "/api/actions/")


def _token_ok(request: Request) -> bool:
    """Personal API token for the iOS Shortcut and scripts: Authorization: Bearer <token>."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return False
    supplied = header[7:].strip()
    from .db import session_scope
    from .services import settings_store

    db = session_scope()
    try:
        token = settings_store.get(db, "api_token") or ""
    finally:
        db.close()
    return bool(token) and hmac.compare_digest(supplied.encode(), token.encode())


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


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        s = get_settings()
        path = request.url.path
        protected = path.startswith("/api/") or path == "/metrics"
        if s.auth_mode == "password" and protected and not path.startswith(OPEN_PATHS):
            if not request.session.get("user") and not _token_ok(request):
                return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        return await call_next(request)


def ensure_api_token() -> None:
    from .db import session_scope
    from .services import settings_store

    db = session_scope()
    try:
        if not settings_store.get(db, "api_token"):
            settings_store.update(db, {"api_token": secrets.token_urlsafe(32)})
    finally:
        db.close()


@router.get("/me")
def me(request: Request):
    s = get_settings()
    if s.auth_mode != "password":
        return {"authenticated": True, "mode": s.auth_mode}
    return {"authenticated": bool(request.session.get("user")), "mode": s.auth_mode,
            "configured": bool(s.admin_password)}


@router.post("/login")
async def login(body: LoginIn, request: Request):
    s = get_settings()
    if s.auth_mode != "password":
        return {"authenticated": True}
    if not s.admin_password:
        raise HTTPException(503, "PRICEWATCH_ADMIN_PASSWORD is not set; run setup.sh or set it in .env")
    if not hmac.compare_digest(body.password.encode(), s.admin_password.encode()):
        await asyncio.sleep(1.0)
        log.warning("failed login", extra={"client": request.client.host if request.client else None})
        raise HTTPException(401, "Wrong password")
    request.session["user"] = "admin"
    return {"authenticated": True}


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"authenticated": False}
