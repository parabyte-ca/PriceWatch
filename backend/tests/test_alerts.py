from datetime import datetime

from pricewatch.models import Alert, Item
from pricewatch.services import alerts, settings_store


def test_dedup_same_key(db_session, monkeypatch):
    sent = []
    monkeypatch.setattr(alerts, "send_apprise", lambda urls, t, b: (sent.append(t) or True, None))
    settings_store.update(db_session, {"notify_urls": ["ntfy://ntfy.sh/test"]})
    item = Item(name="X")
    db_session.add(item)
    db_session.commit()
    a1 = alerts.raise_alert(db_session, item=item, rule="target", key="target:1:100", title="t", body="b")
    a2 = alerts.raise_alert(db_session, item=item, rule="target", key="target:1:100", title="t", body="b")
    a3 = alerts.raise_alert(db_session, item=item, rule="target", key="target:1:90", title="t", body="b")
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
    monkeypatch.setattr(alerts, "send_apprise", lambda urls, t, b: (True, None))
    settings_store.update(db_session, {"notify_urls": ["ntfy://ntfy.sh/test"]})
    monkeypatch.setattr(alerts, "in_quiet_hours", lambda cfg, now=None: True)
    a = alerts.raise_alert(db_session, item=None, rule="drop_pct", key="k2", title="t", body="b")
    assert a.status == "deferred"
    t = alerts.raise_alert(db_session, item=None, rule="target", key="k3", title="t", body="b")
    assert t.status == "sent"  # target hits bypass quiet hours by default
    assert alerts.flush_deferred(db_session) == 0
    monkeypatch.setattr(alerts, "in_quiet_hours", lambda cfg, now=None: False)
    assert alerts.flush_deferred(db_session) == 1
    assert db_session.get(Alert, a.id).status == "sent"


def test_mask_url():
    assert settings_store.mask_url("ntfys://user:pass@ntfy.example.ca/topic") == "ntfys://ntfy.example.ca/***"
