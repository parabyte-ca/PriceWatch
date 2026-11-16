"""Security pass: no fetching the home network, security headers."""

import httpx
import pytest

from pricewatch import netguard
from pricewatch.fetch.http import PoliteFetcher


@pytest.mark.parametrize("url", [
    "http://192.168.2.15:8086/api/items", "http://10.0.0.1/", "http://127.0.0.1:8080/", "http://[::1]/",
    "http://169.254.169.254/latest/meta-data/", "http://localhost/", "http://truenas.local/", "http://nas/",
    "file:///etc/passwd", "gopher://x.ca/", "http://u:p@shop.ca/", "http://[::ffff:10.0.0.1]/",
])
def test_blocked(url):
    with pytest.raises(netguard.BlockedURL):
        netguard.check(url)


def test_public_allowed():
    netguard.check("https://www.bestbuy.ca/en-ca/product/x/1")
    netguard.check("https://8.8.8.8/")


async def test_fetcher_blocks_private_and_redirects_to_private():
    def handler(req: httpx.Request):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"Location": "http://192.168.2.1/admin"})

    f = PoliteFetcher("t", min_interval=0, jitter=0, transport=httpx.MockTransport(handler))
    r = await f.fetch("http://192.168.2.1/")
    assert r.outcome == "error" and "not a public address" in r.error
    r = await f.fetch("https://shop.example.ca/p")
    assert r.outcome == "error" and "192.168.2.1" in r.error  # the redirect was refused, not followed
    await f.close()


def test_api_refuses_private_urls_and_push_endpoints(client):
    r = client.post("/api/items/from-url", json={"url": "http://192.168.2.1/admin"})
    assert r.status_code == 422 and "public store pages" in r.json()["detail"]
    assert client.post("/api/preview", json={"url": "http://localhost:8086/api/items"}).status_code == 422
    item = client.post("/api/items", json={"name": "x"}).json()
    assert client.post(f"/api/items/{item['id']}/sources", json={"url": "http://10.1.2.3/p"}).status_code == 422
    imp = client.post("/api/import", json={"text": "http://nas.local/x\nLEGO Titanic"}).json()
    assert len(imp["created"]) == 1 and len(imp["skipped"]) == 1
    sub = {"endpoint": "https://192.168.2.15/push", "keys": {"p256dh": "B" * 87, "auth": "A" * 22}}
    assert client.post("/api/push/subscribe", json=sub).status_code == 422
    retailers = [r["domain"] for r in client.get("/api/retailers").json()]
    assert "192.168.2.1" not in retailers and "localhost" not in retailers  # nothing saved


def test_security_headers(client):
    r = client.get("/healthz")
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert client.get("/api/items").headers["Cache-Control"] == "no-store"


def test_override_for_local_fixture_server(monkeypatch):
    from pricewatch.config import get_settings

    monkeypatch.setattr(get_settings(), "allow_private_urls", True)
    netguard.check("http://fixtures:8000/jsonld_offer.html")


def test_members_cannot_send_notifications_to_the_home_network(client):
    from pricewatch.db import session_scope
    from pricewatch.models import User
    from pricewatch.services import users as users_svc

    r = client.post("/api/users", json={"username": "kid", "display_name": "Kid", "password": "password123"}).json()
    db = session_scope()
    tok = users_svc.new_api_token(db.get(User, r["id"]))
    db.commit()
    db.close()
    h = {"Authorization": f"Bearer {tok}"}
    lan = {"notify_urls": ["json://192.168.2.15:8123/hook"]}
    assert client.patch("/api/settings", json=lan, headers=h).status_code == 422
    assert client.patch("/api/settings", json={"notify_urls": ["ntfys://ntfy.sh/kid-topic"]}, headers=h).status_code == 200
    # the admin may (Home Assistant or a LAN ntfy)
    assert client.patch("/api/settings", json={"notify_urls": ["json://192.168.2.15:8123/hook"]}).status_code == 200


def test_edit_item_details_and_move_between_lists(client):
    item = client.post("/api/items", json={"name": "Hoodie"}).json()
    other = client.post("/api/lists", json={"name": "Gifts"}).json()
    r = client.patch(f"/api/items/{item['id']}", json={"name": "Raptors Hoodie", "brand": "Nike", "model": "DX1234",
                                                       "gtin": "4548736158566", "list_id": other["id"]})
    assert r.status_code == 200
    j = r.json()
    assert (j["name"], j["brand"], j["model"], j["gtin"], j["list_id"]) == \
        ("Raptors Hoodie", "Nike", "DX1234", "4548736158566", other["id"])
    assert client.patch(f"/api/items/{item['id']}", json={"gtin": "12ab"}).status_code == 422
    assert client.patch(f"/api/items/{item['id']}", json={"list_id": 9999}).status_code == 403


def test_family_share_link(client):
    lst = client.post("/api/lists", json={"name": "Kids", "occasion": "Christmas", "recipient": "Sam",
                                          "budget_cents": 30000}).json()
    a = client.post("/api/items", json={"name": "LEGO Titanic", "list_id": lst["id"], "notes": "secret note"}).json()
    client.post("/api/items", json={"name": "Plush", "list_id": lst["id"]})
    client.post(f"/api/items/{a['id']}/purchases", json={"retailer_name": "Costco", "price_cents": 12345})
    on = client.post(f"/api/lists/{lst['id']}/share", json={}).json()
    link = on["share_link"]
    assert on["share_on"] and link.startswith("/shared/")
    token = link.split("/")[-1]
    # opened without signing in
    client.cookies.clear()
    pub = client.get(f"/api/shared/{token}").json()
    assert pub["name"] == "Kids" and pub["recipient"] == "Sam"
    body = str(pub)
    assert "secret note" not in body and "12345" not in body and "30000" not in body and "budget" not in body
    assert {i["name"]: i["bought"] for i in pub["items"]} == {"LEGO Titanic": True, "Plush": False}
    assert client.get("/api/shared/wrongtoken123").status_code == 404
    off = client.delete(f"/api/lists/{lst['id']}/share").json()
    assert not off["share_on"] and client.get(f"/api/shared/{token}").status_code == 404
    client.post(f"/api/lists/{lst['id']}/share", json={})
    token = client.get("/api/lists").json()[-1]["share_link"].split("/")[-1]
    # with sign-in on: the shared list opens without an account, nothing else does
    from pricewatch.config import get_settings
    s = get_settings()
    old, s.auth_mode = s.auth_mode, "password"
    try:
        client.cookies.clear()
        assert client.get(f"/api/shared/{token}").status_code == 200
        assert client.get("/api/items").status_code == 401
        assert client.get("/api/lists").status_code == 401
    finally:
        s.auth_mode = old
