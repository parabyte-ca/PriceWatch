"""Optional bridge to changedetection.io: its watches can be the fetch engine for chosen sources.

A source with fetch_mode "changedetection" is never fetched by PriceWatch. Its price and stock come from the
watch's restock processor state through the changedetection.io REST API (x-api-key header).
Response shapes differ between releases, so parsing is defensive.
"""

import logging
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.base import parse_price
from ..config import get_settings
from ..models import FetchRun, SourceLink
from ..timeutil import utcnow
from .matching import normalize_url

log = logging.getLogger(__name__)


class ChangeDetectionError(Exception):
    pass


def configured() -> bool:
    s = get_settings()
    return bool(s.changedetection_url and s.changedetection_api_key)


def _client() -> httpx.Client:
    s = get_settings()
    return httpx.Client(base_url=s.changedetection_url.rstrip("/"), timeout=20,
                        headers={"x-api-key": s.changedetection_api_key or ""})


def reachable() -> bool:
    try:
        with _client() as c:
            return c.get("/api/v1/systeminfo").status_code == 200
    except httpx.HTTPError:
        return False


def restock_state(watch: dict) -> dict:
    """Pull price/stock out of a watch, whichever key this release uses."""
    candidates = [watch.get("restock"), (watch.get("processor_state") or {}).get("restock"),
                  watch.get("processor_state"), watch.get("restock_diff")]
    for c in candidates:
        if isinstance(c, dict) and ("price" in c or "in_stock" in c):
            return {
                "price_cents": parse_price(c.get("price")),
                "was_price_cents": parse_price(c.get("original_price")),
                "currency": c.get("currency"),
                "in_stock": c.get("in_stock") if isinstance(c.get("in_stock"), bool) else None,
            }
    return {}


def _ts(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), UTC).replace(tzinfo=None) if value else None
    except (TypeError, ValueError):
        return None


def list_watches(client: httpx.Client) -> dict[str, dict]:
    resp = client.get("/api/v1/watch")
    if resp.status_code != 200:
        raise ChangeDetectionError(f"changedetection.io HTTP {resp.status_code}")
    return resp.json() or {}


def create_watch(src: SourceLink, client: httpx.Client | None = None) -> str:
    own = client is None
    client = client or _client()
    try:
        resp = client.post("/api/v1/watch", json={"url": src.url, "title": src.item.name[:200],
                                                   "processor": "restock_diff"})
        if resp.status_code not in (200, 201):
            raise ChangeDetectionError(f"changedetection.io HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        uuid = data.get("uuid") if isinstance(data, dict) else None
        if not uuid:
            watches = list_watches(client)
            uuid = next((u for u, w in watches.items() if normalize_url(w.get("url", "")) == normalize_url(src.url)), None)
        if not uuid:
            raise ChangeDetectionError("Watch created but its UUID was not returned")
        return uuid
    finally:
        if own:
            client.close()


def sync(db: Session, client: httpx.Client | None = None) -> dict:
    """Read every changedetection-backed source's watch and record new observations."""
    from .checker import counts_for_item, normal_condition, record_observation, run_alerts  # noqa: F401

    if not configured() and client is None:
        return {"configured": False}
    own = client is None
    client = client or _client()
    stats = {"configured": True, "checked": 0, "recorded": 0, "linked": 0, "errors": 0}
    try:
        sources = db.scalars(select(SourceLink).where(SourceLink.status == "confirmed",
                                                      SourceLink.fetch_mode == "changedetection")).all()
        if not sources:
            return stats
        watches = list_watches(client)
        by_url = {normalize_url(w.get("url", "")): u for u, w in watches.items() if isinstance(w, dict)}
        for src in sources:
            stats["checked"] += 1
            uuid = src.external_id or by_url.get(normalize_url(src.url))
            if not uuid:
                src.last_error = "No matching changedetection.io watch"
                continue
            if not src.external_id:
                src.external_id = uuid
                stats["linked"] += 1
            resp = client.get(f"/api/v1/watch/{uuid}")
            if resp.status_code != 200:
                stats["errors"] += 1
                src.last_error = f"changedetection.io HTTP {resp.status_code}"
                continue
            watch = resp.json()
            checked = _ts(watch.get("last_checked"))
            if checked and src.last_checked_at and checked <= src.last_checked_at:
                continue
            state = restock_state(watch)
            domain = src.retailer.domain if src.retailer else ""
            if state.get("price_cents") and state.get("currency") in (None, "", "CAD"):
                _, previous = record_observation(
                    db, src, price_cents=state["price_cents"], was_price_cents=state.get("was_price_cents"),
                    shipping_cents=None, in_stock=state.get("in_stock"), seller=None, method="changedetection",
                    parse_confidence=0.9, observed_at=checked)
                src.last_checked_at = checked or utcnow()
                db.add(FetchRun(source_link_id=src.id, domain=domain, status="ok", method="changedetection",
                                started_at=checked or utcnow()))
                db.commit()
                run_alerts(db, src, previous)
                stats["recorded"] += 1
            else:
                err = watch.get("last_error") or "changedetection.io has no price for this watch yet"
                src.last_checked_at = checked or utcnow()
                src.last_error = str(err)[:500]
                src.consecutive_failures = (src.consecutive_failures or 0) + 1
                db.add(FetchRun(source_link_id=src.id, domain=domain, status="no_price", method="changedetection",
                                error=str(err)[:500], started_at=checked or utcnow()))
        db.commit()
    except (httpx.HTTPError, ChangeDetectionError) as exc:
        log.warning("changedetection sync failed", extra={"error": str(exc)})
        stats["error"] = str(exc)
    finally:
        if own:
            client.close()
    return stats
