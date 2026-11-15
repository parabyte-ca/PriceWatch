"""Bright Data SERP API: Google Shopping for Canada, parsed JSON (brd_json=1)."""

from urllib.parse import urlencode

import httpx

from ..services.matching import Candidate
from .base import ProviderError, shopping_item_to_candidate


class BrightDataProvider:
    name = "brightdata"
    endpoint = "https://api.brightdata.com/request"

    def __init__(self, api_key: str, zone: str) -> None:
        self.api_key = api_key
        self.zone = zone

    async def search(self, query: str, client: httpx.AsyncClient) -> list[Candidate]:
        target = "https://www.google.ca/search?" + urlencode(
            {"q": query, "tbm": "shop", "gl": "ca", "hl": "en", "brd_json": "1"})
        try:
            resp = await client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"zone": self.zone, "url": target, "format": "raw"},
                timeout=60,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Bright Data request failed: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise ProviderError(f"Bright Data HTTP {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderError("Bright Data returned non-JSON; check that the zone is a SERP API zone") from exc
        rows = data.get("shopping") or data.get("shopping_results") or data.get("organic") or []
        return [c for c in (shopping_item_to_candidate(r, self.name) for r in rows if isinstance(r, dict)) if c]
