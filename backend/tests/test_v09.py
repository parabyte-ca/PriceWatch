"""v0.9.0: Home Assistant sensors, barcode lookup, Claude check on the deal feed and flyers."""

import json
from datetime import datetime, timedelta

import httpx
import pytest

from pricewatch.fetch.http import PoliteFetcher
from pricewatch.services import alerts, runtime

from .conftest import fixture_html
from .test_discovery import fake  # noqa: F401  (fixture)


@pytest.fixture
def pages():
    overrides = {}

    def handler(req: httpx.Request):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path in overrides:
            body = overrides[req.url.path]
            return httpx.Response(200, text=body if isinstance(body, str) else json.dumps(body))
        return httpx.Response(200, text=fixture_html("jsonld_offer.html"))

    runtime.set_fetcher(PoliteFetcher("PriceWatchCA/test", min_interval=0, jitter=0,
                                      transport=httpx.MockTransport(handler)))
    yield overrides
    runtime.set_fetcher(None)


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(alerts, "send_all", lambda urls, a: (out.append(a) or True, None))
    return out


def test_home_assistant_summary(client, pages):
    item = client.post("/api/items/from-url", json={"url": "https://www.bestbuy.ca/en-ca/product/a/10000001"}).json()
    client.patch(f"/api/items/{item['id']}", json={"target_price_cents": 50000})
    s = client.get("/api/ha/summary").json()
    assert s["state"] == 1 and s["buy"] == 1 and s["buy_now"] == [item["name"]]
    row = s["items"][0]
    assert row["price_before_tax"] == 449.99 and row["target"] == 500.0 and row["badge"] == "BUY NOW"
    assert row["url"].endswith(f"/items/{item['id']}")
    assert client.get(f"/api/ha/items/{item['id']}").json()["decision"] == "BUY"
    assert client.get("/api/ha/items/999").status_code == 404


def test_barcode_lookup(client, fake, monkeypatch):  # noqa: F811
    r = client.get("/api/barcode/4548736158566").json()
    assert r["gtin"] == "4548736158566" and r["provider"] == "serpapi" and r["names"]
    assert client.get("/api/barcode/4548736158567").status_code == 409  # bad check digit
    from pricewatch.services import discovery
    monkeypatch.setattr(discovery, "get_provider", lambda name=None: None)
    assert client.get("/api/barcode/4548736158566").json()["names"] == []


async def test_deal_feed_llm_veto(client, pages, sent, monkeypatch):
    from pricewatch.db import session_scope
    from pricewatch.services import dealfeed, llm_match
    from pricewatch.services.matching import MatchResult

    client.patch("/api/settings", json={"notify_urls": ["ntfys://ntfy.sh/me"]})
    client.post("/api/items", json={"name": "DEWALT 20V MAX Cordless Drill Kit", "brand": "DEWALT",
                                    "model": "DCD777C2"})
    real = dealfeed.match

    def fuzzy(spec, cand, threshold):
        r = real(spec, cand, threshold)
        return MatchResult(0.792, "fuzzy", True, r.reasons, r.exclusions) if r.accepted else r

    asked = []

    def asker(model, item, listing):
        asked.append(listing)
        return llm_match.Verdict(same_product=False, confidence=0.9, reason="different kit")

    async def check(db, spec, cand, asker_=None):
        return await real_check(db, spec, cand, asker=asker)

    real_check = llm_match.check
    monkeypatch.setattr(dealfeed, "match", fuzzy)
    monkeypatch.setattr(llm_match, "enabled", lambda db: True)
    monkeypatch.setattr(llm_match, "check", check)
    pages["/feed/forum/9"] = fixture_html("rfd_hot_deals.xml")
    fetcher = runtime.get_fetcher()
    plain = fetcher.fetch

    async def no_spacing(url, **kw):
        kw.pop("min_interval", None)  # the feed's 60 s politeness spacing is not needed in a test
        return await plain(url, **kw)

    monkeypatch.setattr(fetcher, "fetch", no_spacing)
    db = session_scope()
    stats = await dealfeed.poll(db)
    db.close()
    assert asked and stats["new"] == 5 and stats["matched"] == 0
    assert not [a for a in sent if a.rule_type == "deal_feed"]


async def test_flyer_llm_veto(client, pages, sent, monkeypatch):
    from pricewatch.db import session_scope
    from pricewatch.services import flyers, llm_match
    from pricewatch.services.matching import MatchResult

    client.post("/api/items", json={"name": "Sony WH-1000XM6 Headphones", "brand": "Sony", "model": "WH-1000XM6"})
    client.patch("/api/settings", json={"flyers_enabled": True, "postal_code": "K1A 0B1"})
    real = flyers.match

    def fuzzy(spec, cand, threshold):
        r = real(spec, cand, threshold)
        return MatchResult(0.81, "fuzzy", True, r.reasons, r.exclusions) if r.accepted else r

    async def check(db, spec, cand, asker=None):
        db.add(llm_match.LlmMatchCache(key=llm_match._key("claude-haiku-5-5", *llm_match._describe(spec, cand)),
                                       same_product="Refurb" not in cand.title, confidence=0.9, reason="t",
                                       model="claude-haiku-5-5"))
        db.flush()
        return {"same_product": True}

    monkeypatch.setattr(flyers, "match", fuzzy)
    monkeypatch.setattr(llm_match, "enabled", lambda db: True)
    monkeypatch.setattr(llm_match, "check", check)
    soon = (datetime.now() + timedelta(days=3)).isoformat()
    pages["/flipp/items/search"] = {"items": [
        {"flyer_item_id": 1, "name": "Sony WH-1000XM6 Wireless Headphones", "merchant_name": "Visions",
         "current_price": 379.99, "valid_to": soon},
        {"flyer_item_id": 2, "name": "Sony WH-1000XM6 Headphones Refurb", "merchant_name": "Visions",
         "current_price": 249.99, "valid_to": soon},
    ]}
    db = session_scope()
    stats = await flyers.poll(db, force=True)
    db.close()
    assert stats["matches"] == 1


