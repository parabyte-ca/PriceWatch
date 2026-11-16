"""Generic adapter: JSON-LD Product/Offer, then microdata, then OpenGraph; CSS overrides win."""

import json
import re
from typing import Any

from bs4 import BeautifulSoup

from .base import (
    ParsedProduct,
    RetailerConfig,
    parse_availability,
    parse_condition,
    parse_price,
)

_WAS_TYPES = ("strikethroughprice", "listprice", "msrp", "suggestedretailprice")


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _types(node: dict) -> set[str]:
    return {str(t).rsplit("/", 1)[-1].lower() for t in _as_list(node.get("@type"))}


def _text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return _text(value.get("name") or value.get("@id"))
    if isinstance(value, list):
        return _text(value[0]) if value else None
    s = str(value).strip()
    return s or None


def _image(value) -> str | None:
    if isinstance(value, list):
        return _image(value[0]) if value else None
    if isinstance(value, dict):
        return _text(value.get("url") or value.get("contentUrl"))
    return _text(value)


def _load_jsonld_blocks(soup: BeautifulSoup) -> list[Any]:
    blocks = []
    for tag in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = tag.string or tag.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            blocks.append(json.loads(raw))
        except json.JSONDecodeError:
            # some sites emit trailing commas or several objects; try a lenient cleanup
            cleaned = re.sub(r",\s*([}\]])", r"\1", raw)
            try:
                blocks.append(json.loads(cleaned))
            except json.JSONDecodeError:
                continue
    return blocks


def _walk(node, out: list[dict]) -> None:
    if isinstance(node, list):
        for n in node:
            _walk(n, out)
    elif isinstance(node, dict):
        out.append(node)
        for key in ("@graph", "mainEntity", "itemListElement", "item", "hasVariant"):
            if key in node:
                _walk(node[key], out)


def _offer_price(offer: dict) -> tuple[int | None, int | None]:
    """Return (price, was_price) in cents from one Offer or AggregateOffer."""
    price = parse_price(offer.get("price"))
    if price is None:
        price = parse_price(offer.get("lowPrice"))
    was = None
    for spec in _as_list(offer.get("priceSpecification")):
        if not isinstance(spec, dict):
            continue
        spec_price = parse_price(spec.get("price"))
        ptype = str(spec.get("priceType", "")).lower().rsplit("/", 1)[-1]
        if ptype in _WAS_TYPES:
            was = spec_price
        elif price is None:
            price = spec_price
    return price, was


def parse_jsonld(soup: BeautifulSoup) -> ParsedProduct | None:
    nodes: list[dict] = []
    for block in _load_jsonld_blocks(soup):
        _walk(block, nodes)
    products = [n for n in nodes if _types(n) & {"product", "productgroup", "individualproduct"}]
    for prod in products:
        offers: list[dict] = []
        for off in _as_list(prod.get("offers")):
            if not isinstance(off, dict):
                continue
            subs = [o for o in _as_list(off.get("offers")) if isinstance(o, dict)]
            # prefer concrete offers over the AggregateOffer summary when both exist
            offers.extend(subs if any(_offer_price(o)[0] for o in subs) else [off])
        if not offers:
            for variant in _as_list(prod.get("hasVariant")):
                if isinstance(variant, dict):
                    offers.extend(o for o in _as_list(variant.get("offers")) if isinstance(o, dict))
        best: tuple[int, int | None, dict] | None = None
        best_key: tuple[int, int] | None = None
        for off in offers:
            price, was = _offer_price(off)
            if price is None or price <= 0:
                continue
            # lowest in-stock (or unknown stock) offer first, then lowest out-of-stock offer
            key = (1 if parse_availability(off.get("availability")) is False else 0, price)
            if best_key is None or key < best_key:
                best, best_key = (price, was, off), key
        result = ParsedProduct(
            name=_text(prod.get("name")),
            brand=_text(prod.get("brand")),
            mpn=_text(prod.get("mpn")),
            gtin=_text(
                prod.get("gtin13") or prod.get("gtin12") or prod.get("gtin14") or prod.get("gtin")
                or prod.get("gtin8")
            ),
            sku=_text(prod.get("sku")),
            image=_image(prod.get("image")),
            url=_text(prod.get("url")),
            source="jsonld",
        )
        if best:
            price, was, off = best
            result.price_cents = price
            result.was_price_cents = was if was and was > price else None
            result.currency = _text(off.get("priceCurrency")) or _text(
                next(
                    (s.get("priceCurrency") for s in _as_list(off.get("priceSpecification"))
                     if isinstance(s, dict)),
                    None,
                )
            )
            result.in_stock = parse_availability(off.get("availability"))
            result.seller = _text(off.get("seller"))
            result.condition = parse_condition(off.get("itemCondition") or prod.get("itemCondition"))
            ship = off.get("shippingDetails")
            for detail in _as_list(ship):
                if isinstance(detail, dict) and isinstance(detail.get("shippingRate"), dict):
                    result.shipping_cents = parse_price(detail["shippingRate"].get("value"))
                    break
        if result.name or result.has_price:
            return result
    return None


