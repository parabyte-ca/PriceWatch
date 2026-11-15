"""Household accounts: separate lists and rules, shared lists by friend code, per-person alerts."""

from datetime import timedelta

import pytest

from pricewatch.db import session_scope
from pricewatch.models import ListInvite, User
from pricewatch.services import alerts
from pricewatch.services import users as users_svc
from pricewatch.timeutil import utcnow


def make_user(client, username, name):
    r = client.post("/api/users", json={"username": username, "display_name": name, "password": "password123"})
    assert r.status_code == 201, r.text
    db = session_scope()
    token = users_svc.new_api_token(db.get(User, r.json()["id"]))
    db.commit()
    db.close()
    return {"Authorization": f"Bearer {token}"}, r.json()["id"]


@pytest.fixture
def household(client):
    alan, alan_id = make_user(client, "alan", "Alan")
    sam, sam_id = make_user(client, "sam", "Sam")
    return {"alan": alan, "sam": sam, "alan_id": alan_id, "sam_id": sam_id}


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(alerts, "send_all", lambda urls, a: (out.append(a) or True, None))
    return out


def test_separate_lists_and_rules(client, household):
    a, s = household["alan"], household["sam"]
    client.post("/api/items", json={"name": "Drill"}, headers=a)
    client.post("/api/items", json={"name": "Stand mixer"}, headers=s)
    assert [i["name"] for i in client.get("/api/items", headers=a).json()] == ["Drill"]
    assert [i["name"] for i in client.get("/api/items", headers=s).json()] == ["Stand mixer"]
    # per-person settings
    client.patch("/api/settings", json={"province": "QC", "notify_urls": ["ntfys://ntfy.sh/sam"]}, headers=s)
    assert client.get("/api/settings", headers=a).json()["province"] == "ON"
    assert client.get("/api/settings", headers=s).json()["province"] == "QC"
    # household settings are admin-only
    assert client.patch("/api/settings", json={"fake_sale_pct": 9}, headers=s).status_code == 403
    assert client.patch("/api/settings", json={"fake_sale_pct": 9}).status_code == 200  # admin (none mode)


def test_cannot_touch_someone_elses_item(client, household):
    item = client.post("/api/items", json={"name": "Drill"}, headers=household["alan"]).json()
    s = household["sam"]
    assert client.get(f"/api/items/{item['id']}", headers=s).status_code == 404
    assert client.patch(f"/api/items/{item['id']}", json={"name": "x"}, headers=s).status_code == 404
    assert client.delete(f"/api/items/{item['id']}", headers=s).status_code == 404
    r = client.post(f"/api/items/{item['id']}/manual", json={"store": "X", "price_cents": 1}, headers=s)
    assert r.status_code == 404


def test_shared_list_by_friend_code(client, household, sent):
    a, s = household["alan"], household["sam"]
    shared = client.post("/api/lists", json={"name": "Gifts for the kids"}, headers=a).json()
    code = client.post(f"/api/lists/{shared['id']}/invites", json={"role": "editor"}, headers=a).json()["code"]
    assert code.startswith("PW-") and len(code) == 12
    assert client.post(f"/api/lists/{shared['id']}/invites", headers=s).status_code == 403  # not the owner
    joined = client.post("/api/lists/join", json={"code": code.lower().replace("-", " ")}, headers=s).json()
    assert joined["name"] == "Gifts for the kids" and joined["role"] == "editor"
    assert client.post("/api/lists/join", json={"code": code}, headers=s).status_code == 400  # single use

    item = client.post("/api/items", json={"name": "LEGO set", "list_id": shared["id"], "target_price_cents": 10000},
                       headers=s).json()
    assert item["added_by"] == household["sam_id"]
    names_alan = [i["name"] for i in client.get("/api/items", headers=a).json()]
    assert "LEGO set" in names_alan

    # both members get their own BUY alert; Alan snoozes, Sam still gets the next one
    for h, url in ((a, "ntfys://ntfy.sh/alan"), (s, "ntfys://ntfy.sh/sam")):
        client.patch("/api/settings", json={"notify_urls": [url]}, headers=h)
    client.post(f"/api/items/{item['id']}/manual", json={"store": "Costco", "price_cents": 9999}, headers=s)
    assert sorted(x.user_id for x in sent if x.rule_type == "buy") == sorted([household["alan_id"], household["sam_id"]])
    client.post(f"/api/items/{item['id']}/snooze", json={"hours": 24}, headers=a)
    sent.clear()
    client.post(f"/api/items/{item['id']}/manual", json={"store": "Costco", "price_cents": 9499}, headers=s)
    assert [x.user_id for x in sent if x.rule_type == "buy"] == [household["sam_id"]]
    assert client.get(f"/api/items/{item['id']}", headers=a).json()["summary"]["snoozed"] is True
    assert client.get(f"/api/items/{item['id']}", headers=s).json()["summary"]["snoozed"] is False
    # each person sees only their own alerts
    assert all(x["title"] for x in client.get("/api/alerts", headers=s).json())

    # leaving removes access without deleting history
    client.delete(f"/api/lists/{shared['id']}/members/{household['sam_id']}", headers=s)
    assert client.get(f"/api/items/{item['id']}", headers=s).status_code == 404
    assert client.get(f"/api/items/{item['id']}/history", headers=a).json()["series"]


