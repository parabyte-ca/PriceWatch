"""v1.1.0: today's drops, matching forum threads, and deal categories on Home."""

import asyncio
from datetime import timedelta

import httpx

from pricewatch.serp.serpapi import SerpApiProvider
from pricewatch.services import deals


def test_keyword_match():
    assert deals.keyword_match("TVs", "[Best Buy] Samsung 65\" QLED TV $799")
    assert deals.keyword_match("3D printers", "[Amazon] Bambu Lab A1 Mini 3D Printer $249")
    assert not deals.keyword_match("Kitchen accessories", "[Costco] LG OLED TV")


def test_categories_from_forum_threads_and_on_sale_search(client, db_session, monkeypatch):
    r = client.post("/api/deal-categories", json={"name": "TVs", "min_discount_pct": 20})
    assert r.status_code == 201
    cat_id = r.json()["id"]
    assert client.post("/api/deal-categories", json={"name": "TVs"}).status_code == 409
    added = asyncio.run(deals.match_rfd(db_session, [
        {"title": "[Best Buy] Hisense 65\" 4K TV $499.99", "link": "https://forums.redflagdeals.com/t1"},
        {"title": "[Costco] KitchenAid mixer $299", "link": "https://forums.redflagdeals.com/t2"},
    ]))
    assert added == 1

    rows = {"shopping_results": [
        {"title": "LG 55\" OLED TV", "link": "https://www.bestbuy.ca/lg55", "source": "Best Buy", "extracted_price": 999.99,
         "extracted_old_price": 1499.99},
        {"title": "TCL 43\" TV", "link": "https://www.walmart.ca/tcl", "source": "Walmart", "extracted_price": 279.0,
         "extracted_old_price": 299.0},  # 7% off: under the 20% minimum
    ]}
    seen = {}

    class P(SerpApiProvider):
        async def on_sale(self, query, client):
            async def handler(req):
                seen.update(dict(req.url.params))
                return httpx.Response(200, json=rows)
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
                return await SerpApiProvider.on_sale(self, query, c)

    import pricewatch.serp as serp

    monkeypatch.setattr(serp, "get_provider", lambda name=None: P("k"))
    assert asyncio.run(deals.refresh_categories(db_session)) == 1
    assert seen["tbs"] == "mr:1,sales:1" and seen["q"] == "deals:tvs"
    home = client.get("/api/deals/home").json()
    tv = next(c for c in home["categories"] if c["id"] == cat_id)
    assert [d["source"] for d in tv["deals"]] == ["google_shopping", "rfd"]  # 33% off first
    assert tv["deals"][0]["discount_pct"] == 33
    assert asyncio.run(deals.refresh_categories(db_session)) == 0  # searched today: not due again
    client.post(f"/api/category-deals/{tv['deals'][0]['id']}/dismiss")
    tv = next(c for c in client.get("/api/deals/home").json()["categories"] if c["id"] == cat_id)
    assert len(tv["deals"]) == 1
    assert client.delete(f"/api/deal-categories/{cat_id}").status_code == 204


def test_todays_drops(client, db_session):
    from pricewatch.models import Observation, SourceLink
    from pricewatch.services.retailers import get_or_create_retailer
    from pricewatch.timeutil import utcnow

    item = client.post("/api/items", json={"name": "Nintendo Switch 2"}).json()
    r = get_or_create_retailer(db_session, "https://www.bestbuy.ca/x")
    src = SourceLink(item_id=item["id"], retailer_id=r.id, url="https://www.bestbuy.ca/x", status="confirmed")
    db_session.add(src)
    db_session.flush()
    now = utcnow()
    for days, price in ((5, 69999), (2, 67999), (0, 59999)):
        db_session.add(Observation(item_id=item["id"], source_link_id=src.id, observed_at=now - timedelta(days=days),
                                   price_cents=price, method="search"))
    db_session.commit()
    drops = client.get("/api/deals/home").json()["drops"]
    assert drops[0]["item"] == "Nintendo Switch 2" and drops[0]["was_cents"] == 69999 and drops[0]["drop_pct"] == 14.3
