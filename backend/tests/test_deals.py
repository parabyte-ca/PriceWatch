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
    async def no_pictures(db, found, limit=4):
        return 0

    monkeypatch.setattr(deals, "thread_images", no_pictures)
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


def test_health_check(client, db_session):
    client.post("/api/items", json={"name": "LEGO Titanic"})
    r = client.get("/api/admin/health").json()
    assert r["ok"] is False and any("no price yet" in i for i in r["issues"])
    assert "LEGO Titanic" in r["items_without_price"]
    from pricewatch.services import health

    assert health.summary_line(db_session).startswith("Health: ")


def test_deal_score_history_and_thread_picture(client, db_session, monkeypatch):
    from pricewatch.fetch.http import FetchResult
    from pricewatch.models import CategoryDeal
    from pricewatch.services import runtime

    assert deals.score(discount_pct=40, price_cents=1000, low_cents=1000, sightings=3, trusted_store=True,
                       source="google_shopping", age_hours=2) > deals.score(
        discount_pct=40, price_cents=1200, low_cents=1000, sightings=3, trusted_store=False, source="google_shopping",
        age_hours=100)
    cat = client.post("/api/deal-categories", json={"name": "TVs"}).json()
    url = "https://forums.redflagdeals.com/tv-1"
    for p in (59999, 49999):
        deals.record_sighting(db_session, url, p)
    d = CategoryDeal(category_id=cat["id"], title="[Best Buy] 65\" TV", url=url, price_cents=49999, source="rfd")
    db_session.add(d)
    db_session.commit()
    h = client.get(f"/api/category-deals/{d.id}/history").json()
    assert h["low_cents"] == 49999 and h["count"] == 2 and h["verdict"].startswith("Lowest price seen")

    class F:
        async def fetch(self, url, **kw):
            return FetchResult(url=url, outcome="ok", status_code=200,
                               html='<meta property="og:image" content="https://img.rfd/x.jpg">')

    monkeypatch.setattr(runtime, "get_fetcher", lambda: F())
    import asyncio

    assert asyncio.run(deals.thread_images(db_session, [d])) == 1
    db_session.refresh(d)
    assert d.image_url == "https://img.rfd/x.jpg"


def test_gift_claims_hidden_from_the_list_owner(client, db_session):
    from pricewatch.models import Item, User, WishList
    from pricewatch.services import users

    item = client.post("/api/items", json={"name": "LEGO Titanic"}).json()
    # the admin owns the list: claims are hidden from them, and they cannot claim on their own list
    assert client.post(f"/api/items/{item['id']}/claim").status_code == 409
    lst = db_session.get(WishList, db_session.get(Item, item["id"]).list_id)
    r = client.post(f"/api/lists/{lst.id}/share", json={})
    token = r.json()["share_link"].rsplit("/", 1)[-1]
    shared = client.get(f"/api/shared/{token}").json()["items"][0]
    assert shared["claimed"] is False
    c = client.post(f"/api/shared/{token}/items/{shared['id']}/claim", json={"name": "Aunt Sue"})
    assert c.status_code == 200
    assert client.post(f"/api/shared/{token}/items/{shared['id']}/claim", json={"name": "Bob"}).status_code == 409
    assert client.get(f"/api/shared/{token}").json()["items"][0]["claimed_by"] == "Aunt Sue"
    assert client.get(f"/api/items/{item['id']}").json()["claimed_by"] is None  # the owner does not see it
    assert client.delete(f"/api/shared/{token}/items/{shared['id']}/claim", params={"code": "wrong"}).status_code == 403
    undo = client.delete(f"/api/shared/{token}/items/{shared['id']}/claim", params={"code": c.json()["code"]})
    assert undo.status_code == 204
    _ = (User, users)


def test_item_photo_upload(client):
    import base64

    item = client.post("/api/items", json={"name": "Mixer"}).json()
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 200
    r = client.post(f"/api/items/{item['id']}/photo", json={"image_b64": base64.b64encode(png).decode()}).json()
    assert r["image_url"].startswith("/api/photos/") and client.get(r["image_url"]).content == png
    bad = client.post(f"/api/items/{item['id']}/photo", json={"image_b64": base64.b64encode(b"x" * 200).decode()})
    assert bad.status_code == 422
    assert client.get("/api/photos/evil.txt").status_code == 404
