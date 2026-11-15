import pytest

from pricewatch.adapters.base import RetailerConfig, parse_availability, parse_price
from pricewatch.adapters.generic import GenericAdapter

from .conftest import fixture_html

adapter = GenericAdapter()


@pytest.mark.parametrize("raw,cents", [
    ("449.99", 44999), (449.99, 44999), (1299, 129900), ("$1,299.99", 129999), ("1 299,99 $", 129999),
    ("1.299,99", 129999), ("CA$ 89", 8900), ("Reg. $1,299.99", 129999), ("1,299", 129900),
    ("12,5", 1250), (None, None), ("call for price", None), (True, None),
])
def test_parse_price(raw, cents):
    assert parse_price(raw) == cents


@pytest.mark.parametrize("raw,expected", [
    ("https://schema.org/InStock", True), ("InStock", True), ("in stock", True),
    ("http://schema.org/OutOfStock", False), ("SoldOut", False), ("PreOrder", True), (None, None), ("weird", None),
])
def test_availability(raw, expected):
    assert parse_availability(raw) is expected


def test_jsonld_offer_with_strikethrough():
    p = adapter.parse(fixture_html("jsonld_offer.html"), "https://www.example.ca/xm6")
    assert p.source == "jsonld"
    assert p.name.startswith("Sony WH-1000XM6")
    assert p.brand == "Sony"
    assert p.mpn == "WH1000XM6/B"
    assert p.gtin == "4548736158566"
    assert p.price_cents == 44999
    assert p.was_price_cents == 54999
    assert p.currency == "CAD"
    assert p.in_stock is True
    assert p.condition == "new"
    assert p.seller == "Best Buy"
    assert p.image == "https://images.example.ca/xm6-1.jpg"


def test_jsonld_graph_aggregate_prefers_lowest_in_stock_offer():
    p = adapter.parse(fixture_html("jsonld_graph_aggregate.html"), "https://x.ca/drill")
    assert p.name == "DEWALT 20V MAX Cordless Drill Kit"
    assert p.gtin == "885911425308"
    assert p.price_cents == 14900  # the $129 offer is out of stock
    assert p.in_stock is True
    assert p.shipping_cents == 999
    assert p.image == "https://img.example.ca/drill.jpg"


def test_microdata():
    p = adapter.parse(fixture_html("microdata.html"), "https://x.ca/kb")
    assert p.source == "microdata"
    assert p.price_cents == 13999
    assert p.in_stock is True
    assert p.name == "Keychron K8 Pro Mechanical Keyboard"


def test_opengraph():
    p = adapter.parse(fixture_html("opengraph.html"), "https://x.ca/fryer")
    assert p.price_cents == 12997
    assert p.currency == "CAD"
    assert p.in_stock is True
    assert p.name == "Ninja Air Fryer Max XL"


def test_french_price():
    p = adapter.parse(fixture_html("french_price.html"), "https://x.ca/tv")
    assert p.price_cents == 129999


def test_no_price_returns_title_only():
    p = adapter.parse(fixture_html("no_price.html"), "https://x.ca/blocked")
    assert p is not None and not p.has_price
    assert p.name == "Access check"


def test_css_override_wins():
    cfg = RetailerConfig(domain="shop.ca", selectors={
        "name": "h1.pdp-title", "price": ".price-now", "was_price": ".price-was", "availability": ".stock"})
    p = adapter.parse(fixture_html("css_override.html"), "https://shop.ca/vac", cfg)
    assert p.source == "css"
    assert p.price_cents == 89999
    assert p.was_price_cents == 129999
    assert p.in_stock is True
    assert p.name == "iRobot Roomba Combo j9+"


def test_usd_currency_detected():
    p = adapter.parse(fixture_html("usd_price.html"), "https://x.com/g")
    assert p.currency == "USD"


def test_broken_jsonld_is_tolerated():
    html = '<html><head><script type="application/ld+json">{"@type":"Product","name":"X",' \
           '"offers":{"@type":"Offer","price":"10.00",},}</script></head></html>'
    p = adapter.parse(html, "https://x.ca")
    assert p.price_cents == 1000
