"""Find: one search box for a name, a store link or a barcode, then every Canadian store's price, then Watch.

The comparison is shown before anything is saved. Searches are cached for a week, so pressing Watch right after a
comparison reuses the same results (no second paid search) and every known store is tracked straight away.
"""

import re

from fastapi import APIRouter, Depends, HTTPException
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


@router.post("/find")
async def find(body: FindIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    product, link = await _resolve(db, body.q)
    item = _transient(product)
    query = build_query(item)
    provider = get_provider(None)
    out = {"query": query, "product": product, "link": link, "offers": [], "provider": None, "cached": False,
           "notes": [], "best": None, "suggested_target_cents": None}
    if provider is None:
        out["notes"].append("Searching other stores needs a SerpApi key (.env) or a Claude key (Household admin).")
        return out
    try:
        r = await compare(db, item, provider, force=body.force)
    except DiscoveryError as exc:
        raise HTTPException(409, str(exc)) from exc
    cfg = settings_store.get_all(db, me.id)
    rows = []
    for o in best_per_store(r["offers"]):
        landed = landed_price(o["price_cents"], o["shipping_cents"], cfg["province"], cfg.get("tax_overrides") or {})
        rows.append({"merchant": o["merchant"], "title": o["title"], "url": o["url"], "store_link": o["store_link"],
                     "price_cents": o["price_cents"], "shipping_cents": o["shipping_cents"],
                     "landed_cents": landed["landed_cents"], "kind": o["kind"], "domain": o["domain"],
                     "confidence": o["confidence"], "method": o["method"]})
    stores = [o for o in rows if o["kind"] == "store"]
    out.update(query=r["query"], offers=rows, provider=provider.name, cached=r["cached"], notes=r["notes"],
               best=stores[0] if stores else None,
               suggested_target_cents=suggest_target(stores[0]["price_cents"] if stores else None))
    return out


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
