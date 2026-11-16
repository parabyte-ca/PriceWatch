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
    return p


def test_discover_suggests_matches_and_remembers_rejections(client, fake):
    client.patch("/api/settings", json={"auto_confirm_strong": False})  # everything waits for a person here
    item = client.post("/api/items", json={"name": "Sony WH-1000XM6 Wireless Headphones Black", "brand": "Sony",
                                           "model": "WH1000XM6/B"}).json()
    r = client.post(f"/api/items/{item['id']}/discover", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["query"] == "Sony WH-1000XM6 Wireless Headphones Black WH1000XM6/B"
    statuses = {c["url"]: c["status"] for c in body["candidates"]}
    assert statuses["https://www.bestbuy.ca/en-ca/product/sony-wh-1000xm6/18930123"] == "suggested"
    assert statuses["https://www.staples.ca/products/2988123-en-sony-wh1000xm6"] == "suggested"
    assert statuses["https://www.ebay.ca/itm/123"] == "excluded"
    assert statuses["https://www.walmart.ca/en/ip/sony-xm5/1"] == "low match"
    assert statuses["https://www.google.ca/shopping/product/111"] == "no merchant link"
    assert statuses["https://www.amazon.ca/dp/B0CASE1234"] == "low match"
    assert body["added"] == 2

    detail = client.get(f"/api/items/{item['id']}").json()
    suggested = [s for s in detail["sources"] if s["status"] == "suggested"]
    assert len(suggested) == 2
    assert suggested[0]["match_reasons"]["serp_price_cents"] in (44999, 42999)
    assert detail["summary"]["suggested_count"] == 2
    assert detail["summary"]["best_price_cents"] is None  # suggestions never count as prices

    # reject one, confirm the other
    bb = next(s for s in suggested if "bestbuy" in s["url"])
    st = next(s for s in suggested if "staples" in s["url"])
    client.patch(f"/api/sources/{bb['id']}", json={"status": "rejected"})
    client.patch(f"/api/sources/{st['id']}", json={"status": "confirmed"})

    # second run: cached (no new billable search) and the rejection is remembered
    body2 = client.post(f"/api/items/{item['id']}/discover", json={}).json()
    assert body2["cached"] is True and fake.calls == 1
    statuses2 = {c["url"]: c["status"] for c in body2["candidates"]}
    assert statuses2[bb["url"]] == "already rejected"
    assert statuses2[st["url"]] == "already confirmed"
    assert body2["added"] == 0

    # force: billable again
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


def test_strong_matches_are_tracked_at_once(client, fake):
    item = client.post("/api/items", json={"name": "Sony WH-1000XM6 Wireless Headphones Black", "brand": "Sony",
                                           "model": "WH1000XM6/B"}).json()
    body = client.post(f"/api/items/{item['id']}/discover", json={}).json()
    st = {c["url"]: c for c in body["candidates"]}
    bb = st["https://www.bestbuy.ca/en-ca/product/sony-wh-1000xm6/18930123"]
    assert bb["status"] == "confirmed" and bb["method"] in ("mpn", "model", "gtin")
    fuzzy = [c for c in body["candidates"] if c["status"] == "suggested"]
    assert all(c["method"] == "fuzzy" for c in fuzzy)
    src = next(s for s in client.get(f"/api/items/{item['id']}").json()["sources"] if s["url"] == bb["url"])
    assert src["next_check_at"] is not None  # first price check queued


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
    statuses = {c["url"]: c["status"] for c in body["candidates"]}
    assert statuses["https://www.bestbuy.ca/en-ca/product/nintendo-switch-2/19000001"] in ("suggested", "confirmed")
    assert statuses["https://www.walmart.ca/en/ip/nintendo-switch-2/6000201"] in ("suggested", "confirmed")
    assert seen.count("google_immersive_product") == 1  # only the matching product's store list was opened
    assert all("token" not in c for c in body["candidates"])


def test_prices_across_stores_snapshot_best_price_and_alert(client, db_session, monkeypatch):
    from pricewatch.models import Alert
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
    assert body["market"] == {"stores": 2, "best_cents": 62999}
    offers = client.get(f"/api/items/{item['id']}/offers").json()
    assert [(o["merchant"], o["price_cents"], o["store_link"]) for o in offers] == [
        ("Best Buy", 62999, True), ("Walmart", 64999, False)]  # one per store, lowest; refurbished left out
    assert offers[0]["tracked"] in ("suggested", "confirmed")
    m = client.get(f"/api/items/{item['id']}").json()["summary"]["market"]
    assert m["best"]["merchant"] == "Best Buy" and m["stores"] == 2
    assert db_session.query(Alert).filter_by(rule_type="market_target").count() == 1
    client.post(f"/api/items/{item['id']}/discover", json={})  # same price again: no second alert
    assert db_session.query(Alert).filter_by(rule_type="market_target").count() == 1
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
