import json

import httpx
import pytest

from pricewatch.serp.serpapi import SerpApiProvider
from pricewatch.services import discovery

from .conftest import FIXTURES

SERP_JSON = json.loads((FIXTURES / "serp" / "serpapi_shopping.json").read_text())


async def test_serpapi_parsing_and_params():
    seen = {}

    def handler(req):
        seen.update(dict(req.url.params))
        return httpx.Response(200, json=SERP_JSON)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        cands = await SerpApiProvider("k").search("Sony WH-1000XM6", client)
    assert seen["gl"] == "ca" and seen["engine"] == "google_shopping"
    assert len(cands) == 6
    assert cands[0].price_cents == 44999 and cands[0].shipping_cents == 0
    assert cands[1].shipping_cents == 999
    assert cands[2].condition == "refurbished"


class FakeProvider:
    name = "serpapi"

    def __init__(self):
        self.calls = 0

    async def search(self, query, client):
        self.calls += 1
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=SERP_JSON))) as c:
            return await SerpApiProvider("k").search(query, c)


@pytest.fixture
def fake(monkeypatch):
    p = FakeProvider()
    monkeypatch.setattr(discovery, "get_provider", lambda name=None: p)
    import pricewatch.api.find as find_api

    monkeypatch.setattr(find_api, "get_provider", lambda name=None: p)
    return p


def test_every_known_store_is_tracked_with_its_search_price(client, fake):
    item = client.post("/api/items", json={"name": "Sony WH-1000XM6 Wireless Headphones Black", "brand": "Sony",
                                           "model": "WH1000XM6/B"}).json()
    body = client.post(f"/api/items/{item['id']}/discover", json={}).json()
    assert body["query"] == "Sony WH-1000XM6 Wireless Headphones Black WH1000XM6/B"
    st = {c["url"]: c for c in body["candidates"]}
    assert st["https://www.ebay.ca/itm/123"]["status"] == "excluded"  # refurbished
    assert st["https://www.walmart.ca/en/ip/sony-xm5/1"]["status"] == "low match"  # the older model
    assert st["https://www.amazon.ca/dp/B0CASE1234"]["status"] == "low match"  # a case
    assert body["added"] == 2 and body["market"]["stores"] == 2

    detail = client.get(f"/api/items/{item['id']}").json()
    tracked = {s["retailer_name"]: s for s in detail["sources"]}
    assert set(tracked) == {"Best Buy Canada", "Staples Canada"}
    assert all(s["status"] == "confirmed" for s in tracked.values())
    assert tracked["Staples Canada"]["last_price_cents"] == 42999 and tracked["Staples Canada"]["last_method"] == "search"
    assert detail["summary"]["best_price_cents"] == 42999  # search prices count: the comparison is the point
    offers = client.get(f"/api/items/{item['id']}/offers").json()
    assert [o["merchant"] for o in offers if o["kind"] == "store"] == ["Staples", "Best Buy Canada"]
    assert any(o["kind"] == "other" for o in offers)  # "Some Store": not a known Canadian store, shown but not tracked

    # hiding a store is remembered; a second run uses the cache (no new paid search) and adds nothing
    client.patch(f"/api/sources/{tracked['Best Buy Canada']['id']}", json={"status": "rejected"})
    body2 = client.post(f"/api/items/{item['id']}/discover", json={}).json()
    assert body2["cached"] is True and fake.calls == 1 and body2["added"] == 0
    sources = client.get(f"/api/items/{item['id']}").json()["sources"]
    assert next(s for s in sources if s["id"] == tracked["Best Buy Canada"]["id"])["status"] == "rejected"
    client.post(f"/api/items/{item['id']}/discover", json={"force": True})
    assert fake.calls == 2
    assert client.get("/api/discovery/providers").status_code == 200


