"""Order-email import: forward store order confirmations to a mailbox; PriceWatch records the purchases.

Off unless the household setting is on and PRICEWATCH_IMAP_* are set. Every 10 minutes PriceWatch reads unread
messages in one folder (marking them read), works out which person forwarded it (their "order emails come from"
address, else the admin), which store it is from, the order number and date, and which of that person's tracked
items it contains. Each matched item becomes a purchase with the store's price-protection terms, exactly as if it
had been entered with "Bought". Lines it cannot match are kept for the person to link by hand.

Matching is rule-based by default: each line of the email is compared with the person's tracked items using the
same matcher as discovery. With the household setting "email_import_llm" and ANTHROPIC_API_KEY, Claude Haiku reads
the email text instead (the whole text goes to Anthropic, so it is off by default). Nothing is ever sent to a store.
"""

import email
import imaplib
import logging
import re
from datetime import datetime
from email import policy
from email.utils import parseaddr, parsedate_to_datetime

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.base import parse_price
from ..config import get_settings
from ..models import EmailImport, Item, Purchase, Retailer, SourceLink, User
from . import events, llm_match, protection, settings_store
from .matching import Candidate, ItemSpec, match

log = logging.getLogger(__name__)
ORDER_RE = re.compile(r"\b(?:order|commande)\s*(?:number|no\.?|num(?:ber|éro)?|#|n°)?\s*[:#]?\s*"
                      r"([A-Z0-9][A-Z0-9-]{4,24})\b", re.I)
PRICE_RE = re.compile(r"(?:CA)?\$\s?\d[\d,]*(?:\.\d{2})?|\d[\d\s,]*[.,]\d{2}\s?\$")
MAX_TEXT = 30_000
MAX_PER_RUN = 20
SURE = 0.9  # matcher confidence: a model number, MPN or GTIN match, or identical titles


def configured() -> bool:
    s = get_settings()
    return bool(s.imap_host and s.imap_user and s.imap_password)


# ---------------------------------------------------------------- parsing

def message_text(msg: email.message.EmailMessage) -> str:
    """Plain text of the email (HTML converted), forwarded parts included."""
    plain, html = [], []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart" or part.get_filename():
            continue
        ctype = part.get_content_type()
        try:
            content = part.get_content()
        except (LookupError, ValueError):
            continue
        if ctype == "text/plain":
            plain.append(str(content))
        elif ctype == "text/html":
            html.append(BeautifulSoup(str(content), "lxml").get_text("\n"))
        elif ctype == "message/rfc822" and hasattr(content, "walk"):
            plain.append(message_text(content))
    text = "\n".join(html) if html and sum(map(len, html)) > sum(map(len, plain)) else "\n".join(plain)
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)[:MAX_TEXT]


def find_retailer(db: Session, msg: email.message.EmailMessage, text: str) -> Retailer | None:
    """Store whose domain or name appears most in the senders and text."""
    haystack = " ".join([msg.get("From", ""), msg.get("Reply-To", ""), text]).lower()
    best, best_hits = None, 0
    for r in db.scalars(select(Retailer)).all():
        name = r.name.lower().replace(" canada", "").strip()
        hits = haystack.count(r.domain) * 3 + (haystack.count(name) if len(name) > 3 else 0)
        if hits > best_hits:
            best, best_hits = r, hits
    return best


def find_order_ref(text: str) -> str | None:
    for m in ORDER_RE.finditer(text):
        ref = m.group(1)
        if any(c.isdigit() for c in ref):
            return ref[:60]
    return None


def _line_price(lines: list[str], i: int) -> int | None:
    for ln in lines[i:i + 3]:
        m = PRICE_RE.search(ln)
        if m:
            return parse_price(m.group(0))
    return None


def rule_lines(text: str, items: list[Item], threshold: float) -> list[dict]:
    """Tracked items mentioned in the email, with the price on or just after the matching line."""
    lines = text.splitlines()
    found = []
    for item in items:
        spec = ItemSpec.from_item(item)
        spec.exclude_marketplace = False
        best = None
        for i, ln in enumerate(lines):
            if len(ln) < 6 or len(ln) > 300:
                continue
            r = match(spec, Candidate(title=ln, url="mailto:order"), threshold)
            if r.accepted and (best is None or r.confidence > best[1]):
                best = (i, r.confidence)
        if best:
            i, conf = best
            found.append({"name": lines[i][:200], "price_cents": _line_price(lines, i), "quantity": 1,
                          "item_id": item.id, "score": conf})
    return found


class OrderLine(BaseModel):
    name: str
    price_cents: int | None = Field(description="unit price before tax, in cents")
    quantity: int = 1


class Order(BaseModel):
    is_order_confirmation: bool
    store: str | None
    order_number: str | None
    lines: list[OrderLine]


