"""FastAPI application: API, SPA, health and metrics."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select, text
from starlette.middleware.sessions import SessionMiddleware

from . import __version__, scheduler
from .api import items as items_api
from .api import system as system_api
from .auth import AuthMiddleware, load_secret_key
from .auth import router as auth_router
from .config import get_settings
from .db import get_engine, init_engine, session_scope
from .logging_setup import setup_logging
from .metrics import ITEMS_GAUGE, SOURCES_GAUGE
from .migrate import upgrade
from .models import Item, SourceLink
from .services import runtime
from .services.retailers import seed_retailers

log = logging.getLogger(__name__)
STATIC_DIR = Path(os.environ.get("PRICEWATCH_STATIC_DIR", Path(__file__).resolve().parent / "static"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    setup_logging(s.log_level)
    s.data_dir.mkdir(parents=True, exist_ok=True)
    upgrade()
    init_engine()
    db = session_scope()
    try:
        seed_retailers(db)
    finally:
        db.close()
    if s.auth_mode == "password" and not s.admin_password:
        log.warning("PRICEWATCH_ADMIN_PASSWORD is not set; login is disabled until it is")
    if s.scheduler_enabled:
        scheduler.start()
    log.info("started", extra={"version": __version__, "port": s.port})
    yield
    await scheduler.shutdown()
    await runtime.close()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="PriceWatch CA", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(SessionMiddleware, secret_key=load_secret_key(s), session_cookie="pricewatch_session",
                       max_age=60 * 60 * 24 * 30, same_site="lax", https_only=s.cookie_secure)
    app.include_router(auth_router)
    app.include_router(items_api.router)
    app.include_router(system_api.router)

    @app.get("/healthz")
    def healthz():
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
            db_ok = True
        except Exception:  # noqa: BLE001
            db_ok = False
        body = {"status": "ok" if db_ok else "degraded", "version": __version__, "database": db_ok}
        return JSONResponse(body, status_code=200 if db_ok else 503)

    @app.get("/metrics")
    def metrics():
        db = session_scope()
        try:
            ITEMS_GAUGE.set(db.scalar(select(func.count(Item.id)).where(Item.active.is_(True))) or 0)
            SOURCES_GAUGE.set(db.scalar(select(func.count(SourceLink.id)).where(
                SourceLink.status == "confirmed")) or 0)
        finally:
            db.close()
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    if (STATIC_DIR / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str, request: Request):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        candidate = (STATIC_DIR / path).resolve()
        if path and candidate.is_file() and STATIC_DIR.resolve() in candidate.parents:
            return FileResponse(candidate)
        index = STATIC_DIR / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse({"detail": "Frontend not built", "version": __version__})

    return app


app = create_app()
