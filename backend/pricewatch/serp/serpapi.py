"""SerpApi Google Shopping (gl=ca). Free plan: 250 searches per month."""

import httpx

from ..services.matching import Candidate
from .base import ProviderError, shopping_item_to_candidate


class SerpApiProvider:
    name = "serpapi"
    endpoint = "https://serpapi.com/search.json"

    def __init__(self, api_key: str, location: str = "Canada") -> None:
        self.api_key = api_key
        self.location = location  # a city gives "in stock nearby" and pickup notes in results

    async def search(self, query: str, client: httpx.AsyncClient) -> list[Candidate]:
        params = {
            "engine": "google_shopping",
            "q": query,
            "gl": "ca",
            "hl": "en",
            "google_domain": "google.ca",
            "location": self.location or "Canada",
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

    async def on_sale(self, query: str, client: httpx.AsyncClient) -> list[Candidate]:
        """Google Shopping Canada filtered to items on sale (each result carries its was-price)."""
        params = {"engine": "google_shopping", "q": query, "gl": "ca", "hl": "en", "google_domain": "google.ca",
                  "location": "Canada", "tbs": "mr:1,sales:1", "api_key": self.api_key}
        try:
            resp = await client.get(self.endpoint, params=params, timeout=40)
        except httpx.HTTPError as exc:
            raise ProviderError(f"SerpApi request failed: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise ProviderError(f"SerpApi HTTP {resp.status_code}")
        data = resp.json()
        if data.get("error"):
            raise ProviderError(f"SerpApi: {data['error']}")
        rows = list(data.get("shopping_results") or [])
        return [c for c in (shopping_item_to_candidate(r, self.name) for r in rows) if c]

    async def expand(self, token: str, client: httpx.AsyncClient) -> list[Candidate]:
        """One Google Shopping product's store list with direct links (Google now hides them in the main results)."""
        params = {"engine": "google_immersive_product", "page_token": token, "gl": "ca", "hl": "en",
                  "api_key": self.api_key}
        try:
            resp = await client.get(self.endpoint, params=params, timeout=40)
        except httpx.HTTPError as exc:
            raise ProviderError(f"SerpApi request failed: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise ProviderError(f"SerpApi HTTP {resp.status_code}")
        data = resp.json()
        if data.get("error"):
            raise ProviderError(f"SerpApi: {data['error']}")
        product = data.get("product_results") or {}
        stores = product.get("stores") or data.get("stores") or []
        out = []
        for st in stores:
            if not isinstance(st, dict):
                continue
            row = {"title": st.get("title") or product.get("title"), "link": st.get("link"),
                   "thumbnail": next(iter(product.get("thumbnails") or []), None),
                   "extracted_price": st.get("extracted_price"), "price": st.get("price"),
                   "source": st.get("name"), "delivery": st.get("shipping") or st.get("delivery")}
            c = shopping_item_to_candidate(row, self.name)
            if c:
                out.append(c)
        return out
