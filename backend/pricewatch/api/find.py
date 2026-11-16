"""Find: one search box for a name, a store link or a barcode, then every Canadian store's price, then Watch.

The comparison is shown before anything is saved. Searches are cached for a week, so pressing Watch right after a
comparison reuses the same results (no second paid search) and every known store is tracked straight away.
"""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..fetch.http import looks_like_challenge
from ..models import Item, User
from ..pricing import landed_price
from ..serp import get_provider
from ..services import settings_store
from ..services.checker import fetch_and_parse
from ..services.discovery import DiscoveryError, barcode_lookup, best_per_store, build_query, compare, discover
from ..services.matching import normalize_url
from ..services.retailers import get_or_create_retailer
from ..services.summary import summarize_items

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["find"])
URL_RE = re.compile(r"https?://\S+")
BARCODE_RE = re.compile(r"^\d{8,14}$")


class FindIn(BaseModel):
    q: str = Field(min_length=1, max_length=500)
    force: bool = False


def suggest_target(best_cents: int | None) -> int | None:
    """About 10% under today's best price, ending in .99 (a price shoppers recognise)."""
    if not best_cents:
        return None
    return max(99, (int(best_cents * 0.9) // 100) * 100 - 1)


async def _resolve(db: Session, q: str) -> tuple[dict, dict | None]:
    """Turn what was typed into a product description, plus the pasted link's own reading when there is one."""
    q = q.strip()
    m = URL_RE.search(q)
    if m:
        from .items import _claude_preview, _public_or_422

        url = normalize_url(m.group(0))
        _public_or_422(url)
        retailer = get_or_create_retailer(db, url)
        db.commit()
        result, parsed, _ = await fetch_and_parse(url, retailer, "auto", use_cache=True)
        from ..adapters.base import ParsedProduct, clean_name

        parsed = parsed or ParsedProduct()
        blocked = result.outcome != "ok" or (not parsed.has_price and looks_like_challenge(result.html))
        if not parsed.has_price:
            await _claude_preview(url, parsed)
        parsed.name = clean_name(parsed.name, url, retailer.name)
        product = {"name": parsed.name, "brand": parsed.brand, "model": parsed.mpn, "gtin": parsed.gtin,
                   "image": parsed.image}
        link = {"url": url, "store": retailer.name, "price_cents": parsed.price_cents, "blocked": blocked}
        return product, link
    digits = re.sub(r"\D", "", q)
    if BARCODE_RE.match(q.replace(" ", "")) and digits:
        found = await barcode_lookup(db, digits)
        best = found["names"][0] if found["names"] else None
        return {"name": best["title"] if best else digits, "brand": best and best.get("brand"), "model": None,
                "gtin": digits, "image": None}, None
    return {"name": q[:300], "brand": None, "model": None, "gtin": None, "image": None}, None


def _transient(product: dict, query: str | None = None) -> Item:
    item = Item(name=(product["name"] or "Product")[:300], brand=product.get("brand"), model=product.get("model"),
                gtin=product.get("gtin"), search_query=query)
    for flag in ("exclude_refurbished", "exclude_open_box", "exclude_used", "exclude_marketplace", "exclude_bundles",
                 "exclude_variants"):
        setattr(item, flag, True)
    return item


def _rows(offers: list[dict], cfg: dict) -> list[dict]:
    rows = []
    for o in best_per_store(offers):
        landed = landed_price(o["price_cents"], o["shipping_cents"], cfg["province"], cfg.get("tax_overrides") or {})
        rows.append({"merchant": o["merchant"], "title": o["title"], "url": o["url"], "store_link": o["store_link"],
                     "price_cents": o["price_cents"], "shipping_cents": o["shipping_cents"],
                     "landed_cents": landed["landed_cents"], "kind": o["kind"], "domain": o["domain"],
                     "confidence": o["confidence"], "method": o["method"], "local": o.get("local")})
    return rows


def _with_best(out: dict, rows: list[dict]) -> dict:
    stores = [o for o in rows if o["kind"] == "store"]
    out.update(offers=rows, best=stores[0] if stores else None,
               suggested_target_cents=suggest_target(stores[0]["price_cents"] if stores else None))
    return out


async def _run_find(db: Session, me: User, q: str, force: bool, on_stage=None) -> dict:
    product, link = await _resolve(db, q)
    item = _transient(product)
    out = {"query": build_query(item), "product": product, "link": link, "offers": [], "provider": None,
           "cached": False, "notes": [], "best": None, "suggested_target_cents": None}
    provider = get_provider(None)
    if on_stage is not None:
        await on_stage("product", dict(out))
    if provider is None:
        out["notes"].append("Searching other stores needs a SerpApi key (.env) or a Claude key (Household admin).")
        return out
    cfg = settings_store.get_all(db, me.id)
    out["provider"] = provider.name

    async def staged(name: str, offers: list[dict]) -> None:
        if on_stage is not None:
            await on_stage(name, _with_best(dict(out), _rows(offers, cfg)))

    r = await compare(db, item, provider, force=force, on_stage=staged)
    out.update(query=r["query"], cached=r["cached"], notes=r["notes"])
    return _with_best(out, _rows(r["offers"], cfg))


@router.post("/find")
async def find(body: FindIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    try:
        return await _run_find(db, me, body.q, body.force)
    except DiscoveryError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/find/stream")
async def find_stream(q: str = Query(min_length=1, max_length=500), force: bool = False,
                      db: Session = Depends(get_db), me: User = Depends(current_user)):
    """The same comparison as POST /find, sent as Server-Sent Events while stores are found:
    "product", then "search", "stores", "claude" (each with the offers so far), then "done" or "error"."""
    import asyncio
    import json

    queue: asyncio.Queue = asyncio.Queue()

    async def emit(name: str, data: dict) -> None:
        await queue.put((name, data))

    async def work() -> None:
        try:
            await emit("done", await _run_find(db, me, q, force, on_stage=emit))
        except DiscoveryError as exc:
            await emit("error", {"detail": str(exc)})
        except HTTPException as exc:
            await emit("error", {"detail": exc.detail})
        except Exception:  # noqa: BLE001
            log.exception("find stream failed")
            await emit("error", {"detail": "Search failed; try again"})

    async def events():
        task = asyncio.create_task(work())
        try:
            while True:
                name, data = await queue.get()
                yield f"event: {name}\ndata: {json.dumps(data, default=str)}\n\n"
                if name in ("done", "error"):
                    break
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class WatchIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    brand: str | None = None
    model: str | None = None
    gtin: str | None = Field(default=None, pattern=r"^\d{8,14}$")
    image_url: str | None = None
    query: str | None = Field(default=None, max_length=300)
    target_price_cents: int | None = Field(default=None, ge=0)
    link_url: str | None = None
    list_id: int | None = None
    hot: bool = False


@router.post("/watch", status_code=201)
async def watch(body: WatchIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    """Save the product and track every store found (the search is reused from the comparison, so it is free)."""
    from .items import _add_source, _load_item, _target_list, item_out

    item = Item(name=body.name, brand=body.brand, model=body.model, gtin=body.gtin, image_url=body.image_url,
                search_query=body.query, target_price_cents=body.target_price_cents, hot=body.hot,
                list_id=_target_list(db, me, body.list_id), added_by=me.id)
    db.add(item)
    db.flush()
    if body.link_url:
        src = _add_source(db, item, body.link_url)
        if src.retailer and src.retailer.fetch_mode == "search":
            src.fetch_mode = "search"  # the store blocks visits: its price comes from the searches
    db.commit()
    notes = []
    if get_provider(None) is not None:
        try:
            await discover(db, item)
        except DiscoveryError as exc:
            notes.append(str(exc))
    item = _load_item(db, item.id)
    out = item_out(db, item, summarize_items(db, [item], me.id)[item.id], with_sources=True, me=me)
    return {"item": out, "notes": notes}


class ListingWrongIn(BaseModel):
    url: str = Field(min_length=1, max_length=1000)
    query: str | None = Field(default=None, max_length=300)
    item_id: int | None = None
    merchant: str | None = Field(default=None, max_length=120)


@router.post("/feedback/not-this-product", status_code=204)
def not_this_product(body: ListingWrongIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    """One tap: this listing is not the product. Remembered for the search and the item; a watched store is hidden."""
    from ..models import ListingFeedback, MarketOffer
    from .items import _load_item

    url = normalize_url(body.url)
    query = (body.query or "").lower().strip()
    if body.item_id:
        item = _load_item(db, body.item_id, me, write=True)
        query = query or build_query(item).lower().strip()
        for s in item.sources:
            if normalize_url(s.url) == url and s.status != "rejected":
                s.status = "rejected"
        db.query(MarketOffer).filter(MarketOffer.item_id == item.id, MarketOffer.url == url).delete()
    db.add(ListingFeedback(item_id=body.item_id, query=query[:300], url=url, merchant=body.merchant,
                           verdict="wrong", user_id=me.id))
    db.commit()


@router.post("/sources/{source_id}/only", status_code=204)
def only_this_store(source_id: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    """One tap: watch only this store for the item; the others are hidden (and stay hidden on later searches)."""
    from .items import _load_source

    src = _load_source(db, source_id, me, write=True)
    for s in src.item.sources:
        if s.id != src.id and s.status == "confirmed":
            s.status = "rejected"
    src.status = "confirmed"
    db.commit()


class PhotoIn(BaseModel):
    image_b64: str = Field(min_length=100, max_length=4_000_000)
    media_type: str = Field(default="image/jpeg", pattern=r"^image/(jpeg|png|webp)$")


class Identified(BaseModel):
    found: bool
    name: str
    brand: str | None
    model: str | None
    barcode: str | None


@router.post("/find/photo")
async def find_photo(body: PhotoIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    """Photo of a product or its box -> what to search for. Claude reads it; the photo is not stored."""
    import anthropic

    from ..services import claude

    key = claude.api_key()
    if not key:
        raise HTTPException(409, "Photo search needs a Claude key (Household admin)")
    left = claude.budget_left()
    if left is not None and left < 0.02:
        raise HTTPException(409, "This month's Claude spending cap is reached")
    api = anthropic.AsyncAnthropic(api_key=key, timeout=60.0, max_retries=1)
    try:
        resp = await api.messages.parse(
            model=claude.PRICE_MODEL, max_tokens=1000, output_config={"effort": "low"},
            system="Identify the retail product in the photo (often its box or shelf label) for a price search in "
                   "Canada: brand, model or product name, and the UPC/EAN digits if a barcode number is readable. "
                   "If you cannot tell what product it is, set found to false.",
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": body.media_type, "data": body.image_b64}},
                {"type": "text", "text": "What product is this?"}]}],
            output_format=Identified)
        claude.record_spend(claude.cost_usd(claude.PRICE_MODEL, getattr(resp, "usage", None)))
        got: Identified | None = resp.parsed_output
    except anthropic.APIStatusError as exc:
        raise HTTPException(502, f"Claude could not read the photo (HTTP {exc.status_code})") from exc
    except anthropic.APIConnectionError as exc:
        raise HTTPException(502, "Could not reach api.anthropic.com") from exc
    finally:
        await api.close()
    if not got or not got.found:
        return {"found": False, "q": None}
    barcode = re.sub(r"\D", "", got.barcode or "")
    name = got.name or ""
    parts = [got.brand] if got.brand and got.brand.lower() not in name.lower() else []
    parts.append(name)
    if got.model and got.model.lower() not in name.lower():
        parts.append(got.model)
    q = " ".join(parts)
    return {"found": True, "q": q.strip() or got.name, "name": got.name, "brand": got.brand, "model": got.model,
            "barcode": barcode if 8 <= len(barcode) <= 14 else None}