def test_monthly_limit(client, fake):
    client.patch("/api/settings", json={"serp_monthly_limit": 1})
    item = client.post("/api/items", json={"name": "Sony WH-1000XM6", "brand": "Sony"}).json()
    assert client.post(f"/api/items/{item['id']}/discover", json={}).status_code == 200
    r = client.post(f"/api/items/{item['id']}/discover", json={"force": True})
    assert r.status_code == 409 and "limit" in r.json()["detail"]


def test_no_provider(client, monkeypatch):
    monkeypatch.setattr(discovery, "get_provider", lambda name=None: None)
    item = client.post("/api/items", json={"name": "X"}).json()
    r = client.post(f"/api/items/{item['id']}/discover", json={})
    assert r.status_code == 409 and "SERPAPI_KEY" in r.json()["detail"]


def test_settings_numeric_validation(client):
    assert client.patch("/api/settings", json={"match_threshold": 20}).status_code == 422
    assert client.patch("/api/settings", json={"match_threshold": 90}).json()["match_threshold"] == 90


GOOGLE_ONLY = {"shopping_results": [
    {"title": "Nintendo Switch 2 System", "product_link": "https://www.google.ca/shopping/product/111",
     "immersive_product_page_token": "tok-111", "source": "Walmart.ca", "extracted_price": 679.95},
    {"title": "Nintendo Switch 2 Dock Set", "product_link": "https://www.google.ca/shopping/product/222",
     "immersive_product_page_token": "tok-222", "source": "Nintendo", "extracted_price": 154.99},
]}
STORES = {"product_results": {"title": "Nintendo Switch 2 System", "stores": [
    {"name": "Best Buy", "link": "https://www.bestbuy.ca/en-ca/product/nintendo-switch-2/19000001",
     "extracted_price": 649.99},
    {"name": "Walmart", "link": "https://www.walmart.ca/en/ip/nintendo-switch-2/6000201", "extracted_price": 679.95},
]}}


def test_google_only_results_open_the_store_list(client, monkeypatch):
    seen = []

    def handler(req):
        seen.append(req.url.params["engine"])
        return httpx.Response(200, json=GOOGLE_ONLY if req.url.params["engine"] == "google_shopping" else STORES)

    real = SerpApiProvider("k")

    class P:
        name = "serpapi"

        async def search(self, query, client):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
                return await real.search(query, c)

        async def expand(self, token, client):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
                return await real.expand(token, c)

    monkeypatch.setattr(discovery, "get_provider", lambda name=None: P() if name in (None, "serpapi") else None)
    item = client.post("/api/items", json={"name": "Nintendo Switch 2 System"}).json()
    body = client.post(f"/api/items/{item['id']}/discover", json={}).json()
    srcs = {s["retailer_name"]: s for s in client.get(f"/api/items/{item['id']}").json()["sources"]}
    assert srcs["Best Buy Canada"]["url"] == "https://www.bestbuy.ca/en-ca/product/nintendo-switch-2/19000001"
    assert srcs["Walmart Canada"]["url"] == "https://www.walmart.ca/en/ip/nintendo-switch-2/6000201"  # store page
    assert srcs["Walmart Canada"]["fetch_mode"] == "search"  # Walmart blocks visits: prices from searches
    assert seen.count("google_immersive_product") == 1  # only the matching product's store list was opened
    assert all("token" not in c for c in body["candidates"])


