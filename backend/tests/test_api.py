import httpx
import pytest

from pricewatch.fetch.http import PoliteFetcher
from pricewatch.services import alerts, runtime

from .conftest import fixture_html

PAGES = {
    "/xm6": ("jsonld_offer.html", 200),
    "/drill": ("jsonld_graph_aggregate.html", 200),
    "/fryer": ("opengraph.html", 200),
    "/blocked": ("no_price.html", 429),
    "/usd": ("usd_price.html", 200),
}


@pytest.fixture
def pages():
    state = {"overrides": {}}

    def handler(req: httpx.Request):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path in state["overrides"]:
            return httpx.Response(200, text=state["overrides"][req.url.path])
        name, code = PAGES.get(req.url.path, ("no_price.html", 404))
        return httpx.Response(code, text=fixture_html(name))

    runtime.set_fetcher(PoliteFetcher("PriceWatchCA/test", min_interval=0, jitter=0,
                                      transport=httpx.MockTransport(handler)))
    yield state
    runtime.set_fetcher(None)


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(alerts, "send_apprise", lambda urls, t, b: (out.append((t, b)) or True, None))
    return out


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["version"]


def test_preview(client, pages):
    r = client.post("/api/preview", json={"url": "https://www.bestbuy.ca/xm6"})
    body = r.json()
    assert body["retailer"] == "Best Buy Canada"
    assert body["product"]["price_cents"] == 44999


def test_add_by_url_and_target_alert(client, pages, sent):
    client.patch("/api/settings", json={"notify_urls": ["ntfy://ntfy.sh/pw-test"]})
    r = client.post("/api/items/from-url", json={"url": "https://www.bestbuy.ca/xm6"})
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["gtin"] == "4548736158563"
    assert item["summary"]["best_price_cents"] == 44999
    assert item["summary"]["best_landed_cents"] == round(44999 * 1.13)
    assert item["sources"][0]["retailer_name"] == "Best Buy Canada"
    assert item["sources"][0]["price_match"] is True
    assert not sent
    # raise the target above the current price -> immediate BUY NOW alert
    r = client.patch(f"/api/items/{item['id']}", json={"target_price_cents": 45000})
    assert r.json()["summary"]["badge"] == "BUY NOW"
    assert len(sent) == 1 and "BUY NOW" in sent[0][0]
    # same price level again -> de-duplicated
    client.patch(f"/api/items/{item['id']}", json={"target_price_cents": 46000})
    assert len(sent) == 1
    alerts_list = client.get("/api/alerts").json()
    assert alerts_list[0]["rule_type"] == "target" and alerts_list[0]["status"] == "sent"


def test_check_records_history_and_drop_alert(client, pages, sent):
    item = client.post("/api/items/from-url", json={"url": "https://www.canadiantire.ca/drill"}).json()
    sid = item["sources"][0]["id"]
    pages["overrides"]["/drill"] = fixture_html("jsonld_graph_aggregate.html").replace('"149.00"', '"119.00"')
    r = client.post(f"/api/sources/{sid}/check")
    assert r.json()["outcome"] == "ok"
    hist = client.get(f"/api/items/{item['id']}/history").json()
    prices = [p["price_cents"] for p in hist["series"][0]["points"]]
    assert prices == [14900, 11900]
    titles = [a["title"] for a in client.get("/api/alerts").json()]
    assert any("Price drop" in t for t in titles)
    assert any("all-time low" in t for t in titles)
    detail = client.get(f"/api/items/{item['id']}").json()
    assert detail["summary"]["low_30_cents"] == 11900


def test_blocked_sets_backoff(client, pages):
    item = client.post("/api/items/from-url", json={"url": "https://www.staples.ca/blocked"}).json()
    sid = item["sources"][0]["id"]
    assert client.post(f"/api/sources/{sid}/check").json()["outcome"] == "blocked"
    retailer = next(r for r in client.get("/api/retailers").json() if r["domain"] == "staples.ca")
    assert retailer["backoff_until"] is not None
    assert client.post(f"/api/sources/{sid}/check").json()["outcome"] == "backoff"
    system = client.get("/api/system").json()
    assert any(d["domain"] == "staples.ca" and d["backoff_until"] for d in system["domains"])


def test_non_cad_rejected(client, pages):
    item = client.post("/api/items/from-url", json={"url": "https://www.example.com/usd"}).json()
    assert item["summary"]["best_price_cents"] is None
    sid = item["sources"][0]["id"]
    assert client.post(f"/api/sources/{sid}/check").json()["outcome"] == "currency"


def test_manual_price_and_multiple_sources(client, pages):
    item = client.post("/api/items", json={"name": "Air fryer", "target_price_cents": 10000}).json()
    client.post(f"/api/items/{item['id']}/sources", json={"url": "https://www.walmart.ca/fryer"})
    r = client.post(f"/api/items/{item['id']}/manual", json={"store": "Costco in store", "price_cents": 11999})
    assert r.status_code == 201
    detail = client.get(f"/api/items/{item['id']}").json()
    assert detail["summary"]["best_price_cents"] == 11999
    assert detail["summary"]["source_count"] == 2
    assert detail["summary"]["badge"] in ("WAIT", "GOOD")


def test_settings_validation_and_masking(client):
    assert client.patch("/api/settings", json={"province": "zz"}).status_code == 422
    r = client.patch("/api/settings", json={"province": "qc", "notify_urls": ["ntfys://ntfy.sh/secret-topic"]})
    body = r.json()
    assert body["province"] == "QC"
    assert body["notify_urls"] == ["ntfys://ntfy.sh/***"]
    # sending the masked value back keeps the real URL
    client.patch("/api/settings", json={"notify_urls": ["ntfys://ntfy.sh/***"]})
    from pricewatch.db import session_scope
    from pricewatch.services import settings_store
    db = session_scope()
    assert settings_store.get(db, "notify_urls") == ["ntfys://ntfy.sh/secret-topic"]
    db.close()


def test_duplicate_source_conflict(client, pages):
    item = client.post("/api/items", json={"name": "X"}).json()
    assert client.post(f"/api/items/{item['id']}/sources", json={"url": "https://a.ca/x"}).status_code == 201
    assert client.post(f"/api/items/{item['id']}/sources", json={"url": "https://a.ca/x"}).status_code == 409


def test_metrics(client):
    assert "pricewatch_items" in client.get("/metrics").text
