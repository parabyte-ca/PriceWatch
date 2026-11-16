"""Cash-back, gift card and card offers that stack on a store's price. Entered by hand; never scraped."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import RetailerPerk
from .events import local_now


def active_perks(db: Session, domain: str | None) -> list[RetailerPerk]:
    if not domain:
        return []
    today = local_now().date()
    rows = db.scalars(select(RetailerPerk).where(RetailerPerk.retailer_domain == domain,
                                                 RetailerPerk.active.is_(True))).all()
    return [p for p in rows if p.valid_until is None or p.valid_until >= today]


def after_perks(landed_cents: int, perks: list[RetailerPerk]) -> dict:
    """Stack percentages multiplicatively (a gift card bought at 10% off, then 5% cash back on the spend)."""
    value = float(landed_cents)
    parts = []
    for p in perks:
        if p.percent and p.percent > 0:
            saved = value * p.percent / 100
            value -= saved
            parts.append({"label": p.label, "kind": p.kind, "percent": p.percent, "saved_cents": round(saved)})
    return {"after_perks_cents": round(value), "perks": parts, "perks_saving_cents": landed_cents - round(value)}
