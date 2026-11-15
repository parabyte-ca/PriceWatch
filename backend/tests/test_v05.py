"""v0.5.0: purchases and price protection, proof package, RedFlagDeals feed matching."""

import io
import zipfile
from datetime import date, datetime

import httpx
import pytest

from pricewatch.fetch.http import PoliteFetcher
from pricewatch.services import alerts, dealfeed, events, runtime

from .conftest import fixture_html


@pytest.fixture
def pages():
    overrides = {}

    def handler(req: httpx.Request):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path in overrides:
            return httpx.Response(200, text=overrides[req.url.path])
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


@pytest.fixture
def nov16(monkeypatch):
    monkeypatch.setattr(events, "local_now", lambda now=None: datetime(2026, 11, 16, 10, 0, tzinfo=events.tz()))


def test_costco_purchase_protected_and_drop_claimable(client, pages, sent, nov16):
    client.patch("/api/settings", json={"notify_urls": ["ntfys://ntfy.sh/me"]})
    item = client.post("/api/items/from-url", json={"url": "https://www.costco.ca/xm6.product.html"}).json()
    src = item["sources"][0]
    client.patch(f"/api/sources/{src['id']}", json={"fetch_mode": "http"})  # Costco defaults to the browser
    costco = next(r for r in client.get("/api/retailers").json() if r["domain"] == "costco.ca")
    from pricewatch.db import session_scope as _ss
    from pricewatch.models import Retailer as _R
    _db = _ss()
    _db.get(_R, costco["id"]).min_interval_seconds = None  # seeded 60 s spacing; not needed in tests
    _db.commit()
    _db.close()
    terms = client.get(f"/api/items/{item['id']}/protection-terms", params={"source_id": src["id"]}).json()
    assert terms["days"] == 30 and terms["until"] == "2026-12-16"
    p = client.post(f"/api/items/{item['id']}/purchases",
                    json={"source_id": src["id"], "price_cents": 44999, "purchased_on": "2026-11-16"}).json()
    assert p["status"] == "watching" and p["protection_basis"].startswith("30-day")
    assert client.get(f"/api/items/{item['id']}").json()["active"] is False  # no more deal alerts

    # price drops: claimable alert with proof captured
    pages["/xm6.product.html"] = fixture_html("jsonld_offer.html").replace('"449.99"', '"399.99"') \
        .replace('"price":449.99', '"price":399.99')
    assert client.post(f"/api/sources/{src['id']}/check").json()["outcome"] == "ok"
    prot = [a for a in sent if a.rule_type == "protection"]
    assert len(prot) == 1 and "Claim $50.00 back" in prot[0].title
    p = client.get("/api/purchases").json()[0]
    assert p["status"] == "claimable" and p["claimable_cents"] == 5000 and p["proof_count"] == 1

    # same price again: no duplicate alert
    client.post(f"/api/sources/{src['id']}/check")
    assert len([a for a in sent if a.rule_type == "protection"]) == 1

    # proof zip has the page snapshot and timestamps
    r = client.get(f"/api/purchases/{p['id']}/proof")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert "summary.json" in names and any(n.endswith("page.html") for n in names)
    proof = next(n for n in names if n.endswith("proof.json"))
    assert b"observed_at_local" in z.read(proof) and b"page_sha256" in z.read(proof)

    # claimed
    r = client.patch(f"/api/purchases/{p['id']}", json={"status": "claimed", "claimed_cents": 5000}).json()
    assert r["status"] == "claimed"


def test_inactive_item_with_open_purchase_still_scheduled(client, pages, nov16):
    from pricewatch import scheduler

    item = client.post("/api/items/from-url", json={"url": "https://www.costco.ca/tv.html"}).json()
    src = item["sources"][0]
    client.post(f"/api/items/{item['id']}/purchases", json={"source_id": src["id"], "price_cents": 100})
    from pricewatch.db import session_scope
    from pricewatch.models import SourceLink
    db = session_scope()
    db.get(SourceLink, src["id"]).next_check_at = None
    db.commit()
    db.close()
    assert src["id"] in scheduler.due_source_ids()


