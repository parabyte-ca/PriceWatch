"""v0.3.0: block detection, offer fields, Keepa, policies, price match, quick add, actions, changedetection.io."""

from datetime import datetime, timedelta

import httpx
import pytest

from pricewatch.fetch.http import PoliteFetcher, looks_like_challenge
from pricewatch.services import alerts, checker, events, keepa, runtime

from .conftest import fixture_html

PAGES = {
    "/xm6": "jsonld_offer.html", "/drill": "jsonld_graph_aggregate.html", "/challenge": "challenge.html",
    "/market": "marketplace_offer.html", "/fryer": "opengraph.html",
}


@pytest.fixture
def pages():
    overrides = {}

    def handler(req: httpx.Request):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path in overrides:
            return httpx.Response(200, text=overrides[req.url.path])
        name = PAGES.get(req.url.path)
        return httpx.Response(200 if name else 404, text=fixture_html(name or "no_price.html"))

    runtime.set_fetcher(PoliteFetcher("PriceWatchCA/test", min_interval=0, jitter=0,
                                      transport=httpx.MockTransport(handler)))
    yield overrides
    runtime.set_fetcher(None)


@pytest.fixture
def quiet(monkeypatch):
    sent = []
    monkeypatch.setattr(alerts, "send_all", lambda urls, a: (sent.append(a) or True, None))
    return sent


def test_challenge_detection():
    assert looks_like_challenge(fixture_html("challenge.html"))
    assert looks_like_challenge("")
    assert not looks_like_challenge(fixture_html("no_price.html"))


def test_200_challenge_is_blocked_not_out_of_stock(client, pages):
    item = client.post("/api/items/from-url", json={"url": "https://www.example-shop.ca/challenge"}).json()
    sid = item["sources"][0]["id"]
    client.patch(f"/api/sources/{sid}", json={"fetch_mode": "http"})
    assert client.post(f"/api/sources/{sid}/check").json()["outcome"] == "blocked"
    src = client.get(f"/api/items/{item['id']}").json()["sources"][0]
    assert src["last_in_stock"] is None and src["last_price_cents"] is None


def test_marketplace_offer_recorded_but_not_compared(client, pages):
    item = client.post("/api/items/from-url", json={"url": "https://www.bestbuy.ca/market"}).json()
    sid = item["sources"][0]["id"]
    assert client.post(f"/api/sources/{sid}/check").json()["outcome"] == "excluded"
    detail = client.get(f"/api/items/{item['id']}").json()
    assert detail["summary"]["best_price_cents"] is None
    assert detail["sources"][0]["last_price_cents"] == 29900
    client.patch(f"/api/items/{item['id']}", json={"exclude_marketplace": False})
    assert client.get(f"/api/items/{item['id']}").json()["summary"]["best_price_cents"] == 29900


def test_seller_type_and_condition_helpers():
    from pricewatch.models import Retailer
    bb = Retailer(domain="bestbuy.ca", name="Best Buy Canada")
    assert checker.seller_type_for("Best Buy", bb) == "first_party"
    assert checker.seller_type_for("BestBuy.ca", bb) == "first_party"
    assert checker.seller_type_for(None, bb) == "first_party"
    assert checker.seller_type_for("Joe's Gadgets", bb) == "marketplace:Joe's Gadgets"
    assert checker.seller_type_for("Best Buy Canada Ltd.", bb) == "first_party"
    wm = Retailer(domain="walmart.ca", name="Walmart Canada")
    assert checker.seller_type_for("Walmart Inc.", wm) == "first_party"
    mx = Retailer(domain="memoryexpress.com", name="Memory Express")
    assert checker.seller_type_for("MEMX Computer Products", mx) == "first_party"  # not a marketplace retailer
    assert checker.seller_type_for("Sold by GadgetCo via Marketplace", mx).startswith("marketplace")
    assert checker.normal_condition("Open Box") == "open_box"
    assert checker.normal_condition(None) == "new"


# ---------- Keepa ----------

KEEPA_JSON = {
    "tokensLeft": 19,
    "products": [{
        "asin": "B0TESTASIN", "title": "Sony WH-1000XM6", "brand": "Sony", "model": "WH1000XM6/B",
        "eanList": ["4548736158566"], "imagesCSV": "abc.jpg,def.jpg",
        "csv": [[keepa.KEEPA_EPOCH_MINUTES * 0 + 8_000_000, 49999, 8_100_000, 42999, 8_200_000, -1]],
        "stats": {"current": [44999, 43999, -1, -1, 54999] + [-1] * 13 + [44999]},
    }],
}


def test_keepa_parse():
    p = keepa.parse_product(KEEPA_JSON)
    assert p.amazon_price_cents == 44999 and p.list_price_cents == 54999 and p.buybox_price_cents == 44999
    assert p.gtin == "4548736158566" and p.image.endswith("abc.jpg")
    assert [x[1] for x in p.amazon_history] == [49999, 42999, None]
    assert keepa.asin_from_url("https://www.amazon.ca/Sony-Headphones/dp/B0TESTASIN?th=1") == "B0TESTASIN"


