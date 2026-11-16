"""Order-email import: rule-based reading of forwarded confirmations, ownership, de-duplication, linking."""

from datetime import datetime
from email.message import EmailMessage

import pytest

from pricewatch.services import emailimport, events


def _email(html: str, sender="me@example.com", mid="<a1@example.com>", subject="Fwd: Your order") -> bytes:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = sender, "orders@example.com", subject, mid
    m["Date"] = "Fri, 20 Nov 2026 14:05:00 -0500"
    m.set_content("See HTML")
    m.add_alternative(html, subtype="html")
    return m.as_bytes()


BESTBUY = """<html><body>
<p>---------- Forwarded message ---------<br>From: Best Buy &lt;noreply@orders.bestbuy.ca&gt;</p>
<h2>Thanks for your order!</h2><p>Order Number: BBY01-806512345678</p>
<table>
<tr><td>Sony WH-1000XM6 Wireless Noise Cancelling Headphones - Black</td><td>$429.99</td></tr>
<tr><td>Insignia 6 ft. USB-C Cable</td><td>$19.99</td></tr>
<tr><td>Subtotal</td><td>$449.98</td></tr><tr><td>HST</td><td>$58.50</td></tr>
</table><p>bestbuy.ca</p></body></html>"""


@pytest.fixture
def setup(client, monkeypatch):
    monkeypatch.setattr(events, "local_now", lambda now=None: datetime(2026, 11, 20, 15, 0, tzinfo=events.tz()))
    item = client.post("/api/items", json={"name": "Sony WH-1000XM6 Wireless Headphones Black", "brand": "Sony",
                                           "model": "WH-1000XM6"}).json()
    other = client.post("/api/items", json={"name": "LEGO Titanic 10294"}).json()
    return item, other


def test_rules_record_purchase_with_protection(client, setup):
    from pricewatch.db import session_scope

    item, other = setup
    db = session_scope()
    row = emailimport.process(db, _email(BESTBUY), use_llm=False)
    assert row.retailer_domain == "bestbuy.ca" and row.order_ref == "BBY01-806512345678"
    assert row.status == "recorded" and len(row.lines) == 1
    assert row.lines[0]["item_id"] == item["id"] and row.lines[0]["price_cents"] == 42999
    assert emailimport.process(db, _email(BESTBUY), use_llm=False) is None  # same Message-ID: skipped
    # forwarded again under a new Message-ID: same order number, no duplicate purchase
    again = emailimport.process(db, _email(BESTBUY, mid="<a2@example.com>"), use_llm=False)
    assert not any(ln.get("purchase_id") for ln in again.lines)
    db.close()
    p = client.get("/api/purchases").json()
    assert len(p) == 1 and p[0]["retailer_name"] == "Best Buy Canada" and p[0]["price_cents"] == 42999
    assert p[0]["order_ref"] == "BBY01-806512345678" and p[0]["purchased_on"] == "2026-11-20"
    imports = client.get("/api/email-imports").json()
    assert imports["configured"] is False and len(imports["imports"]) == 2


def test_owner_by_forwarding_address_and_manual_link(client, setup):
    from pricewatch.db import session_scope
    from pricewatch.models import User
    from pricewatch.services import users as users_svc

    item, other = setup
    r = client.post("/api/users", json={"username": "sam", "display_name": "Sam", "password": "password123"}).json()
    db = session_scope()
    tok = users_svc.new_api_token(db.get(User, r["id"]))
    db.commit()
    h = {"Authorization": f"Bearer {tok}"}
    client.patch("/api/settings", json={"order_email_from": "Sam@Example.com"}, headers=h)
    lego = client.post("/api/items", json={"name": "Minecraft Creeper Plush"}, headers=h).json()
    html = ("<p>From: Costco Wholesale</p><p>Order number: 1234567890</p>"
            "<p>Kirkland Signature Plush Toy 12 in.</p><p>$24.99</p><p>costco.ca</p>")
    row = emailimport.process(db, _email(html, sender="sam@example.com", mid="<c1@x>"), use_llm=False)
    assert row.user_id == r["id"] and row.retailer_domain == "costco.ca" and row.status == "unmatched"
    db.close()
    # nothing matched by rules: Sam links it by hand (here by adding a line through the API path)
    db = session_scope()
    from pricewatch.models import EmailImport
    imp = db.get(EmailImport, row.id)
    imp.lines = [{"name": "Kirkland Signature Plush Toy 12 in.", "price_cents": 2499, "quantity": 1, "item_id": None}]
    db.commit()
    db.close()
    out = client.post(f"/api/email-imports/{row.id}/link", json={"line": 0, "item_id": lego["id"]}, headers=h).json()
    assert out["purchase_id"] and out["import"]["status"] == "recorded"
    sam_p = client.get("/api/purchases", headers=h).json()
    assert sam_p[0]["retailer_name"] == "Costco Canada" and sam_p[0]["protection_until"] == "2026-12-20"
    assert client.post(f"/api/email-imports/{row.id}/link", json={"line": 0, "item_id": item["id"]}).status_code == 404


def test_poll_marks_read_and_respects_switches(client, setup, monkeypatch):
    from pricewatch.config import get_settings
    from pricewatch.db import session_scope

    db = session_scope()
    assert emailimport.poll(db) == {"enabled": False}
    s = get_settings()
    monkeypatch.setattr(s, "imap_host", "imap.example.com")
    monkeypatch.setattr(s, "imap_user", "orders@example.com")
    monkeypatch.setattr(s, "imap_password", "x")
    assert emailimport.poll(db) == {"enabled": False}  # household switch still off
    client.patch("/api/settings", json={"email_import_enabled": True})
    marked = []
    stats = emailimport.poll(db, fetch=lambda: [(b"7", _email(BESTBUY)), (b"8", b"not an email at all")],
                             mark=marked.extend)
    assert stats["read"] == 2 and stats["recorded"] == 1 and marked == [b"7", b"8"]
    db.close()


def test_claude_mode_matches_extracted_lines(client, setup, monkeypatch):
    from pricewatch.db import session_scope

    item, other = setup

    def fake(text, items, threshold):
        order = emailimport.Order(is_order_confirmation=True, store="Best Buy", order_number="BBY01-1",
                                  lines=[emailimport.OrderLine(name="Sony WH-1000XM6 Headphones (Black)",
                                                               price_cents=42999)])
        return order, [{"name": order.lines[0].name, "price_cents": 42999, "quantity": 1, "item_id": item["id"],
                        "score": 0.95}]

    monkeypatch.setattr(emailimport, "claude_lines", fake)
    db = session_scope()
    row = emailimport.process(db, _email(BESTBUY, mid="<z@x>"), use_llm=True)
    assert row.method == "claude" and row.order_ref == "BBY01-1" and row.status == "recorded"
    db.close()
    assert client.get(f"/api/items/{item['id']}").json()["active"] is False  # sure match: deal alerts stop
