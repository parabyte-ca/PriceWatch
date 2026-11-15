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
