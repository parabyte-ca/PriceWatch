import pytest

from pricewatch.services.querytext import tidy


@pytest.mark.parametrize("raw,want", [
    ("Grand Theft Auto VI Pre-Order (Xbox Digital Code): Standard $96.50, Ultimate $122", "Grand Theft Auto VI Xbox"),
    ("[Best Buy] Sony WH-1000XM6 $399.99 (Reg $549)", "Sony WH-1000XM6"),
    ("[Costco] Hisense 75\" U8 Mini-LED TV - $1,299.99 YMMV", "Hisense 75\" U8 Mini-LED TV"),
    ("Ninja AF101 Air Fryer 40% off, now $89 free shipping", "Ninja AF101 Air Fryer"),
    ("[Amazon] Bambu Lab A1 Mini 3D printer w/ code SAVE20", "Bambu Lab A1 Mini 3D printer"),
    ("Nintendo Switch 2", "Nintendo Switch 2"),
    ("LEGO Titanic 10294", "LEGO Titanic 10294"),
    ("Apple iPhone 16 Pro: 256GB", "Apple iPhone 16 Pro: 256GB"),  # no price after the colon: kept
])
def test_tidy(raw, want):
    assert tidy(raw) == want


def test_find_uses_tidy_terms(client, monkeypatch):
    from pricewatch.api import find

    product, _ = __import__("asyncio").run(find._resolve(None, "[Walmart] Instant Pot Duo 7-in-1 $59.97 (Reg $129.97)"))
    assert product["name"] == "Instant Pot Duo 7-in-1"


def test_existing_item_searches_tidy_terms():
    from pricewatch.models import Item
    from pricewatch.services.discovery import build_query
    from pricewatch.services.matching import ItemSpec

    it = Item(name="Grand Theft Auto VI Pre-Order (Xbox Digital Code): Standard $96.50, Ultimate $122")
    assert build_query(it) == "Grand Theft Auto VI Xbox"
    assert ItemSpec.from_item(it).name == "Grand Theft Auto VI Xbox"
    it.search_query = "GTA 6 Xbox Series X"
    assert build_query(it) == "GTA 6 Xbox Series X"  # your own search words always win
