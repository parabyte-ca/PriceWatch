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
    return out


def get_provider(name: str | None = None) -> SerpProvider | None:
    providers = available_providers()
    if name:
        return providers.get(name)
    return next(iter(providers.values()), None)