def test_best_buy_needs_badge(client, pages):
    import pricewatch.services.protection as prot
    from pricewatch.db import session_scope
    db = session_scope()
    assert prot.terms(db, "bestbuy.ca", date(2026, 11, 20), False, False)[0] == 0
    days, until, basis = prot.terms(db, "bestbuy.ca", date(2026, 11, 20), False, True)
    assert until == date(2026, 11, 30) and "Black Friday" in basis
    assert prot.terms(db, "bestbuy.ca", date(2026, 11, 10), False, True)[1] is None  # before the sale
    assert prot.terms(db, "walmart.ca", date(2026, 11, 20), False, True)[1] is None
    db.close()


def test_manual_protection_override_and_privacy(client, pages, nov16):
    item = client.post("/api/items", json={"name": "Printer"}).json()
    p = client.post(f"/api/items/{item['id']}/purchases",
                    json={"retailer_name": "Staples", "price_cents": 20000, "protection_days": 14}).json()
    assert p["protection_until"] == "2026-11-30" and "entered by you" in p["protection_basis"]
    # another person cannot see or touch it
    r = client.post("/api/users", json={"username": "sam", "display_name": "Sam", "password": "password123"})
    from pricewatch.db import session_scope
    from pricewatch.models import User
    from pricewatch.services import users as users_svc
    db = session_scope()
    tok = users_svc.new_api_token(db.get(User, r.json()["id"]))
    db.commit()
    db.close()
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/purchases", headers=h).json() == []
    assert client.get(f"/api/purchases/{p['id']}/proof", headers=h).status_code == 404


# ---------- RedFlagDeals ----------

def test_parse_feed_is_safe_and_splits_titles():
    entries = dealfeed.parse_feed(fixture_html("rfd_hot_deals.xml"))
    assert len(entries) == 5
    assert all("root:" not in e["title"] for e in entries)  # external entity not resolved
    tag, text, price = dealfeed.split_title(entries[0]["title"])
    assert tag == "Best Buy" and price == 39999 and text.startswith("Sony")


def test_feed_matches_wishlist_dedupes_and_correlates(client, pages, sent):
    client.patch("/api/settings", json={"notify_urls": ["ntfys://ntfy.sh/me"]})
    xm6 = client.post("/api/items/from-url", json={"url": "https://www.bestbuy.ca/xm6"}).json()
    drill = client.post("/api/items", json={"name": "DEWALT 20V MAX Cordless Drill Kit", "brand": "DEWALT",
                                            "model": "DCD777C2"}).json()
    from pricewatch.db import session_scope
    db = session_scope()
    stats = dealfeed.ingest(db, dealfeed.parse_feed(fixture_html("rfd_hot_deals.xml")))
    db.close()
    assert stats["new"] == 5
    titles = [a.title for a in sent if a.rule_type == "deal_feed"]
    assert len(titles) == 2  # XM6 once (second thread collapsed), drill once; XM5 and kettle ignored
    assert stats["duplicates"] == 1
    deals = client.get(f"/api/items/{xm6['id']}/deals").json()
    assert len(deals) == 2 and deals[0]["tracked_source_id"] == xm6["sources"][0]["id"]  # already tracked at Best Buy
    assert client.get(f"/api/items/{drill['id']}/deals").json()[0]["retailer_domain"] == "costco.ca"
    body = next(a.body for a in sent if "Sony" in a.body)
    assert "already track Best Buy Canada" in body
    # re-ingesting the same feed adds nothing
    db = session_scope()
    assert dealfeed.ingest(db, dealfeed.parse_feed(fixture_html("rfd_hot_deals.xml")))["new"] == 0
    db.close()