def claude_lines(text: str, items: list[Item], threshold: float) -> tuple[Order | None, list[dict]]:
    """Ask Claude Haiku to read the order, then match its lines to tracked items."""
    import anthropic

    try:
        client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key, timeout=60.0, max_retries=2)
        response = client.messages.parse(
            model=get_settings().llm_match_model, max_tokens=4000, output_config={"effort": "low"},
            system=("You read a forwarded email and extract a retail order confirmation: the store, the order number "
                    "and each product line with its unit price before tax in cents and quantity. Ignore shipping, "
                    "taxes, totals, gift cards and recommendations. If it is not an order confirmation (for "
                    "example a shipping notice without prices, or marketing), say so and return no lines."),
            messages=[{"role": "user", "content": text}],
            output_format=Order,
        )
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
        log.warning("order email extraction failed", extra={"error": type(exc).__name__})
        return None, []
    order = response.parsed_output if response.stop_reason != "refusal" else None
    if order is None or not order.is_order_confirmation:
        return order, []
    out = []
    for ln in order.lines:
        best = None
        for item in items:
            spec = ItemSpec.from_item(item)
            spec.exclude_marketplace = False
            r = match(spec, Candidate(title=ln.name, url="mailto:order"), threshold)
            if r.accepted and (best is None or r.confidence > best[1]):
                best = (item.id, r.confidence)
        out.append({"name": ln.name[:200], "price_cents": ln.price_cents, "quantity": ln.quantity,
                    "item_id": best[0] if best else None, "score": best[1] if best else None})
    return order, out


# ---------------------------------------------------------------- recording

def owner_for(db: Session, msg: email.message.EmailMessage) -> User | None:
    """The person whose 'order emails come from' list has the forwarder's address, else the first admin."""
    sender = parseaddr(msg.get("From", ""))[1].lower()
    for u in db.scalars(select(User).where(User.active.is_(True))).all():
        mine = [a.strip().lower() for a in str(settings_store.get(db, "order_email_from", u.id) or "").split(",")]
        if sender and sender in mine:
            return u
    admin = settings_store._admin_id(db)
    return db.get(User, admin) if admin else None


def _visible_items(db: Session, user: User) -> list[Item]:
    from .users import list_ids

    return list(db.scalars(select(Item).where(Item.list_id.in_(list_ids(db, user)))).all())


def record_line(db: Session, user: User, item: Item, retailer: Retailer | None, line: dict, bought,
                order_ref: str | None) -> Purchase | None:
    """Create the purchase for one matched line unless it was already recorded."""
    dup = select(Purchase.id).where(Purchase.user_id == user.id, Purchase.item_id == item.id)
    dup = dup.where(Purchase.order_ref == order_ref) if order_ref else dup.where(Purchase.purchased_on == bought)
    if db.scalar(dup):
        return None
    src = None
    if retailer:
        src = db.scalar(select(SourceLink).where(SourceLink.item_id == item.id, SourceLink.retailer_id == retailer.id,
                                                 SourceLink.status == "confirmed"))
    price = line.get("price_cents") or (src.last_price_cents if src else None)
    if not price:
        return None
    return protection.create_purchase(
        db, user_id=user.id, item=item, src=src, retailer_name=retailer.name if retailer else "Unknown store",
        retailer_domain=retailer.domain if retailer else None, price_cents=int(price), purchased_on=bought,
        order_ref=order_ref, notes="Imported from an order email",
        stop_tracking=(line.get("score") or 0) >= SURE)  # only a near-certain match stops deal alerts


