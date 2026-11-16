"""Best Buy Canada: read the product JSON the site's own pages use (opt-in fetch mode "bestbuy_api").

Unverified against the live site; the shape is parsed defensively and any miss falls back to the normal page check.
The request still goes through the polite fetcher, so robots.txt and the per-domain delay apply.
"""

import json
import re

from .base import ParsedProduct, parse_price

SKU_RE = re.compile(r"/product/(?:[^/]+/)?(\d{7,9})(?:[/?#]|$)")
API = "https://www.bestbuy.ca/api/v2/json/product/{sku}?lang=en-CA"


def sku_from_url(url: str) -> str | None:
    m = SKU_RE.search(url)
    return m.group(1) if m else None


def api_url(url: str) -> str | None:
    sku = sku_from_url(url)
    return API.format(sku=sku) if sku else None


def parse_json(text: str, url: str) -> ParsedProduct | None:
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("product"), dict):
        data = data["product"]
    sale = parse_price(data.get("salePrice") if data.get("salePrice") not in (None, 0, "") else data.get("priceWithoutEhf"))
    regular = parse_price(data.get("regularPrice"))
    price = sale or regular
    if price is None:
        return None
    avail = data.get("availability") or {}
    in_stock = None
    if isinstance(avail, dict):
        if "isAvailableOnline" in avail:
            in_stock = bool(avail.get("isAvailableOnline"))
        elif "onlineAvailability" in avail:
            in_stock = str(avail.get("onlineAvailability")).lower() in ("instock", "in stock", "limited")
    seller = data.get("seller") or {}
    seller_name = seller.get("name") if isinstance(seller, dict) else None
    return ParsedProduct(
        name=data.get("name"), brand=data.get("brandName"), mpn=data.get("modelNumber"), gtin=data.get("upc"),
        sku=str(data.get("sku") or sku_from_url(url) or "") or None, image=data.get("thumbnailImage"), url=url,
        price_cents=price, was_price_cents=regular if regular and regular > price else None, currency="CAD",
        in_stock=in_stock, seller=seller_name or "Best Buy", condition="new", source="bestbuy_api")
