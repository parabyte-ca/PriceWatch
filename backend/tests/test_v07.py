"""v0.7.0: perks, gift budgets, savings, RFD thread summaries, web push, diagnostics, flyers, Best Buy JSON."""

import json
from datetime import datetime, timedelta

import httpx
import pytest

from pricewatch.fetch.http import PoliteFetcher
from pricewatch.services import alerts, runtime

from .conftest import fixture_html


@pytest.fixture
def pages():
    overrides = {}
    seen = []

    def handler(req: httpx.Request):
        seen.append(str(req.url))
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path in overrides:
            body = overrides[req.url.path]
            return httpx.Response(200, text=body if isinstance(body, str) else json.dumps(body))
        return httpx.Response(200, text=fixture_html("jsonld_offer.html"))

    runtime.set_fetcher(PoliteFetcher("PriceWatchCA/test", min_interval=0, jitter=0,
                                      transport=httpx.MockTransport(handler)))
    overrides["_seen"] = seen
    yield overrides
    runtime.set_fetcher(None)


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(alerts, "send_all", lambda urls, a: (out.append(a) or True, None))
    return out


def test_perks_after_perks_price(client, pages):
    item = client.post("/api/items/from-url", json={"url": "https://www.bestbuy.ca/en-ca/product/x/12345678"}).json()
    r = client.post("/api/perks", json={"retailer_domain": "bestbuy.ca", "kind": "cashback", "label": "Rakuten 2%",
                                        "percent": 2})
    assert r.status_code == 201
    client.post("/api/perks", json={"retailer_domain": "bestbuy.ca", "kind": "card", "label": "Card 5%", "percent": 5})
    best = client.get(f"/api/items/{item['id']}").json()["summary"]["best"]
    landed = best["landed"]["landed_cents"]
    assert best["after_perks_cents"] == round(landed * 0.98 * 0.95)
    assert best["perks_saving_cents"] == landed - best["after_perks_cents"]
    assert [p["label"] for p in client.get("/api/perks").json()] == ["Rakuten 2%", "Card 5%"]
    # expired perks do not count
    pid = client.get("/api/perks").json()[1]["id"]
    client.patch(f"/api/perks/{pid}", json={"retailer_domain": "bestbuy.ca", "kind": "card", "label": "Card 5%",
                                            "percent": 5, "valid_until": "2020-01-01"})
    best = client.get(f"/api/items/{item['id']}").json()["summary"]["best"]
    assert best["after_perks_cents"] == round(landed * 0.98)


def test_gift_list_budget_and_savings(client, pages):
    lst = client.post("/api/lists", json={"name": "Mom", "occasion": "Christmas", "recipient": "Mom",
                                          "event_date": "2026-12-25", "budget_cents": 50000}).json()
    assert lst["budget_cents"] == 50000 and lst["remaining_cents"] == 50000
    item = client.post("/api/items/from-url", json={"url": "https://www.bestbuy.ca/en-ca/product/a/10000001",
                                                            "list_id": lst["id"]}).json()
    src = item["sources"][0]
    # three observations at 449.99 so there is a reference median
    for _ in range(2):
        client.post(f"/api/sources/{src['id']}/check")
    client.post(f"/api/items/{item['id']}/purchases", json={"source_id": src["id"], "price_cents": 39999})
    lst = next(x for x in client.get("/api/lists").json() if x["id"] == lst["id"])
    assert lst["spent_cents"] == 39999 and lst["remaining_cents"] == 10001
    p = client.get("/api/purchases").json()[0]
    assert p["reference_cents"] == 44999 and p["saved_vs_median_cents"] == 5000
    s = client.get("/api/savings").json()
    assert s["total"]["spent_cents"] == 39999 and s["total"]["saved_vs_median_cents"] == 5000
    assert any(x["spent_cents"] == 39999 for x in s["by_list"])
    r = client.patch(f"/api/lists/{lst['id']}", json={"budget_cents": 30000}).json()
    assert r["remaining_cents"] == -9999


