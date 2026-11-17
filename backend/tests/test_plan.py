"""v1.5.0: Black Friday plan, morning checklist and live-day digest."""

from datetime import UTC, date, datetime, timedelta

from pricewatch.models import Alert, Observation, SourceLink, User
from pricewatch.services import deals, plan
from pricewatch.services.retailers import get_or_create_retailer
from pricewatch.timeutil import utcnow


def _item_with_prices(client, db_session, name, prices):
    item = client.post("/api/items", json={"name": name}).json()
    r = get_or_create_retailer(db_session, "https://www.bestbuy.ca/x")
    src = SourceLink(item_id=item["id"], retailer_id=r.id, url=f"https://www.bestbuy.ca/{item['id']}", status="confirmed",
                     last_price_cents=prices[-1][1] if prices else None)
    db_session.add(src)
    db_session.flush()
    for at, price in prices:
        db_session.add(Observation(item_id=item["id"], source_link_id=src.id, observed_at=at, price_cents=price,
                                   method="search"))
    db_session.commit()
    return item


def test_plan_save_and_build(client, db_session):
    now = utcnow()
    a = _item_with_prices(client, db_session, "Nintendo Switch 2", [(now, 59999)])
    b = client.post("/api/items", json={"name": "Air fryer"}).json()
    r = client.put("/api/plan", json={"budget_cents": 100000, "item_ids": [a["id"], b["id"], 99999]})
    assert r.status_code == 200
    p = r.json()
    assert [x["item_id"] for x in p["items"]] == [a["id"], b["id"]]  # unknown id dropped, order kept
    assert p["items"][0]["price_cents"] == 59999 and p["items"][1]["when"] == "unknown"
    assert p["total_now_cents"] >= 59999 and p["left_cents"] == 100000 - p["total_now_cents"]
    assert client.get("/api/plan").json()["budget_cents"] == 100000
    assert {e["name"] for e in p["events"]} >= {"Black Friday"}


def test_live_day():
    assert plan.live_day(date(2026, 11, 27)) == "Black Friday"
    assert plan.live_day(date(2026, 11, 17)) is None


def test_checklist_sent_once_on_black_friday(client, db_session):
    a = _item_with_prices(client, db_session, "Nintendo Switch 2", [(utcnow(), 59999)])
    client.put("/api/plan", json={"item_ids": [a["id"]]})
    early = datetime(2026, 11, 27, 9, 0, tzinfo=UTC)  # 04:00 Toronto
    assert plan.send_checklists(db_session, early) == 0
    later = datetime(2026, 11, 27, 14, 0, tzinfo=UTC)
    assert plan.send_checklists(db_session, later) == 1
    assert plan.send_checklists(db_session, later + timedelta(minutes=20)) == 0  # deduped
    al = db_session.query(Alert).filter(Alert.rule_type == "plan").one()
    assert "Nintendo Switch 2" in al.body and al.title == "Your Black Friday plan"
    assert plan.send_checklists(db_session, datetime(2026, 11, 17, 14, tzinfo=UTC)) == 0


def test_live_digest_only_recent_drops(client, db_session):
    now = utcnow()
    _item_with_prices(client, db_session, "TV", [(now - timedelta(days=3), 100000), (now - timedelta(minutes=10), 80000)])
    _item_with_prices(client, db_session, "Kettle", [(now - timedelta(days=3), 10000), (now - timedelta(hours=5), 8000)])
    assert deals.live_digest(db_session, now) == 1
    al = db_session.query(Alert).filter(Alert.rule_type == "live").one()
    assert "TV" in al.body and "Kettle" not in al.body
    assert deals.live_digest(db_session, now) == 0
    assert db_session.query(User).count() >= 1


def test_live_day_searches_categories_more_often(db_session, monkeypatch):
    from pricewatch.models import DealCategory

    cat = DealCategory(name="TVs", active=True, last_search_at=utcnow() - timedelta(hours=7))
    monkeypatch.setattr(plan, "live_day", lambda today=None: None)
    monkeypatch.setattr(deals, "_sale_season", lambda: True)
    assert not deals.search_due(cat, {"sale_mode": False})
    monkeypatch.setattr(plan, "live_day", lambda today=None: "Black Friday")
    assert deals.search_due(cat, {"sale_mode": False})


def test_live_refresh_keeps_the_monthly_limit(db_session, monkeypatch):
    from pricewatch.services import discovery, settings_store

    class P:
        name = "serpapi"
    settings_store.update(db_session, {"serp_monthly_limit": 100})
    monkeypatch.setattr(discovery, "month_usage", lambda db, name: 100)
    assert not discovery._under_limit(db_session, P())
    monkeypatch.setattr(discovery, "month_usage", lambda db, name: 99)
    assert discovery._under_limit(db_session, P())
