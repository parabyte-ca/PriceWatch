from datetime import datetime

from pricewatch.models import Alert, Item
from pricewatch.services import alerts, settings_store


def test_dedup_same_key(db_session, monkeypatch):
    sent = []
    monkeypatch.setattr(alerts, "send_all", lambda urls, a: (sent.append(a.title) or True, None))
    settings_store.update(db_session, {"notify_urls": ["ntfy://ntfy.sh/test"]})
    item = Item(name="X")
    db_session.add(item)
    db_session.commit()
    a1 = alerts.raise_alert(db_session, item=item, rule="buy", key="buy:1:100", title="t", body="b")
    a2 = alerts.raise_alert(db_session, item=item, rule="buy", key="buy:1:100", title="t", body="b")
    a3 = alerts.raise_alert(db_session, item=item, rule="buy", key="buy:1:90", title="t", body="b")
    assert a1.status == "sent" and a2 is None and a3.status == "sent"
    assert len(sent) == 2


def test_no_urls_logs(db_session):
    a = alerts.raise_alert(db_session, item=None, rule="drop_pct", key="k1", title="t", body="b")
    assert a.status == "logged"


def test_quiet_hours_window():
    cfg = {"quiet_hours_enabled": True, "quiet_hours_start": "22:00", "quiet_hours_end": "07:00"}
    # America/Toronto is UTC-5 in November
    assert alerts.in_quiet_hours(cfg, datetime(2026, 11, 20, 4, 0))       # 23:00 local
    assert alerts.in_quiet_hours(cfg, datetime(2026, 11, 20, 11, 30))     # 06:30 local
    assert not alerts.in_quiet_hours(cfg, datetime(2026, 11, 20, 12, 30))  # 07:30 local
    cfg2 = {"quiet_hours_enabled": True, "quiet_hours_start": "01:00", "quiet_hours_end": "05:00"}
    assert alerts.in_quiet_hours(cfg2, datetime(2026, 11, 20, 8, 0))     # 03:00 local
    assert not alerts.in_quiet_hours({"quiet_hours_enabled": False}, datetime(2026, 11, 20, 4, 0))


def test_deferred_then_flushed(db_session, monkeypatch):
    monkeypatch.setattr(alerts, "send_all", lambda urls, a: (True, None))
    settings_store.update(db_session, {"notify_urls": ["ntfy://ntfy.sh/test"]})
    monkeypatch.setattr(alerts, "in_quiet_hours", lambda cfg, now=None: True)
    a = alerts.raise_alert(db_session, item=None, rule="drop_pct", key="k2", title="t", body="b")
    assert a.status == "deferred"
    t = alerts.raise_alert(db_session, item=None, rule="buy", key="k3", title="t", body="b")
    assert t.status == "sent"  # buy alerts bypass quiet hours by default
    assert alerts.flush_deferred(db_session) == 0
    monkeypatch.setattr(alerts, "in_quiet_hours", lambda cfg, now=None: False)
    assert alerts.flush_deferred(db_session) == 1
    assert db_session.get(Alert, a.id).status == "sent"


def test_mask_url():
    assert settings_store.mask_url("ntfys://user:pass@ntfy.example.ca/topic") == "ntfys://ntfy.example.ca/***"


def test_parse_ntfy_urls():
    assert alerts.parse_ntfy("ntfy://mytopic") == {"base": "https://ntfy.sh", "topic": "mytopic", "auth": None}
    assert alerts.parse_ntfy("ntfys://ntfy.example.ca/deals")["base"] == "https://ntfy.example.ca"
    assert alerts.parse_ntfy("ntfys://u:p@ntfy.example.ca/deals")["auth"] == ("basic", "u", "p")
    assert alerts.parse_ntfy("ntfys://tk_abc@ntfy.example.ca/deals")["auth"] == ("token", "tk_abc", None)
    assert alerts.parse_ntfy("json://x/y") is None


def test_ntfy_payload_has_actions(db_session, monkeypatch):
    import httpx

    from pricewatch.config import get_settings
    from pricewatch.models import Alert

    monkeypatch.setattr(get_settings(), "public_url", "https://pw.example.ca")
    seen = {}

    def handler(req):
        import json
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={})

    alert = Alert(item_id=7, rule_type="buy", dedup_key="x", title="BUY NOW: X", body="b", url="https://shop.ca/x")
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        alerts.send_ntfy(alerts.parse_ntfy("ntfys://ntfy.sh/t"), alert, c)
    assert seen["topic"] == "t" and seen["click"] == "https://shop.ca/x"
    labels = [a["label"] for a in seen["actions"]]
    assert labels == ["Open store", "Bought", "Snooze 24h"]
    assert seen["actions"][0]["url"] == "https://shop.ca/x" and seen["actions"][1]["method"] == "POST"
    from urllib.parse import unquote
    token = seen["actions"][2]["url"].rsplit("/", 1)[-1]
    assert alerts.read_action_token(unquote(token))[:2] == (7, "snooze")
    token = seen["actions"][1]["url"].rsplit("/", 1)[-1]
    assert alerts.read_action_token(unquote(token))[:2] == (7, "bought")


def test_one_tap_bought_records_the_purchase(client, db_session):
    from pricewatch.models import Purchase, SourceLink
    from pricewatch.services.retailers import get_or_create_retailer

    item = client.post("/api/items", json={"name": "Nintendo Switch 2"}).json()
    r = get_or_create_retailer(db_session, "https://www.costco.ca/x")
    db_session.add(SourceLink(item_id=item["id"], retailer_id=r.id, url="https://www.costco.ca/x", status="confirmed",
                              last_price_cents=59999))
    db_session.commit()
    token = alerts.action_token(item["id"], "bought", None)
    page = client.get(f"/api/actions/{token}")
    assert "Yes, I bought it" in page.text and db_session.query(Purchase).count() == 0  # a preview records nothing
    done = client.post(f"/api/actions/{token}")
    assert "Recorded" in done.text and "599.99" in done.text
    p = db_session.query(Purchase).one()
    assert p.price_cents == 59999
    assert "Already recorded" in client.post(f"/api/actions/{token}").text


def test_digest_lists_items_and_pending(db_session):
    from pricewatch.models import Alert
    db_session.add(Alert(rule_type="drop_pct", dedup_key="d1", title="Price drop 12%: X", body="b", status="digest"))
    db_session.commit()
    title, body = alerts.build_digest(db_session)
    assert title.startswith("PriceWatch digest")
    assert "Price drop 12%: X" in body