def test_rfd_thread_summary_signals():
    from pricewatch.services import rfdthread

    html = """<div class="post_content">ATL, lowest price I've seen. Use code SAVE20NOW at checkout</div>
    <div class="post_content">Got Best Buy to price match no problem at $379.99</div>
    <div class="post_content">All time low for sure</div>
    <div class="post_content">Wait for Boxing Day, it was cheaper last year at $349.99</div>"""
    s = rfdthread.summarize(rfdthread.extract_posts(html))
    assert s["posts"] == 4
    assert s["signals"]["all_time_low"] == 2 and s["signals"]["wait"] == 1 and s["signals"]["price_match_ok"] == 1
    assert s["verdict"] == "crowd says good price"
    assert s["lowest_quoted_cents"] == 34999 and "SAVE20NOW" in s["coupons"]
    assert "PriceWatch saw $300.00" in rfdthread.compare(s, 30000)
    assert rfdthread.compare(s, 40000) is None
    over = rfdthread.summarize(["Deal is dead", "expired now", "sold out"])
    assert over["verdict"] == "likely over"


def test_web_push_send_and_gone_subscription(client, monkeypatch):
    from pricewatch.db import session_scope
    from pricewatch.models import Alert, PushSubscription
    from pricewatch.services import webpush

    key = client.get("/api/push/key").json()["public_key"]
    assert len(key) > 80
    sub = {"endpoint": "https://push.example.com/a", "keys": {"p256dh": "B" * 87, "auth": "A" * 22}}
    assert client.post("/api/push/subscribe", json=sub).status_code == 201
    client.post("/api/push/subscribe", json=sub)  # idempotent
    client.post("/api/push/subscribe", json={**sub, "endpoint": "https://push.example.com/gone"})
    assert len(client.get("/api/push/devices").json()) == 2

    calls = []

    class Gone(Exception):
        response = type("R", (), {"status_code": 410})()

    def fake(subscription_info, data, **kw):
        calls.append((subscription_info["endpoint"], json.loads(data)))
        if subscription_info["endpoint"].endswith("gone"):
            raise Gone()

    db = session_scope()
    uid = db.scalar(__import__("sqlalchemy").select(PushSubscription.user_id))
    alert = Alert(user_id=uid, item_id=None, rule_type="test", dedup_key="t", title="Hi", body="There", url="/")
    assert webpush.send(db, alert, sender=fake) == 1
    assert calls[0][1]["title"] == "Hi"
    assert db.query(PushSubscription).count() == 1  # 410 removed
    db.close()
    client.post("/api/push/unsubscribe", json={"endpoint": "https://push.example.com/a"})
    assert client.get("/api/push/devices").json() == []


def test_deliver_counts_push_as_sent(client, monkeypatch):
    from pricewatch.db import session_scope
    from pricewatch.models import Alert
    from pricewatch.services import webpush

    monkeypatch.setattr(webpush, "send", lambda db, alert: 1)
    db = session_scope()
    a = Alert(user_id=1, rule_type="test", dedup_key="x", title="t", body="b")
    db.add(a)
    db.commit()
    alerts.deliver(db, a, force=True)
    assert a.status == "sent"
    db.close()


def test_diagnose_reports_and_saves_fixture(client, pages):
    r = client.post("/api/admin/diagnose", json={"url": "https://www.sportchek.ca/p/1", "save_fixture": True}).json()
    assert r["robots_allowed"] is True and r["http"]["outcome"] == "ok"
    assert r["http"]["parsed"]["price_cents"] == 44999 and r["verdict"] == "ok"
    assert r["fixture"].startswith("data/fixtures/sportchek.ca-")
    pages["/p/2"] = "<html><body>Just a moment... checking your browser</body></html>"
    r = client.post("/api/admin/diagnose", json={"url": "https://www.sportchek.ca/p/2"}).json()
    assert r["verdict"] != "ok"


