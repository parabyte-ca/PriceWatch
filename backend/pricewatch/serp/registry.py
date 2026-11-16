from ..config import get_settings
from .base import SerpProvider
from .brightdata import BrightDataProvider
from .serpapi import SerpApiProvider


def available_providers() -> dict[str, SerpProvider]:
    s = get_settings()
    out: dict[str, SerpProvider] = {}
    if s.serpapi_key:
        out["serpapi"] = SerpApiProvider(s.serpapi_key)
    if s.brightdata_api_key:
        out["brightdata"] = BrightDataProvider(s.brightdata_api_key, s.brightdata_zone)
    claude_web = _claude_provider()
    if claude_web is not None:
        out["claude"] = claude_web
    return out


def _claude_provider():
    """Claude web search across known Canadian stores, when a Claude key is set and the household allows it."""
    from sqlalchemy import select

    from ..db import session_scope
    from ..models import Retailer
    from ..services import claude, settings_store
    from .claude_web import ClaudeWebProvider

    key = claude.api_key()
    if not key:
        return None
    db = session_scope()
    try:
        if not settings_store.get(db, "web_search_enabled"):
            return None
        model = claude.config(db)["model"]
        domains = [r.domain for r in db.scalars(select(Retailer).order_by(Retailer.id)).all()
                   if r.fetch_mode not in ("manual",) and "." in r.domain]
    finally:
        db.close()
    return ClaudeWebProvider(key, model, domains)


def get_provider(name: str | None = None) -> SerpProvider | None:
    providers = available_providers()
    if name:
        return providers.get(name)
    return next(iter(providers.values()), None)