def process(db: Session, raw: bytes, use_llm: bool | None = None) -> EmailImport | None:
    """Turn one raw email into purchases. Returns the EmailImport row, or None if it was seen before."""
    from .alerts import money, raise_alert

    msg = email.message_from_bytes(raw, policy=policy.default)
    mid = (msg.get("Message-ID") or "").strip()[:300] or f"nomid:{hash(raw)}"
    if db.scalar(select(EmailImport.id).where(EmailImport.message_id == mid)):
        return None
    user = owner_for(db, msg)
    try:
        received = parsedate_to_datetime(msg.get("Date")) if msg.get("Date") else None
    except (TypeError, ValueError):
        received = None
    local_date = (events.local_now(received.astimezone(tz=None).replace(tzinfo=None)) if received
                  else events.local_now()).date()
    row = EmailImport(message_id=mid, user_id=user.id if user else None, subject=str(msg.get("Subject", ""))[:300],
                      received_at=received.replace(tzinfo=None) if received else None)
    db.add(row)
    if user is None:
        row.status, row.error = "error", "No person to record it for"
        db.commit()
        return row
    text = message_text(msg)
    retailer = find_retailer(db, msg, text)
    row.retailer_domain = retailer.domain if retailer else None
    row.order_ref = find_order_ref(text)
    items = _visible_items(db, user)
    threshold = float(settings_store.get(db, "match_threshold") or 85)
    if use_llm is None:
        use_llm = bool(settings_store.get(db, "email_import_llm")) and llm_match.enabled(db)
    if use_llm:
        order, lines = claude_lines(text, items, threshold)
        row.method = "claude"
        if order and order.order_number:
            row.order_ref = order.order_number[:60]
        if order is not None and not order.is_order_confirmation:
            row.status, row.lines = "ignored", []
            db.commit()
            return row
    else:
        lines = rule_lines(text, items, threshold)
    recorded = 0
    by_id = {i.id: i for i in items}
    for ln in lines:
        item = by_id.get(ln.get("item_id"))
        if item is None:
            continue
        p = record_line(db, user, item, retailer, ln, local_date, row.order_ref)
        if p:
            ln["purchase_id"] = p.id
            recorded += 1
            raise_alert(db, item=item, rule="protection", key=f"emailbuy:{p.id}", user_id=user.id,
                        title=f"Recorded from email: {item.name}",
                        body=(f"{p.retailer_name}, {money(p.price_cents)} on {p.purchased_on:%b %d}"
                              + (f", order {p.order_ref}" if p.order_ref else "") + ". "
                              + (f"{p.protection_basis} until {p.protection_until:%b %d}; PriceWatch is watching the price."
                                 if p.protection_until else "No price protection at this store.")))
    row.lines = lines
    matched = [ln for ln in lines if ln.get("item_id")]
    row.status = ("recorded" if recorded and len(matched) == len(lines) else "partial" if recorded
                  else "unmatched" if lines or retailer else "ignored")
    db.commit()
    return row


# ---------------------------------------------------------------- mailbox

def fetch_unread(limit: int = MAX_PER_RUN) -> list[tuple[bytes, bytes]]:
    """(uid, raw message) for unread mail in the import folder. Leaves them unread until marked."""
    s = get_settings()
    out = []
    with imaplib.IMAP4_SSL(s.imap_host, s.imap_port, timeout=30) as box:
        box.login(s.imap_user, s.imap_password)
        box.select(s.imap_folder)
        typ, data = box.uid("search", None, "UNSEEN")
        uids = (data[0] or b"").split()[:limit] if typ == "OK" else []
        for uid in uids:
            typ, msg = box.uid("fetch", uid, "(BODY.PEEK[])")
            if typ == "OK" and msg and isinstance(msg[0], tuple):
                out.append((uid, msg[0][1]))
    return out


def mark_read(uids: list[bytes]) -> None:
    if not uids:
        return
    s = get_settings()
    with imaplib.IMAP4_SSL(s.imap_host, s.imap_port, timeout=30) as box:
        box.login(s.imap_user, s.imap_password)
        box.select(s.imap_folder)
        for uid in uids:
            box.uid("store", uid, "+FLAGS", "(\\Seen)")


def poll(db: Session, fetch=fetch_unread, mark=mark_read) -> dict:
    """Read the mailbox once. Blocking (IMAP); the scheduler runs it in a thread."""
    if not configured() or not settings_store.get(db, "email_import_enabled"):
        return {"enabled": False}
    stats = {"read": 0, "recorded": 0, "unmatched": 0, "errors": 0}
    done = []
    for uid, raw in fetch():
        stats["read"] += 1
        try:
            row = process(db, raw)
            if row is not None:
                stats["recorded"] += sum(1 for ln in (row.lines or []) if ln.get("purchase_id"))
                stats["unmatched"] += sum(1 for ln in (row.lines or []) if not ln.get("item_id"))
            done.append(uid)
        except Exception:  # noqa: BLE001 - one bad email must not stop the rest
            db.rollback()
            stats["errors"] += 1
            log.exception("order email failed")
            done.append(uid)
    mark(done)
    log.info("order email import", extra=stats)
    return stats


def link(db: Session, row: EmailImport, index: int, item: Item, user: User) -> Purchase | None:
    """Link an unmatched line to an item by hand and record the purchase."""
    lines = list(row.lines or [])
    if not 0 <= index < len(lines):
        return None
    retailer = db.scalar(select(Retailer).where(Retailer.domain == row.retailer_domain)) if row.retailer_domain else None
    bought = (row.received_at or datetime.now()).date()
    p = record_line(db, user, item, retailer, {**lines[index], "score": 1.0}, bought, row.order_ref)
    lines[index] = {**lines[index], "item_id": item.id, "purchase_id": p.id if p else None}
    row.lines = lines
    if all(ln.get("item_id") for ln in lines):
        row.status = "recorded"
    db.commit()
    return p