async def test_flyers_opt_in_and_matching(client, pages, sent):
    from pricewatch.db import session_scope
    from pricewatch.services import flyers

    item = client.post("/api/items", json={"name": "Sony WH-1000XM6 Headphones", "brand": "Sony",
                                           "model": "WH-1000XM6", "target_price_cents": 40000}).json()
    db = session_scope()
    assert await flyers.poll(db) == {"enabled": False}  # off by default
    client.patch("/api/settings", json={"flyers_enabled": True, "postal_code": "K1A 0B1",
                                        "notify_urls": ["ntfys://ntfy.sh/me"]})
    soon = (datetime.now() + timedelta(days=3)).isoformat()
    pages["/flipp/items/search"] = {"items": [
        {"flyer_item_id": 111, "name": "Sony WH-1000XM6 Wireless Headphones", "merchant_name": "Visions",
         "current_price": 379.99, "valid_to": soon},
        {"flyer_item_id": 222, "name": "Sony WH-1000XM5 Headphones", "merchant_name": "Visions",
         "current_price": 299.99, "valid_to": soon},
        {"flyer_item_id": 333, "name": "Bananas", "merchant_name": "Grocer", "current_price": 0.69},
    ]}
    stats = await flyers.poll(db, force=True)
    assert stats["matches"] == 1
    assert any("postal_code=K1A0B1" in u for u in pages["_seen"])
    rows = client.get(f"/api/items/{item['id']}/flyers").json()
    assert len(rows) == 1 and rows[0]["merchant"] == "Visions" and rows[0]["price_cents"] == 37999
    assert any(a.rule_type == "flyer" for a in sent)  # at or under target: sent right away
    assert (await flyers.poll(db, force=True))["matches"] == 0  # no duplicates
    db.close()
    assert flyers.valid_postal("90210") is None


def test_best_buy_json_adapter(client, pages):
    from pricewatch.adapters import bestbuy

    url = "https://www.bestbuy.ca/en-ca/product/sony-wh-1000xm6/18934721"
    assert bestbuy.api_url(url) == "https://www.bestbuy.ca/api/v2/json/product/18934721?lang=en-CA"
    pages["/api/v2/json/product/18934721"] = {"sku": "18934721", "name": "Sony WH-1000XM6", "regularPrice": 549.99,
                                              "salePrice": 429.99, "brandName": "Sony", "modelNumber": "WH1000XM6/B",
                                              "availability": {"isAvailableOnline": True}}
    item = client.post("/api/items/from-url", json={"url": url}).json()
    src = item["sources"][0]
    client.patch(f"/api/sources/{src['id']}", json={"fetch_mode": "bestbuy_api"})
    r = client.post(f"/api/sources/{src['id']}/check").json()
    assert r["outcome"] == "ok"
    s = client.get(f"/api/items/{item['id']}").json()["sources"][0]
    assert s["last_price_cents"] == 42999
    # API gone: falls back to the product page
    pages["/api/v2/json/product/18934721"] = "<html>nope</html>"
    assert client.post(f"/api/sources/{src['id']}/check").json()["outcome"] == "ok"
    s = client.get(f"/api/items/{item['id']}").json()["sources"][0]
    assert s["last_price_cents"] == 44999
    assert bestbuy.parse_json("not json", url) is None


async def test_proof_screenshot_added(client, pages, monkeypatch):
    from pricewatch.config import get_settings
    from pricewatch.db import session_scope
    from pricewatch.fetch import browser
    from pricewatch.models import ProofCapture, Purchase, SourceLink
    from pricewatch.services import protection

    item = client.post("/api/items/from-url", json={"url": "https://www.bestbuy.ca/en-ca/product/b/10000002"}).json()
    src_id = item["sources"][0]["id"]
    client.post(f"/api/items/{item['id']}/purchases", json={"source_id": src_id, "price_cents": 50000})
    db = session_scope()
    src = db.get(SourceLink, src_id)
    p = db.query(Purchase).one()
    obs = src.item and db.query(__import__("pricewatch.models", fromlist=["Observation"]).Observation).first()
    protection.capture(db, p, src, obs, "<html>proof</html>")
    db.commit()
    monkeypatch.setattr(get_settings(), "browser_enabled", True)

    async def shot(url, ws, timeout, ua):
        return b"\x89PNG fake"

    monkeypatch.setattr(browser, "screenshot", shot)
    assert await protection.add_screenshots(db, src) == 1
    cap = db.query(ProofCapture).one()
    folder = get_settings().data_dir / cap.path
    assert cap.screenshot and (folder / "screenshot.png").read_bytes() == b"\x89PNG fake"
    assert "screenshot_sha256" in json.loads((folder / "proof.json").read_text())
    assert await protection.add_screenshots(db, src) == 0
    db.close()