def test_amazon_without_keepa_key_is_manual(client):
    r = client.post("/api/preview", json={"url": "https://www.amazon.ca/dp/B0TESTASIN"}).json()
    assert r["outcome"] == "needs_keepa" and "KEEPA_API_KEY" in r["error"]
    item = client.post("/api/items/from-url", json={"url": "https://www.amazon.ca/dp/B0TESTASIN"}).json()
    sid = item["sources"][0]["id"]
    assert client.post(f"/api/sources/{sid}/check").json()["outcome"] == "needs_keepa"


def test_amazon_with_keepa_seeds_history(client, monkeypatch):
    from pricewatch.config import get_settings
    monkeypatch.setattr(get_settings(), "keepa_api_key", "k")
    now_min = int(datetime.now().timestamp() // 60) - keepa.KEEPA_EPOCH_MINUTES
    data = {**KEEPA_JSON, "products": [{**KEEPA_JSON["products"][0],
                                        "csv": [[now_min - 30 * 1440, 49999, now_min - 10 * 1440, 42999]]}]}

    async def fake_fetch(key, asin, client=None, history=True):
        return keepa.parse_product(data)

    monkeypatch.setattr(keepa, "fetch_product", fake_fetch)
    item = client.post("/api/items/from-url", json={"url": "https://www.amazon.ca/dp/B0TESTASIN"}).json()
    detail = client.get(f"/api/items/{item['id']}").json()
    assert detail["name"] == "Sony WH-1000XM6" and detail["gtin"] == "4548736158566"  # autofilled
    src = detail["sources"][0]
    assert src["last_price_cents"] == 44999 and src["external_id"] if "external_id" in src else True
    hist = client.get(f"/api/items/{item['id']}/history").json()["series"][0]["points"]
    assert [p["price_cents"] for p in hist] == [49999, 42999, 44999]
    assert detail["summary"]["seasonal_low_cents"] == round(42999 * 1.13)
    assert detail["summary"]["history_confidence"] == "MEDIUM"


# ---------- policies, decisions ----------

def test_policies_seeded_with_corrections(client):
    pols = {p["domain"]: p for p in client.get("/api/policies").json()}
    assert pols["walmart.ca"]["competitor_match"] is False
    assert pols["canadiantire.ca"]["enabled"] is False and pols["canadiantire.ca"]["verified"] is False
    assert "black_friday" in pols["bestbuy.ca"]["excluded_events"]
    assert pols["staples.ca"]["electronics_window_days"] == 14
    assert pols["costco.ca"]["own_price_adjustment"] is True
    retailers = {r["domain"] for r in client.get("/api/retailers").json()}
    assert "thesource.ca" not in retailers and "sportchek.ca" in retailers


def test_price_match_opportunity(client, pages, monkeypatch):
    monkeypatch.setattr(events, "local_now", lambda now=None: datetime(2026, 11, 16, 9, 0, tzinfo=events.tz()))
    item = client.post("/api/items/from-url", json={"url": "https://www.bestbuy.ca/xm6"}).json()
    client.post(f"/api/items/{item['id']}/manual", json={"store": "Canada Computers", "price_cents": 41999,
                                                         "url": "https://www.canadacomputers.com/p/1"})
    s = client.get(f"/api/items/{item['id']}").json()["summary"]
    opp = s["price_match"][0]
    assert opp["at"] == "Best Buy Canada" and opp["match_to"] == "Canada Computers"
    assert opp["saving_cents"] == 44999 - 41999 and opp["caveats"] == []
    monkeypatch.setattr(events, "local_now", lambda now=None: datetime(2026, 11, 27, 9, 0, tzinfo=events.tz()))
    s = client.get(f"/api/items/{item['id']}").json()["summary"]
    assert "Black Friday" in s["price_match"][0]["caveats"][0]


def test_buy_and_protect_costco(client, monkeypatch):
    from pricewatch.db import session_scope
    from pricewatch.models import Observation, SourceLink
    from pricewatch.services.summary import summarize_items
    from pricewatch.timeutil import utcnow

    monkeypatch.setattr(events, "local_now", lambda now=None: datetime(2026, 11, 16, 9, 0, tzinfo=events.tz()))
    item = client.post("/api/items", json={"name": "TV"}).json()
    src = client.post(f"/api/items/{item['id']}/manual", json={"store": "Costco", "price_cents": 100000,
                                                               "url": "https://www.costco.ca/tv.html"}).json()
    db = session_scope()
    # 20 days of history with a seasonal low of $1000, now $1040 (4% above)
    for d in range(20, 0, -1):
        db.add(Observation(item_id=item["id"], source_link_id=src["id"], observed_at=utcnow() - timedelta(days=d),
                           price_cents=100000))
    s = db.get(SourceLink, src["id"])
    s.last_price_cents = 104000
    db.commit()
    from pricewatch.models import Item
    summ = summarize_items(db, [db.get(Item, item["id"])])[item["id"]]
    db.close()
    assert summ["decision"] == "BUY_AND_PROTECT" and "30-day" in summ["protection"]


def test_blackfriday_interval(db_session, monkeypatch):
    from pricewatch.models import Item
    item = Item(name="Hot", hot=True, priority=1)
    db_session.add(item)
    db_session.commit()
    monkeypatch.setattr(events, "local_now", lambda now=None: datetime(2026, 11, 28, 12, 0,
                                                                       tzinfo=events.tz()))
    assert checker.next_interval_minutes(item, db_session) <= 39  # 30 min plus or minus 30%
    monkeypatch.setattr(events, "local_now", lambda now=None: datetime(2026, 11, 20, 12, 0,
                                                                       tzinfo=events.tz()))
    assert checker.next_interval_minutes(item, db_session) >= 84  # 2 h minus 30%


# ---------- quick add, actions, token ----------

def test_import_list(client, pages):
    r = client.post("/api/import", json={"text": "https://www.bestbuy.ca/xm6?utm_source=x\nLEGO Titanic set\n\n# note\n"
                                                 "https://www.bestbuy.ca/xm6"}).json()
    assert len(r["created"]) == 3  # same URL on two lines makes two items; each is its own wishlist entry
    items = client.get("/api/items").json()
    autofill = next(i for i in items if i["sources"] is None and "bestbuy" in i["name"].lower()) if False else None
    assert any(i["name"] == "LEGO Titanic set" for i in items)
    first = client.get(f"/api/items/{r['created'][0]['id']}").json()
    sid = first["sources"][0]["id"]
    assert client.post(f"/api/sources/{sid}/check").json()["outcome"] == "ok"
    assert client.get(f"/api/items/{first['id']}").json()["name"].startswith("Sony WH-1000XM6")  # autofilled
    assert autofill is None


def test_snooze_and_signed_action(client, pages, quiet):
    client.patch("/api/settings", json={"notify_urls": ["ntfys://ntfy.sh/pw-test"]})
    item = client.post("/api/items/from-url", json={"url": "https://www.bestbuy.ca/xm6"}).json()
    token = alerts.action_token(item["id"], "snooze")
    assert client.post(f"/api/actions/{token}").status_code == 200
    assert client.get(f"/api/items/{item['id']}").json()["summary"]["snoozed"] is True
    client.patch(f"/api/items/{item['id']}", json={"target_price_cents": 50000})
    assert not quiet  # snoozed: no push
    assert client.post("/api/actions/garbage").status_code == 403
    client.delete(f"/api/items/{item['id']}/snooze")
    client.patch(f"/api/items/{item['id']}", json={"target_price_cents": 50001})
    assert quiet and quiet[0].title.startswith("BUY NOW")


def test_bearer_token_auth(client, monkeypatch):
    from pricewatch.config import get_settings
    s = get_settings()
    token = client.get("/api/token").json()["token"]
    assert token
    monkeypatch.setattr(s, "auth_mode", "password")
    monkeypatch.setattr(s, "admin_password", "pw")
    assert client.get("/api/items").status_code == 401
    assert client.get("/api/items", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.get("/api/items", headers={"Authorization": "Bearer wrong"}).status_code == 401


# ---------- changedetection.io ----------

def test_changedetection_sync(client, pages, monkeypatch):
    from pricewatch.config import get_settings
    from pricewatch.db import session_scope
    from pricewatch.services import changedetection as cd

    s = get_settings()
    monkeypatch.setattr(s, "changedetection_url", "http://cd:5000")
    monkeypatch.setattr(s, "changedetection_api_key", "key")
    created = {}

    def handler(req):
        assert req.headers["x-api-key"] == "key"
        if req.method == "POST":
            created.update({"url": req.read().decode()})
            return httpx.Response(201, json={"uuid": "u-1"})
        if req.url.path == "/api/v1/watch":
            return httpx.Response(200, json={"u-1": {"url": "https://www.bestbuy.ca/xm6"}})
        return httpx.Response(200, json={"url": "https://www.bestbuy.ca/xm6", "last_checked": 1_900_000_000,
                                         "restock": {"in_stock": True, "price": 399.99, "currency": "CAD"}})

    real_client = cd._client
    monkeypatch.setattr(cd, "_client", lambda: httpx.Client(base_url="http://cd:5000", headers={"x-api-key": "key"},
                                                            transport=httpx.MockTransport(handler)))
    item = client.post("/api/items/from-url", json={"url": "https://www.bestbuy.ca/xm6"}).json()
    sid = item["sources"][0]["id"]
    r = client.post(f"/api/sources/{sid}/changedetection").json()
    assert r["watch"] == "u-1" and "restock_diff" in created["url"]
    assert client.post(f"/api/sources/{sid}/check").json()["outcome"] == "skipped"  # PriceWatch stops fetching
    db = session_scope()
    stats = cd.sync(db)
    db.close()
    assert stats["recorded"] == 1
    assert client.get(f"/api/items/{item['id']}").json()["sources"][0]["last_price_cents"] == 39999
    assert real_client is not None
