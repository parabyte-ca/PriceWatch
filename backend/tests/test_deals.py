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


def test_receipt_photo_read_then_save(client, db_session, monkeypatch):
    from types import SimpleNamespace as NS

    import anthropic

    from pricewatch.api import receipts
    from pricewatch.models import Purchase
    from pricewatch.services import claude

    item = client.post("/api/items", json={"name": "Nintendo Switch 2"}).json()
    monkeypatch.setattr(claude, "api_key", lambda: "sk-ant-test")

    class API:
        @property
        def messages(self):
            return self

        async def parse(self, **kw):
            assert f"{item['id']}: Nintendo Switch 2" in kw["messages"][0]["content"][1]["text"]
            return NS(usage=None, parsed_output=receipts.Receipt(is_receipt=True, store="Best Buy", date="2026-11-28",
                      lines=[receipts.ReceiptLine(name="NINTENDO SW2 CNSL", price_cents=59999, item_id=item["id"]),
                             receipts.ReceiptLine(name="HDMI CABLE", price_cents=1999, item_id=999999)]))

        async def close(self):
            pass

    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **kw: API())
    r = client.post("/api/purchases/receipt/read", json={"image_b64": "A" * 200}).json()
    assert r["domain"] == "bestbuy.ca" and [ln["item_id"] for ln in r["lines"]] == [item["id"], None]
    assert db_session.query(Purchase).count() == 0  # nothing recorded before Save
    s = client.post("/api/purchases/receipt/save", json={"store": "Best Buy", "date": "2026-11-28",
                                                          "lines": [{"item_id": item["id"], "price_cents": 59999}]})
    assert s.json() == {"saved": 1, "skipped": 0}
    p = db_session.query(Purchase).one()
    assert p.price_cents == 59999 and str(p.purchased_on) == "2026-11-28"


def test_category_forecast(client, db_session):
    from datetime import datetime

    from pricewatch.models import CategoryDeal, DealCategory

    cat_id = client.post("/api/deal-categories", json={"name": "TVs"}).json()["id"]
    cat = db_session.get(DealCategory, cat_id)
    assert deals.forecast(db_session, cat) is None  # not enough yet
    for day, pct in [(24, 40), (25, 35), (26, 30), (10, 15), (11, 10), (12, 20), (13, 15), (14, 12)]:
        db_session.add(CategoryDeal(category_id=cat_id, title="TV", url=f"https://x/{day}", price_cents=100 - pct,
                                    was_cents=100, source="rfd", seen_at=datetime(2026, 11, day, 17)))
    db_session.commit()
    f = deals.forecast(db_session, cat)
    assert f["best_window"] == "Black Friday week" and f["averages"]["Black Friday week"] == 35


def test_pay_with_text():
    from pricewatch.services.alerts import pay_with_text

    best = {"perks": [{"label": "Card", "percent": 5}], "perks_saving_cents": 2500}
    assert pay_with_text(best) == " Pay with: Card 5% ($25.00 back)."
    assert pay_with_text({}) == ""


def test_same_category_shared_between_people(client, db_session, monkeypatch):
    """A second person following "3D printers" gets the first person's deals, and one search serves both."""
    from pricewatch.models import CategoryDeal, DealCategory, User
    from pricewatch.serp.base import Candidate
    from pricewatch.timeutil import utcnow

    admin = db_session.query(User).first()
    other = User(username="amoote", display_name="Alan", role="member", password_hash="x")
    db_session.add(other)
    db_session.flush()
    a = DealCategory(user_id=admin.id, name="3D printers", min_discount_pct=20, last_search_at=utcnow())
    db_session.add(a)
    db_session.flush()
    db_session.add(CategoryDeal(category_id=a.id, title="Bambu A1", url="https://x.ca/a1", price_cents=30000,
                                was_cents=50000, source="google_shopping", seen_at=utcnow()))
    db_session.commit()

    b = DealCategory(user_id=other.id, name="3d  Printers", min_discount_pct=20)
    db_session.add(b)
    db_session.commit()
    assert deals.copy_from_others(db_session, b) == 1
    assert b.last_search_at is not None
    assert deals.copy_from_others(db_session, b) == 0  # no duplicates

    class P:
        name = "serpapi"

        async def on_sale(self, q, client):
            return [Candidate(title="Prusa MK4", url="https://x.ca/mk4", price_cents=60000,
                              extra={"old_price_cents": 100000})]
    monkeypatch.setattr("pricewatch.serp.get_provider", lambda name=None: P())
    asyncio.run(deals.search_category(db_session, a))
    urls = {d.url for d in db_session.query(CategoryDeal).filter(CategoryDeal.category_id == b.id)}
    assert urls == {"https://x.ca/a1", "https://x.ca/mk4"}


def test_category_more_page(client, db_session):
    """Home shows 6 deals and the total; the More page lists them all, sorted and a page at a time."""
    from pricewatch.models import CategoryDeal, DealCategory, User
    from pricewatch.timeutil import utcnow

    me = db_session.query(User).first()
    cat = DealCategory(user_id=me.id, name="TVs")
    db_session.add(cat)
    db_session.flush()
    for n in range(9):
        db_session.add(CategoryDeal(category_id=cat.id, title=f"TV {n}", url=f"https://x.ca/{n}",
                                    price_cents=100000 - n * 5000, was_cents=150000, source="google_shopping",
                                    seen_at=utcnow() - timedelta(hours=n)))
    db_session.add(CategoryDeal(category_id=cat.id, title="old", url="https://x.ca/old", price_cents=1, was_cents=2,
                                source="google_shopping", seen_at=utcnow() - timedelta(days=30)))
    db_session.commit()
    home = next(c for c in client.get("/api/deals/home").json()["categories"] if c["id"] == cat.id)
    assert len(home["deals"]) == 6 and home["total"] == 9
    page = client.get(f"/api/deal-categories/{cat.id}/deals?sort=price&limit=5").json()
    assert page["total"] == 9 and len(page["deals"]) == 5 and page["deals"][0]["title"] == "TV 8"
    rest = client.get(f"/api/deal-categories/{cat.id}/deals?sort=price&offset=5&limit=5").json()
    assert [d["title"] for d in rest["deals"]] == ["TV 3", "TV 2", "TV 1", "TV 0"]
    assert client.get(f"/api/deal-categories/{cat.id}/deals?sort=newest").json()["deals"][0]["title"] == "TV 0"
    assert client.get(f"/api/deal-categories/{cat.id}/deals?sort=bogus").status_code == 422
    assert client.get("/api/deal-categories/99999/deals").status_code == 404
