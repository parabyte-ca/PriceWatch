from pricewatch.config import get_settings


def test_password_mode(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "auth_mode", "password")
    monkeypatch.setattr(s, "admin_password", "correct horse")
    assert client.get("/api/items").status_code == 401
    assert client.get("/metrics").status_code == 401
    assert client.get("/healthz").status_code == 200
    assert client.post("/api/auth/login", json={"password": "nope"}).status_code == 401
    assert client.post("/api/auth/login", json={"password": "correct horse"}).status_code == 200
    assert client.get("/api/items").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/items").status_code == 401
