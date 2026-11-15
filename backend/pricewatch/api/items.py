"""Wishlist items, source links, history and manual prices."""

import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .. import scheduler
from ..db import get_db
from ..fetch.http import domain_of
from ..models import Item, Observation, SourceLink
from ..schemas import (
    FromUrlIn,
    ItemCreate,
    ItemOut,
    ItemUpdate,
    ManualPriceIn,
    SourceCreate,
    SourceOut,
    SourceUpdate,
    UrlIn,
)
from ..services import alerts, settings_store
from ..services.checker import check_source, fetch_and_parse, record_observation, run_alerts, schedule_next
from ..services.retailers import get_or_create_retailer
from ..services.summary import _source_landed, summarize_items
from ..timeutil import utcnow

router = APIRouter(prefix="/api", tags=["items"])


def _load_item(db: Session, item_id: int) -> Item:
    item = db.scalar(
        select(Item).where(Item.id == item_id).options(selectinload(Item.sources).selectinload(SourceLink.retailer))
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    return item


def source_out(src: SourceLink, province: str) -> SourceOut:
    out = SourceOut.model_validate(src)
    out.retailer_name = src.retailer.name if src.retailer else None
    out.price_match = bool(src.retailer and src.retailer.price_match)
    out.landed = _source_landed(src, province)
    return out


def item_out(db: Session, item: Item, summary: dict, with_sources: bool = False) -> ItemOut:
    out = ItemOut.model_validate(item, from_attributes=True)
    out.summary = summary
    if with_sources:
        province = settings_store.get(db, "province")
        out.sources = [source_out(s, province) for s in item.sources]
    else:
        out.sources = None
    return out


@router.get("/items", response_model=list[ItemOut])
def list_items(include_inactive: bool = False, db: Session = Depends(get_db)):
    q = select(Item).options(selectinload(Item.sources).selectinload(SourceLink.retailer))
    if not include_inactive:
        q = q.where(Item.active.is_(True))
    items = list(db.scalars(q.order_by(Item.priority, Item.name)).all())
    summaries = summarize_items(db, items)
    return [item_out(db, i, summaries[i.id]) for i in items]


@router.post("/items", response_model=ItemOut, status_code=201)
def create_item(body: ItemCreate, db: Session = Depends(get_db)):
    item = Item(**body.model_dump())
    db.add(item)
    db.commit()
    item = _load_item(db, item.id)
    return item_out(db, item, summarize_items(db, [item])[item.id], with_sources=True)


@router.get("/items/{item_id}", response_model=ItemOut)
def get_item(item_id: int, db: Session = Depends(get_db)):
    item = _load_item(db, item_id)
    return item_out(db, item, summarize_items(db, [item])[item.id], with_sources=True)


@router.patch("/items/{item_id}", response_model=ItemOut)
def update_item(item_id: int, body: ItemUpdate, db: Session = Depends(get_db)):
    item = _load_item(db, item_id)
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(item, key, value)
    if "hot" in changes:
        # reschedule so the new interval applies soon
        for src in item.sources:
            if src.next_check_at and src.next_check_at > utcnow() + timedelta(minutes=60):
                src.next_check_at = utcnow()
    db.commit()
    item = _load_item(db, item_id)
    summary = summarize_items(db, [item])[item.id]
    if "target_price_cents" in changes or "max_price_cents" in changes:
        alerts.evaluate_item(db, item, summary)
    return item_out(db, item, summary, with_sources=True)


@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: int, db: Session = Depends(get_db)):
    item = _load_item(db, item_id)
    db.delete(item)
    db.commit()


@router.post("/preview")
async def preview(body: UrlIn, db: Session = Depends(get_db)):
    url = str(body.url)
    retailer = get_or_create_retailer(db, url)
    db.commit()
    result, parsed, method = await fetch_and_parse(url, retailer, retailer.fetch_mode, use_cache=True)
    return {
        "url": url,
        "domain": domain_of(url),
        "retailer": retailer.name,
        "outcome": result.outcome,
        "error": result.error,
        "method": method,
        "product": parsed.to_dict() if parsed else None,
    }


def _add_source(db: Session, item: Item, url: str, fetch_mode: str | None = None,
                status_: str = "confirmed", method: str = "manual") -> SourceLink:
    retailer = get_or_create_retailer(db, url)
    src = SourceLink(item_id=item.id, retailer_id=retailer.id, url=url, status=status_, fetch_mode=fetch_mode,
                     match_method=method, match_confidence=1.0 if method == "manual" else None)
    db.add(src)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This URL is already a source for the item") from exc
    db.refresh(src)
    return src


