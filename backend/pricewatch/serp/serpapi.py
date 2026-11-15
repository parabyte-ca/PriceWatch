"""SerpApi Google Shopping (gl=ca). Free plan: 250 searches per month."""

import httpx

from ..services.matching import Candidate
from .base import ProviderError, shopping_item_to_candidate


class SerpApiProvider:
    name = "serpapi"
    endpoint = "https://serpapi.com/search.json"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def search(self, query: str, client: httpx.AsyncClient) -> list[Candidate]:
        params = {
            "engine": "google_shopping",
            "q": query,
            "gl": "ca",
            "hl": "en",
            "google_domain": "google.ca",
            "location": "Canada",
            "api_key": self.api_key,
        }
        try:
            resp = await client.get(self.endpoint, params=params, timeout=40)
        except httpx.HTTPError as exc:
            raise ProviderError(f"SerpApi request failed: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            detail = ""
            try:
                detail = resp.json().get("error", "")
            except ValueError:
                pass
            raise ProviderError(f"SerpApi HTTP {resp.status_code} {detail}".strip())
        data = resp.json()
        if data.get("error"):
            raise ProviderError(f"SerpApi: {data['error']}")
        rows = list(data.get("shopping_results") or []) + list(data.get("inline_shopping_results") or [])
        return [c for c in (shopping_item_to_candidate(r, self.name) for r in rows) if c]
