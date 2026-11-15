"""Retailer lookup and seed data for common Canadian retailers."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..fetch.http import domain_of
from ..models import Retailer

# Price-match notes are reminders to check the retailer's current policy, not policy text.
SEED = [
    ("bestbuy.ca", "Best Buy Canada", True),
    ("walmart.ca", "Walmart Canada", True),
    ("canadiantire.ca", "Canadian Tire", True),
    ("staples.ca", "Staples Canada", True),
    ("memoryexpress.com", "Memory Express", True),
    ("canadacomputers.com", "Canada Computers", True),
    ("newegg.ca", "Newegg Canada", False),
    ("thesource.ca", "The Source", False),
    ("homedepot.ca", "Home Depot Canada", True),
    ("costco.ca", "Costco Canada", False),
    ("amazon.ca", "Amazon.ca", False),
    ("visions.ca", "Visions Electronics", True),
    ("londondrugs.com", "London Drugs", True),
    ("thebay.com", "Hudson's Bay", False),
]


def seed_retailers(db: Session) -> None:
    existing = set(db.scalars(select(Retailer.domain)).all())
    for domain, name, pm in SEED:
        if domain not in existing:
            db.add(Retailer(domain=domain, name=name, price_match=pm,
                            price_match_notes="Check the current price-match policy before relying on it." if pm else None))
    db.commit()


def _pretty_name(domain: str) -> str:
    base = domain.split(".")[0]
    return base.replace("-", " ").title()


def get_or_create_retailer(db: Session, url: str) -> Retailer:
    domain = domain_of(url)
    # match subdomains (e.g. shop.example.ca) to a parent domain when known
    candidates = [domain]
    parts = domain.split(".")
    for i in range(1, len(parts) - 1):
        candidates.append(".".join(parts[i:]))
    for cand in candidates:
        r = db.scalar(select(Retailer).where(Retailer.domain == cand))
        if r:
            return r
    r = Retailer(domain=domain, name=_pretty_name(domain))
    db.add(r)
    db.flush()
    return r
