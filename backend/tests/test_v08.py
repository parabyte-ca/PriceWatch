"""v0.8.0: Boxing Week mode, pre-event backup, readiness, basket optimiser, Claude match check."""

from datetime import datetime

from pricewatch.services import events

from .test_discovery import fake  # noqa: F401  (fixture)


def _cfg(**kw):
    from pricewatch.services.settings_store import DEFAULTS

    return {**DEFAULTS, **kw}


def _utc(local: datetime) -> datetime:
    return local.replace(tzinfo=events.tz()).astimezone(events.ZoneInfo("UTC")).replace(tzinfo=None)


def test_sale_modes():
    cfg = _cfg()
    assert events.sale_mode(cfg, _utc(datetime(2026, 11, 27, 12))) == "Black Friday"
    assert events.sale_mode(cfg, _utc(datetime(2026, 12, 28, 9))) == "Boxing Week"
    assert events.sale_mode(cfg, _utc(datetime(2026, 12, 10, 9))) is None
    assert events.blackfriday_active(cfg, _utc(datetime(2026, 12, 26, 0, 30)))
    assert not events.blackfriday_active(_cfg(boxingweek_mode=False), _utc(datetime(2026, 12, 28, 9)))


async def test_pre_event_backup(db_session, monkeypatch, tmp_path):
    from pricewatch import backup, scheduler

    made = []
    monkeypatch.setattr(backup, "vacuum_into", lambda dest, keep: (made.append(dest), dest.write_text("x"))[0])
    monkeypatch.setattr(events, "local_now", lambda now=None: datetime(2026, 11, 25, 21, 0, tzinfo=events.tz()))
    from pricewatch.config import get_settings
    monkeypatch.setattr(type(get_settings()), "db_url", property(lambda self: "sqlite:///x"))
    await scheduler.pre_event_backup()
    await scheduler.pre_event_backup()  # once only
    assert len(made) == 1 and made[0].name == "pre-blackfriday-2026.sqlite"
    monkeypatch.setattr(events, "local_now", lambda now=None: datetime(2026, 11, 20, 9, 0, tzinfo=events.tz()))
    made[0].unlink()
    await scheduler.pre_event_backup()
    assert len(made) == 1  # too early


def _source(db, item, domain, price, shipping=None):
    from pricewatch.models import Retailer, SourceLink

    r = db.query(Retailer).filter_by(domain=domain).one()
    s = SourceLink(item_id=item.id, retailer_id=r.id, url=f"https://www.{domain}/p/{item.id}", status="confirmed",
                   last_price_cents=price, last_shipping_cents=shipping, last_in_stock=True, last_condition="new",
                   last_seller_type="first_party", channel="online")
    db.add(s)
    return s


def test_basket_consolidates_for_free_shipping(client):
    from pricewatch.db import session_scope
    from pricewatch.models import Item, Retailer
    from pricewatch.services import basket

    db = session_scope()
    lst = client.get("/api/lists").json()[0]["id"]
    staples = db.query(Retailer).filter_by(domain="staples.ca").one()
    staples.free_shipping_threshold_cents, staples.default_shipping_cents = 4500, 999
    cc = db.query(Retailer).filter_by(domain="canadacomputers.com").one()
    cc.free_shipping_threshold_cents, cc.default_shipping_cents = 10000, 1499
    a = Item(name="Mouse", list_id=lst)
    b = Item(name="Keyboard", list_id=lst)
    db.add_all([a, b])
    db.flush()
    # alone, each is a bit cheaper at Canada Computers, but each order would pay shipping there
    _source(db, a, "staples.ca", 3000)
    _source(db, a, "canadacomputers.com", 2900)
    _source(db, b, "staples.ca", 2500)
    _source(db, b, "canadacomputers.com", 2400)
    db.commit()
    plan = client.post("/api/basket", json={"item_ids": [a.id, b.id]}).json()
    assert plan["method"] == "exact"
    assert [s["retailer"] for s in plan["stores"]] == ["Staples Canada"]
    assert plan["stores"][0]["shipping_cents"] == 0
    assert plan["total_cents"] == round(5500 * 1.13)
    assert plan["saving_cents"] > 0 and plan["missing"] == []
    # local search path agrees on a forced large basket
    monkey_limit = basket.EXACT_LIMIT
    basket.EXACT_LIMIT = 1
    try:
        plan2 = client.post("/api/basket", json={"item_ids": [a.id, b.id]}).json()
        assert plan2["method"] == "local search" and plan2["total_cents"] <= plan["separately_cents"]
    finally:
        basket.EXACT_LIMIT = monkey_limit
    db.close()


def test_basket_tip_and_missing(client):
    from pricewatch.db import session_scope
    from pricewatch.models import Item, Retailer

    db = session_scope()
    lst = client.get("/api/lists").json()[0]["id"]
    st = db.query(Retailer).filter_by(domain="staples.ca").one()
    st.free_shipping_threshold_cents, st.default_shipping_cents = 4500, 999
    a = Item(name="Cable", list_id=lst)
    b = Item(name="Nothing anywhere", list_id=lst)
    db.add_all([a, b])
    db.flush()
    _source(db, a, "staples.ca", 3500)
    db.commit()
    plan = client.post("/api/basket", json={"item_ids": [a.id, b.id]}).json()
    assert plan["missing"][0]["name"] == "Nothing anywhere"
    assert plan["stores"][0]["shipping_cents"] == 999 and plan["stores"][0]["free_shipping_gap_cents"] == 1000
    assert "add $10.00 more for free shipping" in plan["tips"][0]
    db.close()


