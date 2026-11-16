"""eBay Browse API (eBay Canada): new, fixed-price listings for the comparison.

Official API with an application token (EBAY_CLIENT_ID and EBAY_CLIENT_SECRET from developer.ebay.com, free). eBay
listings are third-party sellers, so they appear with the marketplace listings: shown for reference, never tracked as
a store.
"""

import base64
import time

import httpx

from ..services.matching import Candidate
from .base import ProviderError

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
_token: tuple[float, str] | None = None


class EbayProvider:
    name = "ebay"

    def __init__(self, client_id: str, client_secret: str) -> None:
        self.client_id, self.client_secret = client_id, client_secret

    async def _access_token(self, client: httpx.AsyncClient) -> str:
        global _token
        if _token and _token[0] > time.monotonic() + 60:
            return _token[1]
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        resp = await client.post(TOKEN_URL, headers={"Authorization": f"Basic {basic}"}, timeout=30,
                                 data={"grant_type": "client_credentials",
                                       "scope": "https://api.ebay.com/oauth/api_scope"})
        if resp.status_code != 200:
            raise ProviderError(f"eBay token request failed (HTTP {resp.status_code})")
        data = resp.json()
        _token = (time.monotonic() + int(data.get("expires_in", 7200)), data["access_token"])
        return _token[1]

    async def search(self, query: str, client: httpx.AsyncClient) -> list[Candidate]:
        try:
            token = await self._access_token(client)
            resp = await client.get(SEARCH_URL, timeout=30, params={
                "q": query[:100], "limit": "20",
                "filter": "conditions:{NEW},buyingOptions:{FIXED_PRICE},deliveryCountry:CA,priceCurrency:CAD"},
                headers={"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_CA"})
        except httpx.HTTPError as exc:
            raise ProviderError(f"eBay request failed: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise ProviderError(f"eBay search failed (HTTP {resp.status_code})")
        out = []
        for it in resp.json().get("itemSummaries") or []:
            price = it.get("price") or {}
            if price.get("currency") != "CAD":
                continue
            try:
                cents = round(float(price["value"]) * 100)
            except (KeyError, TypeError, ValueError):
                continue
            ship = None
            opts = it.get("shippingOptions") or []
            if opts and (opts[0].get("shippingCost") or {}).get("currency") == "CAD":
                try:
                    ship = round(float(opts[0]["shippingCost"]["value"]) * 100)
                except (KeyError, TypeError, ValueError):
                    ship = None
            seller = (it.get("seller") or {}).get("username") or "seller"
            url = it.get("itemWebUrl")
            if not url or not it.get("title"):
                continue
            out.append(Candidate(title=it["title"], url=url, price_cents=cents, merchant=f"eBay - {seller}",
                                 shipping_cents=ship, provider=self.name, condition="new"))
        return out


def ebay_provider() -> EbayProvider | None:
    from ..config import get_settings

    s = get_settings()
    if s.ebay_client_id and s.ebay_client_secret:
        return EbayProvider(s.ebay_client_id, s.ebay_client_secret)
    return None