def test_forecast_estimate():
    from datetime import date

    from pricewatch.services import forecast

    today = date(2026, 11, 16)
    days = [today - timedelta(days=40 - n) for n in range(40)]
    # usual 400, dips to 360 now and then, now back up at 449
    prices = [40000 if n % 10 else 36000 for n in range(39)] + [44900]
    r = forecast.estimate(list(zip(days, prices, strict=True)), today)
    assert r["chance"] == "high" and r["next_event"]["name"] == "Black Friday"
    assert r["likely_low_cents"] == 36000 and any("above its usual" in x for x in r["reasons"])
    flat = forecast.estimate(list(zip(days, [30000] * 40, strict=True)), date(2026, 12, 2))
    assert flat["chance"] == "low" and flat["likely_low_cents"] is None
    assert forecast.estimate([(today, 100)], today)["chance"] is None


def test_forecast_endpoint(client, pages):
    item = client.post("/api/items/from-url", json={"url": "https://www.bestbuy.ca/en-ca/product/a/10000001"}).json()
    r = client.get(f"/api/items/{item['id']}/forecast").json()
    assert r["chance"] is None and "Needs at least" in r["reasons"][0]


def test_weekly_report(client, pages, sent, monkeypatch):
    from pricewatch.db import session_scope
    from pricewatch.services import events, llm_match, weekly

    client.patch("/api/settings", json={"notify_urls": ["ntfys://ntfy.sh/me"]})
    item = client.post("/api/items/from-url", json={"url": "https://www.bestbuy.ca/en-ca/product/a/10000001"}).json()
    client.patch(f"/api/items/{item['id']}", json={"target_price_cents": 50000})
    sunday = datetime(2026, 11, 22, 18, 30, tzinfo=events.tz())
    monkeypatch.setattr(events, "local_now", lambda now=None: sunday)
    monkeypatch.setattr(llm_match, "enabled", lambda db: False)
    db = session_scope()
    out = weekly.maybe_send(db)
    assert len(out) == 1 and "Buy now:" in out[0].body and item["name"] in out[0].body
    assert weekly.maybe_send(db) == []  # once a week
    monkeypatch.setattr(events, "local_now", lambda now=None: datetime(2026, 11, 23, 18, 30, tzinfo=events.tz()))
    assert weekly.maybe_send(db) == []  # Mondays: nothing
    # with Claude: the note goes on top
    monkeypatch.setattr(weekly, "claude_summary", lambda db, text: "Buy the headphones now.")
    from pricewatch.models import User
    title, body = weekly.build(db, db.query(User).first())
    assert body.startswith("Buy the headphones now.\n\nBuy now:")
    db.close()


def test_generic_titles_use_url_name():
    from pricewatch.adapters.base import clean_name, name_from_url

    url = "https://www.sportchek.ca/en/pdp/toronto-raptors-nike-men-s-standard-issue-hoodie-86259822f.334692194.html"
    assert clean_name("General PDP Template", url, "Sport Chek") == "Toronto Raptors Nike Men's Standard Issue Hoodie"
    assert clean_name("Sport Chek", url, "Sport Chek").startswith("Toronto Raptors")
    assert clean_name("Sony WH-1000XM6 Headphones", url, "Sport Chek") == "Sony WH-1000XM6 Headphones"
    assert name_from_url("https://www.canadiantire.ca/en/pdp/mastercraft-20v-drill-kit-0543210p.html") == \
        "Mastercraft 20V Drill Kit"
    assert name_from_url("https://www.costco.ca/x.product.html") is None


def test_preview_replaces_template_title(client, pages):
    pages["/en/pdp/toronto-raptors-hoodie-86259822f.334692194.html"] = \
        "<html><head><title>General PDP Template</title></head><body>loading</body></html>"
    from pricewatch.db import session_scope
    from pricewatch.models import Retailer

    db = session_scope()
    r = db.query(Retailer).filter_by(domain="sportchek.ca").one()
    r.fetch_mode, r.min_interval_seconds = "auto", None  # seeded browser mode and 45 s spacing; not needed here
    db.commit()
    db.close()
    resp = client.post("/api/preview", json={
        "url": "https://www.sportchek.ca/en/pdp/toronto-raptors-hoodie-86259822f.334692194.html"}).json()
    assert resp["product"]["name"] == "Toronto Raptors Hoodie" and resp["product"]["price_cents"] is None