def test_readiness_and_load_plan(client, monkeypatch):
    from pricewatch.db import session_scope
    from pricewatch.models import Item

    db = session_scope()
    lst = client.get("/api/lists").json()[0]["id"]
    for n in range(30):
        it = Item(name=f"Hot {n}", list_id=lst, hot=True, priority=1)
        db.add(it)
        db.flush()
        _source(db, it, "bestbuy.ca", 1000)
    db.add(Item(name="Hot with no store", list_id=lst, hot=True))
    db.commit()
    db.close()
    r = client.get("/api/admin/readiness").json()
    keys = {c["key"]: c for c in r["checks"]}
    assert keys["hot_sources"]["status"] == "warn" and "Hot with no store" in keys["hot_sources"]["detail"]
    assert keys["hot_count"]["status"] == "warn"
    assert keys["notify"]["status"] == "warn"
    bb = next(p for p in r["load"] if p["domain"] == "bestbuy.ca")
    # 25 items every 30 min + 5 every 2 h = 52.5 requests/h (tests run with no per-domain spacing)
    assert bb["requests_per_hour"] == 52.5 and bb["load_pct"] < 100
    from pricewatch.config import get_settings
    from pricewatch.services import readiness
    monkeypatch.setattr(get_settings(), "min_domain_interval", 20.0)
    monkeypatch.setattr(get_settings(), "domain_jitter", 0.3)
    db = session_scope()
    bb = next(p for p in readiness.load_plan(db, {}) if p["domain"] == "bestbuy.ca")
    db.close()
    assert bb["capacity_per_hour"] == 156.5  # 3600 / (20 s * 1.15)
    assert keys["load"]["status"] == "ok"
    assert r["overall"] in ("warn", "fail")
    assert client.get("/api/sale-mode").json()["windows"][1]["name"] == "Boxing Week"


async def test_llm_check_caches(db_session, monkeypatch):
    from pricewatch.models import LlmMatchCache
    from pricewatch.services import llm_match
    from pricewatch.services.matching import Candidate, ItemSpec

    calls = []

    def asker(model, item, listing):
        calls.append((model, item, listing))
        return llm_match.Verdict(same_product=False, confidence=0.9, reason="XM5 is the older generation")

    spec = ItemSpec(name="Sony WH-1000XM6", brand="Sony", model="WH-1000XM6")
    cand = Candidate(title="Sony WH-1000XM5 Wireless Headphones", url="https://x", merchant="Walmart")
    r1 = await llm_match.check(db_session, spec, cand, asker=asker)
    r2 = await llm_match.check(db_session, spec, cand, asker=asker)
    assert r1["same_product"] is False and r1["cached"] is False and r2["cached"] is True
    assert len(calls) == 1 and calls[0][0] == "claude-haiku-5-5"
    assert "Sony WH-1000XM5" in calls[0][2] and db_session.query(LlmMatchCache).count() == 1
    assert llm_match.in_band(0.792) and not llm_match.in_band(0.855) and not llm_match.in_band(0.711)
    assert llm_match.in_band(0.72) and not llm_match.in_band(0.9)
    assert llm_match.enabled(db_session) is False  # no key


def test_discovery_uses_llm_to_reject(client, fake, monkeypatch):  # noqa: F811
    from pricewatch.services import discovery, llm_match
    from pricewatch.services.matching import MatchResult

    real = discovery.match

    def fuzzy(spec, cand, threshold):
        r = real(spec, cand, threshold)
        return MatchResult(0.792, "fuzzy", r.accepted, list(r.reasons), list(r.exclusions)) if r.accepted else r

    async def check(db, spec, cand, asker=None):
        same = "bestbuy" in cand.url
        return {"same_product": same, "confidence": 0.8, "reason": "test", "model": "m", "cached": False}

    monkeypatch.setattr(discovery, "match", fuzzy)
    monkeypatch.setattr(llm_match, "enabled", lambda db: True)
    monkeypatch.setattr(llm_match, "check", check)
    item = client.post("/api/items", json={"name": "Sony WH-1000XM6 Wireless Headphones Black", "brand": "Sony",
                                           "model": "WH1000XM6/B"}).json()
    body = client.post(f"/api/items/{item['id']}/discover", json={}).json()
    st = {c["url"]: c for c in body["candidates"]}
    assert st["https://www.bestbuy.ca/en-ca/product/sony-wh-1000xm6/18930123"]["status"] == "suggested"
    staples = st["https://www.staples.ca/products/2988123-en-sony-wh1000xm6"]
    assert staples["status"] == "low match" and any("Claude" in x for x in staples["reasons"])
    assert body["added"] == 1



def test_llm_band_uses_real_matcher_scale():
    """Regression: the band was compared against 80 to 94 while the matcher reports 0 to 0.9, so it never fired."""
    from pricewatch.services import llm_match
    from pricewatch.services.matching import Candidate, ItemSpec, match

    spec = ItemSpec(name="LEGO Titanic Building Set", brand="LEGO")
    near = match(spec, Candidate(title="LEGO Titanic 10294 Building Kit", url="https://x"), 85)
    assert near.accepted and near.method == "fuzzy" and llm_match.in_band(near.confidence)
    exact = match(spec, Candidate(title="LEGO Titanic Building Set", url="https://x"), 85)
    assert not llm_match.in_band(exact.confidence)
    knock = match(spec, Candidate(title="Titanic Building Set Ship Model LEGO Compatible", url="https://x"), 85)
    assert not knock.accepted
