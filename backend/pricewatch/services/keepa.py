"""Keepa API for Amazon.ca (domain 6). Paid: tokens per minute; 1 token per product request.

Prices are integer cents in the marketplace currency; -1 means no offer.
Times are "Keepa minutes": minutes since 2011-01-01 00:00 UTC.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

KEEPA_DOMAIN_CA = 6
KEEPA_EPOCH_MINUTES = 21564000  # 2011-01-01 in minutes since the Unix epoch
CSV_AMAZON, CSV_NEW, CSV_LIST_PRICE, CSV_BUY_BOX = 0, 1, 4, 18
ASIN_RE = re.compile(r"/(?:dp|gp/product|gp/aw/d|product)/([A-Z0-9]{10})(?:[/?]|$)")


class KeepaError(Exception):
    pass


def asin_from_url(url: str) -> str | None:
    m = ASIN_RE.search(url)
    return m.group(1) if m else None


def keepa_time(minutes: int) -> datetime:
    return datetime.fromtimestamp((minutes + KEEPA_EPOCH_MINUTES) * 60, UTC).replace(tzinfo=None)


@dataclass
class KeepaProduct:
    asin: str
    title: str | None
    brand: str | None
    model: str | None
    gtin: str | None
    image: str | None
    amazon_price_cents: int | None  # Amazon as the seller
    buybox_price_cents: int | None  # includes shipping; may be a marketplace seller
    list_price_cents: int | None
    amazon_history: list[tuple[datetime, int | None]]  # None = Amazon out of stock
    tokens_left: int | None


def _cur(stats: dict, idx: int) -> int | None:
    current = (stats or {}).get("current") or []
    if idx < len(current) and isinstance(current[idx], int) and current[idx] > 0:
        return current[idx]
    return None


def _history(csv: list, idx: int, step: int) -> list[tuple[datetime, int | None]]:
    if not csv or idx >= len(csv) or not csv[idx]:
        return []
    arr = csv[idx]
    out = []
    for i in range(0, len(arr) - 1, step):
        t, price = arr[i], arr[i + 1]
        out.append((keepa_time(t), price if price and price > 0 else None))
    return out


def parse_product(data: dict) -> KeepaProduct:
    products = data.get("products") or []
    if not products:
        raise KeepaError("Keepa returned no product")
    p = products[0]
    stats = p.get("stats") or {}
    images = (p.get("imagesCSV") or "").split(",")
    eans = p.get("eanList") or []
    upcs = p.get("upcList") or []
    return KeepaProduct(
        asin=p.get("asin"),
        title=p.get("title"),
        brand=p.get("brand"),
        model=p.get("model") or p.get("partNumber"),
        gtin=(eans[0] if eans else (upcs[0] if upcs else None)),
        image=f"https://m.media-amazon.com/images/I/{images[0]}" if images and images[0] else None,
        amazon_price_cents=_cur(stats, CSV_AMAZON),
        buybox_price_cents=_cur(stats, CSV_BUY_BOX),
        list_price_cents=_cur(stats, CSV_LIST_PRICE),
        amazon_history=_history(p.get("csv") or [], CSV_AMAZON, 2),
        tokens_left=data.get("tokensLeft"),
    )


async def fetch_product(api_key: str, asin: str, client: httpx.AsyncClient | None = None,
                        history: bool = True) -> KeepaProduct:
    params = {"key": api_key, "domain": KEEPA_DOMAIN_CA, "asin": asin, "stats": 180,
              "history": 1 if history else 0, "buybox": 1}
    own = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        resp = await client.get("https://api.keepa.com/product", params=params)
    except httpx.HTTPError as exc:
        raise KeepaError(f"Keepa request failed: {type(exc).__name__}") from exc
    finally:
        if own:
            await client.aclose()
    if resp.status_code == 429:
        raise KeepaError("Keepa: out of tokens, will retry later")
    if resp.status_code != 200:
        raise KeepaError(f"Keepa HTTP {resp.status_code}")
    data = resp.json()
    if data.get("error"):
        raise KeepaError(f"Keepa: {data['error'].get('message', data['error'])}")
    return parse_product(data)
