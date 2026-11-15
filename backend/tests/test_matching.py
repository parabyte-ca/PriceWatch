import pytest

from pricewatch.services.matching import (
    Candidate,
    ItemSpec,
    match,
    normalize_gtin,
    normalize_mpn,
    normalize_url,
)

XM6 = ItemSpec(name="Sony WH-1000XM6 Wireless Headphones Black", brand="Sony", model="WH1000XM6/B",
               gtin="4548736158566")
IPAD = ItemSpec(name="Apple iPad Air 11-inch 256GB Blue", brand="Apple")
TV = ItemSpec(name="LG 65\" OLED evo C5 4K TV", brand="LG")


def c(title, url="https://www.bestbuy.ca/p/1", **kw):
    return Candidate(title=title, url=url, **kw)


def test_gtin_normalisation():
    assert normalize_gtin("4548736158566") == "04548736158566"
    assert normalize_gtin("885911425308") == "00885911425308"
    assert normalize_gtin("4548736158563") is None  # bad check digit
    assert normalize_gtin("abc") is None


def test_mpn_normalisation():
    assert normalize_mpn("WH-1000XM6/B") == normalize_mpn("wh1000xm6 b") == "WH1000XM6B"


@pytest.mark.parametrize("title,kw,method,accepted", [
    ("Sony headphones", {"gtin": "04548736158566"}, "gtin", True),
    ("Sony headphones", {"gtin": "885911425308"}, "gtin", False),
    ("Sony WH1000XM6/B Over-Ear", {"mpn": "WH-1000XM6/B", "brand": "Sony"}, "mpn", True),
    ("Sony WH-1000XM6/B Noise Cancelling", {}, "mpn", True),
    ("Sony WH-1000XM5/B", {"mpn": "WH1000XM5/B", "brand": "Sony"}, "mpn", False),
    ("Sony WH-1000XM6 Wireless Noise Cancelling Headphones - Black", {}, "model", True),
    ("Sony WH1000XM6 headphones $399.99 YMMV", {}, "model", True),
])
def test_positive_and_negative_identifiers(title, kw, method, accepted):
    spec = XM6 if method != "fuzzy" else ItemSpec(name=XM6.name, brand="Sony")
    r = match(spec, c(title, **kw))
    assert r.method == method
    assert r.accepted is accepted


@pytest.mark.parametrize("title,reason", [
    ("Apple iPad Air 11-inch 256GB Blue (Refurbished)", "refurbished"),
    ("Apple iPad Air 11-inch 256GB Blue - Open Box", "open box"),
    ("Used Apple iPad Air 11-inch 256GB Blue", "used"),
    ("Apple iPad Air 11-inch 256GB Blue Bundle with Case", "bundle"),
    ("Apple iPad Air 11-inch 128GB Blue", "different storage"),
    ("Apple iPad Air 11-inch 256GB Space Grey Purple", "different colour"),
])
def test_exclusions(title, reason):
    r = match(IPAD, c(title))
    assert not r.accepted
    assert any(e.startswith(reason) for e in r.exclusions), r.exclusions


def test_exclusion_toggle_off_allows_refurbished():
    spec = ItemSpec(name=IPAD.name, brand="Apple", exclude_refurbished=False)
    assert match(spec, c("Apple iPad Air 11-inch 256GB Blue Refurbished")).accepted


def test_tv_size_variant():
    assert not match(TV, c("LG 55\" OLED evo C5 4K TV")).accepted
    assert match(TV, c("LG 65 inch OLED evo C5 4K Smart TV")).accepted


def test_marketplace_excluded():
    r = match(IPAD, c("Apple iPad Air 11-inch 256GB Blue", url="https://www.ebay.ca/itm/1", merchant="eBay - seller"))
    assert "marketplace seller" in r.exclusions


def test_accessory_not_matched():
    r = match(IPAD, c("Case for Apple iPad Air 11-inch Blue"))
    assert not r.accepted


def test_brand_mismatch():
    r = match(ItemSpec(name="WH-1000XM6 headphones", brand="Sony"), c("Bose QuietComfort headphones", brand="Bose"))
    assert not r.accepted


def test_normalize_url():
    assert normalize_url("https://WWW.BestBuy.ca/en-ca/product/1?utm_source=x&gclid=y&sku=2#reviews") == \
        "https://www.bestbuy.ca/en-ca/product/1?sku=2"
    assert normalize_url("https://www.google.com/url?url=https://www.staples.ca/p/9%3Futm_medium%3Dz") == \
        "https://www.staples.ca/p/9"


def test_model_conflict_rejects_previous_generation():
    spec = ItemSpec(name="Sony WH-1000XM6 Wireless Headphones Black", brand="Sony")
    r = match(spec, c("Sony WH-1000XM5 Wireless Headphones Black"))
    assert not r.accepted and "different model" in r.reasons[0]
    assert match(spec, c("SONY WH1000XM6 Wireless Headphones, Black")).accepted


def test_model_tokens_ignore_units():
    from pricewatch.services.matching import model_tokens
    assert model_tokens('iPad Air 11-inch 256GB 65" 4K') == set()
    assert model_tokens("LG OLED65C5PUA") == {"OLED65C5PUA"}


def test_accessory_with_model_number_not_matched():
    spec = ItemSpec(name="Sony WH-1000XM6 Wireless Headphones", brand="Sony")
    assert not match(spec, c("Hard Case for Sony WH-1000XM6 Headphones")).accepted
    assert not match(spec, c("Replacement ear pads compatible with Sony WH-1000XM6")).accepted