@router.post("/items/from-url", response_model=ItemOut, status_code=201)
async def create_from_url(body: FromUrlIn, db: Session = Depends(get_db)):
    url = str(body.url)
    retailer = get_or_create_retailer(db, url)
    db.commit()
    result, parsed, method = await fetch_and_parse(url, retailer, retailer.fetch_mode, use_cache=True)
    name = body.name or (parsed.name if parsed else None) or domain_of(url)
    item = Item(
        name=name[:300],
        brand=parsed.brand if parsed else None,
        model=parsed.mpn if parsed else None,
        gtin=parsed.gtin if parsed and parsed.gtin and re.fullmatch(r"\d{8,14}", parsed.gtin) else None,
        image_url=parsed.image if parsed else None,
        target_price_cents=body.target_price_cents,
        hot=body.hot,
        priority=body.priority,
    )
    db.add(item)
    db.flush()
    src = _add_source(db, item, url)
    if parsed and parsed.name:
        src.title = parsed.name[:500]
    if parsed and parsed.has_price and parsed.currency in (None, "", "CAD"):
        if method == "http":
            src.etag, src.last_modified = result.etag, result.last_modified
        _, previous = record_observation(
            db, src, price_cents=parsed.price_cents, was_price_cents=parsed.was_price_cents,
            shipping_cents=parsed.shipping_cents, in_stock=parsed.in_stock, seller=parsed.seller,
            method=method)
        schedule_next(src)
        db.commit()
        run_alerts(db, src, previous)
    else:
        src.last_error = result.error or "No price found on the page"
        src.last_checked_at = utcnow()
        schedule_next(src, minutes=60)
        db.commit()
    item = _load_item(db, item.id)
    return item_out(db, item, summarize_items(db, [item])[item.id], with_sources=True)


@router.post("/items/{item_id}/sources", response_model=SourceOut, status_code=201)
def add_source(item_id: int, body: SourceCreate, db: Session = Depends(get_db)):
    item = _load_item(db, item_id)
    src = _add_source(db, item, str(body.url), body.fetch_mode)
    db.commit()
    return source_out(src, settings_store.get(db, "province"))


@router.patch("/sources/{source_id}", response_model=SourceOut)
def update_source(source_id: int, body: SourceUpdate, db: Session = Depends(get_db)):
    src = db.get(SourceLink, source_id)
    if src is None:
        raise HTTPException(404, "Source not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(src, key, value)
    if src.status == "confirmed" and src.next_check_at is None:
        src.next_check_at = utcnow()
    db.commit()
    return source_out(src, settings_store.get(db, "province"))


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: int, db: Session = Depends(get_db)):
    src = db.get(SourceLink, source_id)
    if src is None:
        raise HTTPException(404, "Source not found")
    db.delete(src)
    db.commit()


@router.post("/sources/{source_id}/check")
async def check_now(source_id: int, db: Session = Depends(get_db)):
    src = db.get(SourceLink, source_id)
    if src is None:
        raise HTTPException(404, "Source not found")
    db.close()
    outcome = await check_source(source_id)
    return {"source_id": source_id, "outcome": outcome}


@router.post("/items/{item_id}/check", status_code=202)
async def check_item(item_id: int, db: Session = Depends(get_db)):
    item = _load_item(db, item_id)
    ids = [s.id for s in item.sources if s.status == "confirmed" and not s.url.startswith("manual://")]
    queued = [sid for sid in ids if scheduler.dispatch(sid)]
    return {"queued": queued}


@router.post("/items/{item_id}/manual", response_model=SourceOut, status_code=201)
def manual_price(item_id: int, body: ManualPriceIn, db: Session = Depends(get_db)):
    item = _load_item(db, item_id)
    slug = re.sub(r"[^a-z0-9]+", "-", body.store.lower()).strip("-") or "store"
    url = body.url or f"manual://{slug}"
    src = db.scalar(select(SourceLink).where(SourceLink.item_id == item.id, SourceLink.url == url))
    if src is None:
        src = SourceLink(item_id=item.id, url=url, title=body.store, status="confirmed", match_method="manual",
                         match_confidence=1.0)
        if not url.startswith("manual://"):
            src.retailer_id = get_or_create_retailer(db, url).id
        db.add(src)
        db.flush()
        db.refresh(src)
    _, previous = record_observation(
        db, src, price_cents=body.price_cents, was_price_cents=body.was_price_cents,
        shipping_cents=body.shipping_cents, in_stock=body.in_stock, seller=body.store, method="manual")
    db.commit()
    run_alerts(db, src, previous)
    return source_out(src, settings_store.get(db, "province"))


@router.get("/items/{item_id}/history")
def history(item_id: int, days: int = 120, db: Session = Depends(get_db)):
    item = _load_item(db, item_id)
    since = utcnow() - timedelta(days=days)
    rows = db.execute(
        select(Observation.source_link_id, Observation.observed_at, Observation.price_cents,
               Observation.was_price_cents, Observation.in_stock, Observation.method)
        .where(Observation.item_id == item.id, Observation.observed_at >= since)
        .order_by(Observation.observed_at)
    ).all()
    names = {s.id: (s.retailer.name if s.retailer else (s.title or s.url)) for s in item.sources}
    series: dict[int, dict] = {}
    for sid, at, price, was, stock, method in rows:
        if sid not in names:
            continue
        entry = series.setdefault(sid, {"source_id": sid, "name": names[sid], "points": []})
        entry["points"].append({
            "t": at.isoformat() + "Z", "price_cents": price, "was_price_cents": was,
            "in_stock": stock, "method": method,
        })
    return {"item_id": item.id, "series": list(series.values())}
