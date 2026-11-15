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

OPEN_PATHS = ("/api/auth/", "/healthz")


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
            if not request.session.get("user"):
                return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        return await call_next(request)


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
