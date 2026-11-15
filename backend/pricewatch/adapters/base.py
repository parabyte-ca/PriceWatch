"""Adapter interface: turn a product page into a ParsedProduct."""

import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Protocol


@dataclass
class ParsedProduct:
    name: str | None = None
    brand: str | None = None
    mpn: str | None = None
    gtin: str | None = None
    sku: str | None = None
    image: str | None = None
    url: str | None = None
    price_cents: int | None = None
    was_price_cents: int | None = None
    currency: str | None = None
    in_stock: bool | None = None
    seller: str | None = None
    shipping_cents: int | None = None
    condition: str | None = None
    source: str | None = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def has_price(self) -> bool:
        return self.price_cents is not None


@dataclass
class RetailerConfig:
    domain: str = ""
    selectors: dict | None = None


class Adapter(Protocol):
    name: str

    def parse(self, html: str, url: str, retailer: RetailerConfig) -> ParsedProduct | None: ...


_NUM_RE = re.compile(r"\d[\d\s.,  ]*")


def parse_price(value) -> int | None:
    """Parse a price into cents. Handles 1299.99, "$1,299.99", "1 299,99 $", 1299."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float | Decimal):
        try:
            d = Decimal(str(value))
        except InvalidOperation:
            return None
        return int((d * 100).quantize(Decimal("1"))) if d >= 0 else None
    text = str(value).strip()
    m = _NUM_RE.search(text)
    if not m:
        return None
    num = re.sub(r"[\s  ]", "", m.group(0)).rstrip(".,")
    if "," in num and "." in num:
        # the last separator is the decimal point
        if num.rfind(",") > num.rfind("."):
            num = num.replace(".", "").replace(",", ".")
        else:
            num = num.replace(",", "")
    elif "," in num:
        head, _, tail = num.rpartition(",")
        num = f"{head.replace(',', '')}.{tail}" if len(tail) in (1, 2) else num.replace(",", "")
    elif num.count(".") > 1:
        head, _, tail = num.rpartition(".")
        num = f"{head.replace('.', '')}.{tail}" if len(tail) in (1, 2) else num.replace(".", "")
    try:
        d = Decimal(num)
    except InvalidOperation:
        return None
    return int((d * 100).quantize(Decimal("1")))


IN_STOCK_TOKENS = ("instock", "in_stock", "limitedavailability", "onlineonly", "instoreonly", "presale", "preorder")
OUT_TOKENS = ("outofstock", "out_of_stock", "soldout", "discontinued", "backorder")


def parse_availability(value) -> bool | None:
    if value is None:
        return None
    token = str(value).lower().rsplit("/", 1)[-1].replace(" ", "").replace("-", "")
    if any(t in token for t in OUT_TOKENS):
        return False
    if any(t in token for t in IN_STOCK_TOKENS):
        return True
    return None


CONDITION_MAP = {
    "newcondition": "new",
    "refurbishedcondition": "refurbished",
    "usedcondition": "used",
    "damagedcondition": "used",
}


def parse_condition(value) -> str | None:
    if not value:
        return None
    token = str(value).lower().rsplit("/", 1)[-1]
    return CONDITION_MAP.get(token, token)