def test_viewer_is_read_only(client, household):
    a, s = household["alan"], household["sam"]
    lst = client.post("/api/lists", json={"name": "Peek"}, headers=a).json()
    item = client.post("/api/items", json={"name": "Camera", "list_id": lst["id"]}, headers=a).json()
    code = client.post(f"/api/lists/{lst['id']}/invites", json={"role": "viewer"}, headers=a).json()["code"]
    client.post("/api/lists/join", json={"code": code}, headers=s)
    assert client.get(f"/api/items/{item['id']}", headers=s).status_code == 200
    assert client.patch(f"/api/items/{item['id']}", json={"name": "x"}, headers=s).status_code == 403
    assert client.post("/api/items", json={"name": "y", "list_id": lst["id"]}, headers=s).status_code == 403


def test_expired_code_rejected(client, household):
    a, s = household["alan"], household["sam"]
    lst = client.post("/api/lists", json={"name": "Old"}, headers=a).json()
    code = client.post(f"/api/lists/{lst['id']}/invites", headers=a).json()["code"]
    db = session_scope()
    inv = db.query(ListInvite).one()
    assert code not in (inv.code_hash,)  # stored hashed
    inv.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    db.close()
    assert client.post("/api/lists/join", json={"code": code}, headers=s).status_code == 400


def test_members_cannot_manage_people(client, household):
    s = household["sam"]
    assert client.post("/api/users", json={"username": "x1", "display_name": "X", "password": "password123"},
                       headers=s).status_code == 403
    assert client.patch(f"/api/users/{household['alan_id']}", json={"role": "member"}, headers=s).status_code == 403
    assert client.patch(f"/api/users/{household['sam_id']}", json={"display_name": "Samantha"}, headers=s).status_code == 200
    people = client.get("/api/users", headers=s).json()
    assert all(set(p) == {"id", "display_name"} for p in people)  # members see names only


def test_many_people_and_a_list_shared_with_several(client, sent):
    """No two-person assumption: six people, one list shared with four of them, each alerted separately."""
    people = [make_user(client, f"user{i}", f"Person {i}") for i in range(6)]
    owner_h, owner_id = people[0]
    lst = client.post("/api/lists", json={"name": "Family gifts"}, headers=owner_h).json()
    for h, _ in people[1:4]:
        code = client.post(f"/api/lists/{lst['id']}/invites", headers=owner_h).json()["code"]
        assert client.post("/api/lists/join", json={"code": code}, headers=h).status_code == 200
    detail = next(x for x in client.get("/api/lists", headers=owner_h).json() if x["id"] == lst["id"])
    assert len(detail["members"]) == 4
    item = client.post("/api/items", json={"name": "Board game", "list_id": lst["id"], "target_price_cents": 5000},
                       headers=people[2][0]).json()
    for i, (h, _) in enumerate(people):
        client.patch("/api/settings", json={"notify_urls": [f"ntfys://ntfy.sh/p{i}"]}, headers=h)
    client.post(f"/api/items/{item['id']}/manual", json={"store": "Indigo", "price_cents": 4999}, headers=people[1][0])
    notified = {a.user_id for a in sent if a.rule_type == "buy"}
    assert notified == {uid for _, uid in people[:4]}  # members only; persons 4 and 5 are not on the list
    assert client.get(f"/api/items/{item['id']}", headers=people[5][0]).status_code == 404
    assert len(client.get("/api/users").json()) == 7  # admin plus six
