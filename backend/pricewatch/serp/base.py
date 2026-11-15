from typing import Protocol

import httpx

from ..adapters.base import parse_price
from ..services.matching import Candidate


class ProviderError(Exception):
    pass


class SerpProvider(Protocol):
    name: str

    async def search(self, query: str, client: httpx.AsyncClient) -> list[Candidate]: ...


_SECOND_HAND = {"refurbished": "refurbished", "used": "used", "pre-owned": "used", "open box": "open box"}


def shopping_item_to_candidate(row: dict, provider: str) -> Candidate | None:
    """Convert one Google Shopping result row (SerpApi or Bright Data JSON) into a Candidate."""
    title = row.get("title")
    url = row.get("link") or row.get("url") or row.get("product_link")
    if not title or not url:
        return None
    price = row.get("extracted_price")
    price_cents = parse_price(price) if price is not None else parse_price(row.get("price"))
    condition = None
    cond_text = str(row.get("second_hand_condition") or row.get("condition") or "").lower()
    for key, value in _SECOND_HAND.items():
        if key in cond_text:
            condition = value
    shipping = None
    delivery = str(row.get("delivery") or row.get("shipping") or "").lower()
    if "free" in delivery:
        shipping = 0
    elif delivery:
        shipping = parse_price(delivery)
    return Candidate(
        title=str(title),
        url=str(url),
        price_cents=price_cents,
        merchant=row.get("source") or row.get("shop") or row.get("merchant") or row.get("seller"),
        condition=condition,
        shipping_cents=shipping,
        provider=provider,
        extra={"product_id": row.get("product_id"), "google_link": row.get("product_link")},
    )
