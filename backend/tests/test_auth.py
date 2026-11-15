from pricewatch.config import get_settings


def test_password_mode(client, monkeypatch):
    # in "none" mode requests act as the admin, who creates a household member
    r = client.post("/api/users", json={"username": "sam", "display_name": "Sam", "password": "correct horse"})
    assert r.status_code == 201
    s = get_settings()
    monkeypatch.setattr(s, "auth_mode", "password")
    assert client.get("/api/items").status_code == 401
    assert client.get("/metrics").status_code == 401
    assert client.get("/healthz").status_code == 200
    assert client.post("/api/auth/login", json={"username": "sam", "password": "nope"}).status_code == 401
    r = client.post("/api/auth/login", json={"username": "Sam", "password": "correct horse"})
    assert r.status_code == 200 and r.json()["user"]["display_name"] == "Sam"
    assert client.get("/api/items").status_code == 200
    assert client.get("/api/auth/me").json()["user"]["username"] == "sam"
    client.post("/api/auth/logout")
    assert client.get("/api/items").status_code == 401


def test_password_hashing():
    from pricewatch.services.users import hash_password, verify_password
    h = hash_password("s3cret-pass")
    assert h.startswith("scrypt$") and verify_password("s3cret-pass", h)
    assert not verify_password("wrong", h) and not verify_password("x", None)
