"""In-app updates: the app only writes a validated request; status comes from the agent's read-only folder."""

import json
from datetime import UTC, datetime

import pytest

from pricewatch.config import get_settings


@pytest.fixture
def folders(tmp_path, monkeypatch):
    s = get_settings()
    inbox, status = tmp_path / "upgrade", tmp_path / "upgrade-status"
    inbox.mkdir()
    status.mkdir()
    monkeypatch.setattr(s, "upgrade_dir", inbox)
    monkeypatch.setattr(s, "upgrade_status_dir", status)
    (status / "agent.json").write_text(json.dumps({"agent_version": "1", "last_run": datetime.now(UTC).isoformat()}))
    (status / "available.json").write_text(json.dumps({"tags": "v99.0.0,v0.5.0,v0.3.0", "checked_at": "x"}))
    (status / "upgrade.log").write_text("line 1\nline 2\n")
    return inbox, status


def test_status_and_request(client, folders):
    inbox, status = folders
    r = client.get("/api/admin/updates").json()
    assert r["agent_online"] and r["latest"] == "99.0.0" and r["update_available"]
    assert r["log"] == ["line 1", "line 2"]
    assert client.post("/api/admin/updates", json={"action": "update", "version": "1.2.3"}).status_code == 422
    assert client.post("/api/admin/updates", json={"action": "update", "version": "1;rm"}).status_code == 422
    assert client.post("/api/admin/updates", json={"action": "update", "version": "99.0.0"}).status_code == 202
    req = json.loads((inbox / "request.json").read_text())
    assert req["action"] == "update" and req["version"] == "99.0.0" and req["requested_by"] == "admin"
    assert client.post("/api/admin/updates", json={"action": "rollback"}).status_code == 409  # one at a time
    (inbox / "request.json").unlink()
    (status / "status.json").write_text(json.dumps({"state": "running"}))
    assert client.post("/api/admin/updates", json={"action": "check"}).status_code == 409


def test_members_cannot_update(client, folders):
    from pricewatch.db import session_scope
    from pricewatch.models import User
    from pricewatch.services import users as users_svc

    r = client.post("/api/users", json={"username": "kid", "display_name": "Kid", "password": "password123"})
    db = session_scope()
    tok = users_svc.new_api_token(db.get(User, r.json()["id"]))
    db.commit()
    db.close()
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/admin/updates", headers=h).status_code == 403
    assert client.post("/api/admin/updates", json={"action": "check"}, headers=h).status_code == 403


def test_not_mounted(client, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "upgrade_dir", tmp_path / "missing")
    monkeypatch.setattr(get_settings(), "upgrade_status_dir", tmp_path / "missing2")
    r = client.get("/api/admin/updates").json()
    assert r["agent_installed"] is False
    assert client.post("/api/admin/updates", json={"action": "check"}).status_code == 409


def test_progress_steps_estimate_and_history(client, folders):
    inbox, status = folders
    assert client.get("/api/admin/updates").json()["progress"]["state"] == "idle"
    # a past run sets the estimate (3 min 30 s + 30 s pick-up)
    (status / "history.jsonl").write_text(json.dumps({"action": "update", "state": "succeeded", "version": "0.13.0",
                                                      "started_at": "2026-11-15T10:00:00Z",
                                                      "finished_at": "2026-11-15T10:03:30Z"}) + "\n")
    (status / "status.json").write_text(json.dumps({"state": "running", "action": "update", "version": "0.14.0",
                                                     "started_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}))
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    (status / "upgrade.log").write_text(
        f"[update 2020-01-01T00:00:00Z] restarting containers\n"  # an older run: ignored
        f"[update {now}] current: v0.13.0, target: v0.14.0\n[update {now}] backing up the database\n"
        f"[update {now}] downloading v0.14.0\n[update {now}] verifying the signature\n")
    p = client.get("/api/admin/updates").json()["progress"]
    assert p["state"] == "running" and p["estimate_s"] == 240.0
    reached = [s["key"] for s in p["stages"] if s["reached"]]
    assert reached == ["requested", "started", "backup", "download"]
    assert p["last_line"] == "verifying the signature"
    (status / "status.json").write_text(json.dumps({"state": "failed", "action": "update", "version": "0.14.0",
                                                    "started_at": now, "finished_at": now, "rolled_back": "yes"}))
    with (status / "upgrade.log").open("a") as f:
        f.write(f"[update {now}] restarting containers\n[update {now}] waiting for the health check\n"
                f"[update {now}] health check failed; rolling back automatically\n")
    p = client.get("/api/admin/updates").json()["progress"]
    assert p["state"] == "failed" and p["failed_at"] == "health" and p["rolled_back"] is True
    assert client.get("/api/admin/updates").json()["history"][0]["version"] == "0.13.0"