def test_prices_across_stores_snapshot_and_best_price(client, db_session, monkeypatch):
    from pricewatch.services.discovery import merchant_key

    rows = {"shopping_results": [
        {"title": "Nintendo Switch 2 System", "product_link": "https://www.google.ca/shopping/product/1",
         "source": "Walmart.ca", "extracted_price": 679.95},
        {"title": "Nintendo Switch 2 System", "product_link": "https://www.google.ca/shopping/product/2",
         "source": "Walmart", "extracted_price": 649.99},
        {"title": "Nintendo Switch 2 System", "link": "https://www.bestbuy.ca/en-ca/product/switch-2/19000001",
         "source": "Best Buy", "extracted_price": 629.99, "delivery": "Free delivery"},
        {"title": "Nintendo Switch 2 System (Refurbished)", "link": "https://www.ebay.ca/itm/9",
         "source": "eBay", "extracted_price": 399.99, "second_hand_condition": "refurbished"},
    ]}

    class P:
        name = "serpapi"

        async def search(self, query, client):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=rows))) as c:
                return await SerpApiProvider("k").search(query, c)

    monkeypatch.setattr(discovery, "get_provider", lambda name=None: P() if name in (None, "serpapi") else None)
    item = client.post("/api/items", json={"name": "Nintendo Switch 2 System", "target_price_cents": 64999}).json()
    body = client.post(f"/api/items/{item['id']}/discover", json={}).json()
    assert body["market"]["stores"] == 2 and body["market"]["best_cents"] == 62999
    offers = client.get(f"/api/items/{item['id']}/offers").json()
    assert [(o["merchant"], o["price_cents"], o["store_link"]) for o in offers] == [
        ("Best Buy", 62999, True), ("Walmart", 64999, False)]  # one per store, lowest; refurbished left out
    assert offers[0]["tracked"] == "confirmed"
    m = client.get(f"/api/items/{item['id']}").json()["summary"]["market"]
    assert m["best"]["merchant"] == "Best Buy" and m["stores"] == 2
    assert client.get(f"/api/items/{item['id']}").json()["summary"]["best_price_cents"] == 62999
    assert merchant_key("Walmart.ca") == merchant_key("walmart") == merchant_key("Walmart Canada")


def test_daily_refresh_is_paced_to_the_monthly_limit(client, db_session, monkeypatch):
    from datetime import datetime

    from pricewatch.models import SerpSearch

    class P:
        name = "serpapi"
        calls = 0

        async def search(self, query, client):
            P.calls += 1
            return []

    monkeypatch.setattr(discovery, "get_provider", lambda name=None: P() if name in (None, "serpapi") else None)
    monkeypatch.setattr(discovery, "utcnow", lambda: datetime(2026, 11, 3, 12, 0))
    client.patch("/api/settings", json={"serp_monthly_limit": 30})
    for n in range(3):
        client.post("/api/items", json={"name": f"Thing {n}"})
    for _ in range(3):  # day 3 of 30 with a limit of 30: 3 searches so far is the pace
        db_session.add(SerpSearch(provider="serpapi", query="x", created_at=datetime(2026, 11, 2)))
    db_session.commit()
    import asyncio

    assert asyncio.run(discovery.refresh_stale(db_session, per_run=3)) == 0 and P.calls == 0
    client.patch("/api/settings", json={"serp_monthly_limit": 300})
    assert asyncio.run(discovery.refresh_stale(db_session, per_run=3)) == 3


def test_find_compares_then_watch_tracks_every_store_without_a_second_search(client, fake):
    r = client.post("/api/find", json={"q": "Sony WH-1000XM6 Wireless Headphones Black"}).json()
    assert r["provider"] == "serpapi" and fake.calls == 1
    stores = [o for o in r["offers"] if o["kind"] == "store"]
    assert [o["merchant"] for o in stores][:2] == ["Staples", "Best Buy Canada"]
    assert r["best"]["price_cents"] == 42999 and r["best"]["landed_cents"] > 42999  # with tax
    assert r["suggested_target_cents"] == 38599
    w = client.post("/api/watch", json={"name": r["product"]["name"], "query": r["query"],
                                        "target_price_cents": r["suggested_target_cents"]})
    assert w.status_code == 201, w.text
    item = w.json()["item"]
    assert fake.calls == 1  # the comparison's search was reused
    assert {s["retailer_name"] for s in item["sources"]} == {"Best Buy Canada", "Staples Canada"}
    assert item["summary"]["best_price_cents"] == 42999


