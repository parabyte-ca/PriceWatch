"""Deals on Home: today's drops on your items, matching forum threads, and deals in categories you follow."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import CategoryDeal, DealCategory, User
from ..services import deals

router = APIRouter(prefix="/api", tags=["deals"])


@router.get("/deals/home")
def home_deals(db: Session = Depends(get_db), me: User = Depends(current_user)):
    return {"drops": deals.todays_drops(db, me), "threads": deals.matched_threads(db, me),
            "categories": deals.category_deals(db, me), "presets": deals.PRESETS}


class CategoryIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    min_discount_pct: int = Field(default=20, ge=0, le=90)
    max_price_cents: int | None = Field(default=None, ge=0)


@router.post("/deal-categories", status_code=201)
async def add_category(body: CategoryIn, background: BackgroundTasks, db: Session = Depends(get_db),
                       me: User = Depends(current_user)):
    name = " ".join(body.name.split())
    if db.scalar(select(DealCategory.id).where(DealCategory.user_id == me.id, DealCategory.name == name)):
        raise HTTPException(409, "You already follow that category")
    cat = DealCategory(user_id=me.id, name=name, min_discount_pct=body.min_discount_pct,
                       max_price_cents=body.max_price_cents)
    db.add(cat)
    db.commit()
    # fill it straight away from forum threads already seen in the last few days
    from datetime import timedelta

    from ..models import DealFeedEntry
    from ..timeutil import utcnow

    recent = db.scalars(select(DealFeedEntry).where(DealFeedEntry.created_at >= utcnow() - timedelta(days=4))
                        .order_by(DealFeedEntry.created_at.desc()).limit(150)).all()
    seen, rows = set(), []
    for e in recent:
        if e.url and e.url not in seen:
            seen.add(e.url)
            rows.append({"title": e.title, "link": e.url})
    if rows:
        found = await deals.sort_into_categories([cat], [r["title"] for r in rows])
        from .. import models as m
        from ..services.dealfeed import split_title

        for r, ids in zip(rows, found, strict=True):
            if cat.id in ids:
                tag, _t, price = split_title(r["title"])
                db.add(m.CategoryDeal(category_id=cat.id, title=r["title"][:500], url=r["link"][:1000], store=tag,
                                      price_cents=price, source="rfd"))
        db.commit()
    # someone in the household already follows it: share their recent deals; otherwise search for sales right away
    if not deals.copy_from_others(db, cat) and cat.last_search_at is None:
        background.add_task(_first_search, cat.id)
    return {"id": cat.id, "name": cat.name}


async def _first_search(cat_id: int) -> None:
    """The first Google Shopping "on sale" search for a new category, within the month's search pace."""
    from ..db import session_scope
    from ..serp import get_provider
    from ..services.discovery import _within_budget

    db = session_scope()
    try:
        cat = db.get(DealCategory, cat_id)
        provider = get_provider("serpapi")
        if cat is not None and provider is not None and _within_budget(db, provider):
            await deals.search_category(db, cat)
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception("first category search failed")
    finally:
        db.close()


@router.patch("/deal-categories/{cat_id}")
def edit_category(cat_id: int, body: CategoryIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    cat = db.get(DealCategory, cat_id)
    if cat is None or cat.user_id != me.id:
        raise HTTPException(404, "Category not found")
    cat.name, cat.min_discount_pct, cat.max_price_cents = " ".join(body.name.split()), body.min_discount_pct, \
        body.max_price_cents
    db.commit()
    return {"id": cat.id}


@router.delete("/deal-categories/{cat_id}", status_code=204)
def delete_category(cat_id: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    cat = db.get(DealCategory, cat_id)
    if cat is None or cat.user_id != me.id:
        raise HTTPException(404, "Category not found")
    db.delete(cat)
    db.commit()


@router.get("/category-deals/{deal_id}/history")
def deal_history(deal_id: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    """Every price this deal's link was seen at, and how today's price compares."""
    d = db.get(CategoryDeal, deal_id)
    cat = db.get(DealCategory, d.category_id) if d else None
    if d is None or cat is None or cat.user_id != me.id:
        raise HTTPException(404, "Deal not found")
    h = deals.history(db, d.url)
    verdict = None
    if d.price_cents and h["count"] >= 2:
        if d.price_cents <= h["low_cents"]:
            verdict = f"Lowest price seen in {h['count']} sightings"
        else:
            pct = round((d.price_cents - h["low_cents"]) * 100 / h["low_cents"])
            verdict = f"{pct}% above the lowest price seen"
    elif d.price_cents:
        verdict = "First time PriceWatch has seen this price"
    return {**h, "verdict": verdict, "price_cents": d.price_cents, "was_cents": d.was_cents, "score": d.score}


@router.post("/category-deals/{deal_id}/dismiss", status_code=204)
def dismiss_deal(deal_id: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    d = db.get(CategoryDeal, deal_id)
    cat = db.get(DealCategory, d.category_id) if d else None
    if d is None or cat is None or cat.user_id != me.id:
        raise HTTPException(404, "Deal not found")
    d.dismissed = True
    db.commit()


class PlanIn(BaseModel):
    budget_cents: int | None = Field(default=None, ge=0)
    item_ids: list[int] = Field(default_factory=list, max_length=200)


@router.get("/plan")
def get_plan(db: Session = Depends(get_db), me: User = Depends(current_user)):
    from ..services import plan

    return plan.build(db, me)


@router.put("/plan")
def put_plan(body: PlanIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    from ..services import plan

    plan.save(db, me, body.budget_cents, body.item_ids)
    return plan.build(db, me)


@router.post("/plan/practice")
async def practice_plan(db: Session = Depends(get_db), me: User = Depends(current_user)):
    """Rehearse a sale day now: the checklist, a re-check of up to 3 plan items and a note of recent drops."""
    from ..services import plan

    return await plan.practice(db, me)
