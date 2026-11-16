"""Retailer lookup and seed data for common Canadian retailers."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..fetch.http import domain_of
from ..models import Retailer

# (domain, name, fetch mode, minimum seconds between requests). Price-match terms live in price_policies.
# The Source was folded into Best Buy (Best Buy Express) and is not seeded.
SEED = [
    ("bestbuy.ca", "Best Buy Canada", "auto", None),
    ("walmart.ca", "Walmart Canada", "browser", 60),
    ("canadiantire.ca", "Canadian Tire", "browser", 45),
    ("sportchek.ca", "Sport Chek", "auto", None),
    ("staples.ca", "Staples Canada", "auto", None),
    ("memoryexpress.com", "Memory Express", "auto", None),
    ("canadacomputers.com", "Canada Computers", "auto", None),
    ("newegg.ca", "Newegg Canada", "auto", None),
    ("homedepot.ca", "Home Depot Canada", "auto", None),
    ("costco.ca", "Costco Canada", "browser", 60),
    ("amazon.ca", "Amazon.ca", "keepa", None),
    ("visions.ca", "Visions Electronics", "auto", None),
    ("londondrugs.com", "London Drugs", "auto", None),
    ("indigo.ca", "Indigo", "auto", None),
    ("shoppersdrugmart.ca", "Shoppers Drug Mart", "auto", None),
]


def seed_retailers(db: Session) -> None:
    from .policies import seed_policies

    existing = {r.domain: r for r in db.scalars(select(Retailer)).all()}
    for domain, name, mode, interval in SEED:
        if domain not in existing:
            db.add(Retailer(domain=domain, name=name, fetch_mode=mode, min_interval_seconds=interval))
        elif domain == "amazon.ca" and existing[domain].fetch_mode == "auto":
            existing[domain].fetch_mode = "keepa"  # no direct Amazon scraping by default
        elif domain == "canadiantire.ca" and existing[domain].fetch_mode == "auto":
            existing[domain].fetch_mode = "browser"  # prices are rendered by script; plain pages carry none
            existing[domain].min_interval_seconds = existing[domain].min_interval_seconds or 45
    db.commit()
    seed_policies(db)


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