def test_find_barcode_and_no_provider(client, monkeypatch):
    monkeypatch.setattr(discovery, "get_provider", lambda name=None: None)
    import pricewatch.api.find as find_api

    monkeypatch.setattr(find_api, "get_provider", lambda name=None: None)
    r = client.post("/api/find", json={"q": "LEGO Titanic"}).json()
    assert r["offers"] == [] and "SerpApi" in r["notes"][0]
    w = client.post("/api/watch", json={"name": "LEGO Titanic"}).json()
    assert w["item"]["name"] == "LEGO Titanic"


def test_not_this_product_and_only_this_store(client, fake):
    item = client.post("/api/items", json={"name": "Sony WH-1000XM6 Wireless Headphones Black", "brand": "Sony",
                                           "model": "WH1000XM6/B"}).json()
    client.post(f"/api/items/{item['id']}/discover", json={})
    srcs = {s["retailer_name"]: s for s in client.get(f"/api/items/{item['id']}").json()["sources"]}
    staples = srcs["Staples Canada"]
    r = client.post("/api/feedback/not-this-product", json={"url": staples["url"], "item_id": item["id"]})
    assert r.status_code == 204
    client.post(f"/api/items/{item['id']}/discover", json={"force": True})  # the listing is skipped from now on
    after = {s["retailer_name"]: s for s in client.get(f"/api/items/{item['id']}").json()["sources"]}
    assert after["Staples Canada"]["status"] == "rejected"
    assert all(o["url"] != staples["url"] for o in client.get(f"/api/items/{item['id']}/offers").json())
    client.post(f"/api/sources/{after['Staples Canada']['id']}/only")
    final = {s["retailer_name"]: s["status"] for s in client.get(f"/api/items/{item['id']}").json()["sources"]}
    assert final == {"Staples Canada": "confirmed", "Best Buy Canada": "rejected"}


def test_claude_sorts_bundles_and_accessories_out_of_the_comparison(client, fake, monkeypatch):
    from types import SimpleNamespace as NS

    from pricewatch.services import classify

    class API:
        calls = 0

        @property
        def messages(self):
            return self

        async def parse(self, **kw):
            API.calls += 1
            text = kw["messages"][0]["content"]
            labels = [classify.Label(n=n, label="bundle" if "Staples" in line else "same")
                      for n, line in enumerate(text.split("Listings:\n")[1].splitlines(), 1)]
            return NS(parsed_output=classify.Labels(listings=labels), usage=None)

        async def close(self):
            pass

    monkeypatch.setattr(classify, "available", lambda: True)
    import anthropic

    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **kw: API())
    item = client.post("/api/items", json={"name": "Sony WH-1000XM6 Wireless Headphones Black", "brand": "Sony",
                                           "model": "WH1000XM6/B"}).json()
    client.post(f"/api/items/{item['id']}/discover", json={})
    names = {s["retailer_name"] for s in client.get(f"/api/items/{item['id']}").json()["sources"]}
    assert names == {"Best Buy Canada"}  # the Staples listing was a bundle: shown, not tracked
    offers = client.get(f"/api/items/{item['id']}/offers").json()
    assert next(o for o in offers if o["merchant"] == "Staples")["kind"] == "bundle"
    client.post(f"/api/items/{item['id']}/discover", json={"force": True})
    assert API.calls == 1  # labels are cached per title


def test_find_stream_sends_stages(client, fake):
    with client.stream("GET", "/api/find/stream", params={"q": "Sony WH-1000XM6 Wireless Headphones Black"}) as r:
        body = "".join(r.iter_text())
    names = [line.split(": ", 1)[1] for line in body.splitlines() if line.startswith("event: ")]
    assert names[0] == "product" and names[-1] == "done" and "search" in names
    import json

    done = json.loads(body.split("event: done\ndata: ")[1].split("\n")[0])
    assert done["best"]["price_cents"] == 42999