def parse_microdata(soup: BeautifulSoup) -> ParsedProduct | None:
    price_el = soup.find(attrs={"itemprop": "price"})
    if not price_el:
        return None
    price = parse_price(price_el.get("content") or price_el.get_text())
    if price is None:
        return None
    cur_el = soup.find(attrs={"itemprop": "priceCurrency"})
    avail_el = soup.find(attrs={"itemprop": "availability"})
    name_el = soup.find(attrs={"itemprop": "name"})
    return ParsedProduct(
        name=(name_el.get("content") or name_el.get_text(strip=True)) if name_el else None,
        price_cents=price,
        currency=(cur_el.get("content") or cur_el.get_text(strip=True)) if cur_el else None,
        in_stock=parse_availability(avail_el.get("href") or avail_el.get("content")) if avail_el else None,
        source="microdata",
    )


def _meta(soup: BeautifulSoup, *names: str) -> str | None:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


def _iter_dicts(node, depth=0):
    if depth > 40:
        return
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _iter_dicts(v, depth + 1)
    elif isinstance(node, list):
        for v in node[:500]:
            yield from _iter_dicts(v, depth + 1)


def _num_price(obj) -> int | None:
    if isinstance(obj, dict):
        for k in ("price", "amount", "value"):
            if isinstance(obj.get(k), int | float) and not isinstance(obj.get(k), bool):
                return parse_price(obj[k])
        if isinstance(obj.get("priceString"), str):
            return parse_price(obj["priceString"])
    return None


def parse_embedded_json(soup) -> ParsedProduct | None:
    """Product data that script-built pages embed as JSON (Next.js ``__NEXT_DATA__`` and similar).

    Looks for a product object with ``priceInfo.currentPrice`` (the shape Walmart Canada uses). Conservative: a
    price in another currency is ignored, and only the first product with a price counts.
    """
    scripts = soup.find_all("script", attrs={"id": "__NEXT_DATA__"}) + \
        soup.find_all("script", attrs={"type": "application/json"})
    for tag in scripts[:20]:
        raw = tag.string or tag.get_text() or ""
        if "priceInfo" not in raw or len(raw) > 5_000_000:
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        for node in _iter_dicts(data):
            info = node.get("priceInfo")
            if not isinstance(info, dict):
                continue
            current = info.get("currentPrice") or info.get("linePrice")
            price = _num_price(current)
            if price is None:
                continue
            currency = (current or {}).get("currencyUnit") or (current or {}).get("currency")
            if currency and str(currency).upper() not in ("CAD", "CA$"):
                continue
            was = _num_price(info.get("wasPrice")) or _num_price(info.get("listPrice"))
            status = str(node.get("availabilityStatus") or "").upper()
            in_stock = True if status in ("IN_STOCK", "AVAILABLE") else False if status in ("OUT_OF_STOCK",) else None
            seller_obj = node.get("seller")
            seller = node.get("sellerName") or (seller_obj.get("name") if isinstance(seller_obj, dict) else None)
            brand = node.get("brand") if isinstance(node.get("brand"), str) else None
            return ParsedProduct(name=node.get("name"), brand=brand,
                                 sku=str(node.get("usItemId") or node.get("id") or "") or None, image=None,
                                 price_cents=price, was_price_cents=was if was and was > price else None, currency="CAD",
                                 in_stock=in_stock, seller=seller, source="embedded_json")
    return None


def parse_opengraph(soup: BeautifulSoup) -> ParsedProduct:
    return ParsedProduct(
        name=_meta(soup, "og:title", "twitter:title"),
        image=_meta(soup, "og:image", "twitter:image"),
        url=_meta(soup, "og:url"),
        brand=_meta(soup, "product:brand", "og:brand"),
        price_cents=parse_price(_meta(soup, "product:price:amount", "og:price:amount")),
        currency=_meta(soup, "product:price:currency", "og:price:currency"),
        in_stock=parse_availability(_meta(soup, "product:availability", "og:availability")),
        source="opengraph",
    )


def parse_css(soup: BeautifulSoup, selectors: dict) -> ParsedProduct:
    def pick(key: str) -> str | None:
        sel = selectors.get(key)
        if not sel:
            return None
        el = soup.select_one(sel)
        if not el:
            return None
        return (el.get("content") or el.get("src") or el.get_text(" ", strip=True)) or None

    return ParsedProduct(
        name=pick("name"),
        image=pick("image"),
        price_cents=parse_price(pick("price")),
        was_price_cents=parse_price(pick("was_price")),
        in_stock=parse_availability(pick("availability")),
        source="css",
    )


def _merge(primary: ParsedProduct, fallback: ParsedProduct | None) -> ParsedProduct:
    if fallback is None:
        return primary
    for key, value in vars(fallback).items():
        if key in ("source", "extra"):
            continue
        if getattr(primary, key) in (None, "") and value not in (None, ""):
            setattr(primary, key, value)
    return primary


class GenericAdapter:
    name = "generic"

    def parse(self, html: str, url: str, retailer: RetailerConfig | None = None) -> ParsedProduct | None:  # noqa: C901
        soup = BeautifulSoup(html, "lxml")
        retailer = retailer or RetailerConfig()
        candidates: list[ParsedProduct] = []
        if retailer.selectors:
            css = parse_css(soup, retailer.selectors)
            if css.has_price or css.name:
                candidates.append(css)
        for fn in (parse_jsonld, parse_microdata, parse_embedded_json):
            parsed = fn(soup)
            if parsed:
                candidates.append(parsed)
        candidates.append(parse_opengraph(soup))
        priced = [c for c in candidates if c.has_price]
        result = priced[0] if priced else candidates[0]
        for other in candidates:
            if other is not result:
                _merge(result, other)
        if not result.name:
            title = soup.find("title")
            result.name = title.get_text(strip=True) if title else None
        if not result.url:
            result.url = url
        if not result.has_price and not result.name:
            return None
        return result
