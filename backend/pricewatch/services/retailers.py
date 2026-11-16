"""Retailer lookup and seed data for common Canadian retailers."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..fetch.http import domain_of
from ..models import Retailer

# (domain, name, fetch mode, minimum seconds between requests, other names stores go by in search results).
# fetch mode "auto": PriceWatch reads the store page itself (Claude reads it if the store blocks);
# "search": the store blocks automated visits, so its prices come from the cross-store searches only.
# Price-match terms live in price_policies.
SEED = [
    # The Source became Best Buy Express, so its name points to Best Buy
    ("bestbuy.ca", "Best Buy Canada", "auto", None, ("best buy", "bestbuy", "the source", "best buy express")),
    ("walmart.ca", "Walmart Canada", "search", 60, ("walmart",)),
    ("canadiantire.ca", "Canadian Tire", "search", 45, ("canadian tire",)),
    ("sportchek.ca", "Sport Chek", "search", 45, ("sport chek", "sportchek")),
    ("staples.ca", "Staples Canada", "auto", None, ("staples",)),
    ("memoryexpress.com", "Memory Express", "auto", None, ("memory express",)),
    ("canadacomputers.com", "Canada Computers", "auto", None, ("canada computers",)),
    ("newegg.ca", "Newegg Canada", "auto", None, ("newegg",)),
    ("homedepot.ca", "Home Depot Canada", "auto", None, ("home depot", "the home depot")),
    ("costco.ca", "Costco Canada", "search", 60, ("costco",)),
    ("amazon.ca", "Amazon.ca", "search", None, ("amazon", "amazon ca")),
    ("visions.ca", "Visions Electronics", "auto", None, ("visions", "visions electronics")),
    ("londondrugs.com", "London Drugs", "auto", None, ("london drugs",)),
    ("indigo.ca", "Indigo", "auto", None, ("indigo", "chapters indigo")),
    ("shoppersdrugmart.ca", "Shoppers Drug Mart", "auto", None, ("shoppers drug mart", "shoppers")),
    ("gamestop.ca", "GameStop / EB Games", "auto", None, ("gamestop", "eb games")),
    ("toysrus.ca", "Toys R Us Canada", "auto", None, ("toys r us", "toysrus")),
    ("giantiger.com", "Giant Tiger", "auto", None, ("giant tiger",)),
    ("realcanadiansuperstore.ca", "Real Canadian Superstore", "search", None, ("real canadian superstore",
                                                                               "superstore")),
    ("rona.ca", "RONA", "auto", None, ("rona",)),
    ("lowes.ca", "Lowe's Canada", "auto", None, ("lowe's", "lowes")),
    ("thebrick.com", "The Brick", "auto", None, ("the brick",)),
    ("leons.ca", "Leon's", "auto", None, ("leon's", "leons")),
    ("mec.ca", "MEC", "auto", None, ("mec",)),
    ("simons.ca", "Simons", "auto", None, ("simons",)),
    ("well.ca", "Well.ca", "auto", None, ("well",)),
    ("princessauto.com", "Princess Auto", "auto", None, ("princess auto",)),
    ("leevalley.com", "Lee Valley", "auto", None, ("lee valley",)),
    ("nintendo.com", "Nintendo Store", "auto", None, ("nintendo", "my nintendo store")),
    ("apple.com", "Apple", "auto", None, ("apple",)),
    ("samsung.com", "Samsung Canada", "auto", None, ("samsung",)),
    ("dell.com", "Dell Canada", "auto", None, ("dell",)),
    ("lenovo.com", "Lenovo Canada", "auto", None, ("lenovo",)),
    ("sony.ca", "Sony Canada", "auto", None, ("sony",)),
    ("bose.ca", "Bose Canada", "auto", None, ("bose",)),
    ("dyson.ca", "Dyson Canada", "auto", None, ("dyson",)),
]
MARKETPLACES = ("ebay", "aliexpress", "temu", "wish", "desertcart", "ubuy", "etsy", "poshmark", "kijiji",
                "facebook", "mercari", "back market", "backmarket", "amazon marketplace")


def _norm(name: str) -> str:
    import re

    n = (name or "").lower().strip()
    n = re.sub(r"^www\.", "", n)
    n = re.sub(r"\.(ca|com)\b.*$", "", n)
    n = re.sub(r"\b(canada|ca|inc|ltd|online|store)\b", " ", n)
    return re.sub(r"[^a-z0-9' ]+", " ", n).strip()


_ALIASES = {_norm(alias): domain for domain, _, _, _, aliases in SEED for alias in aliases}


def domain_for_merchant(name: str) -> str | None:
    """The store's domain from the name search results use ("Walmart.ca", "Best Buy", "EB Games"), if known."""
    n = _norm(name)
    if n in _ALIASES:
        return _ALIASES[n]
    for alias, domain in _ALIASES.items():  # "Walmart - Seller", "Best Buy Marketplace"
        if n.startswith(alias + " "):
            return domain
    return None


def merchant_kind(name: str) -> str:
    """"store" for the store itself, "marketplace" for a third-party seller or a marketplace site."""
    n = (name or "").lower()
    if any(m in n for m in MARKETPLACES) or "marketplace" in n or " - " in n or "seller" in n:
        return "marketplace"
    return "store"


def seed_retailers(db: Session) -> None:
    from .policies import seed_policies

    existing = {r.domain: r for r in db.scalars(select(Retailer)).all()}
    for domain, name, mode, interval, _ in SEED:
        if domain not in existing:
            db.add(Retailer(domain=domain, name=name, fetch_mode=mode, min_interval_seconds=interval))
        elif mode == "search" and existing[domain].fetch_mode in ("auto", "browser", "keepa"):
            existing[domain].fetch_mode = "search"  # blocks automated visits: prices come from searches
    db.commit()
    seed_policies(db)


def _pretty_name(domain: str) -> str:
    base = domain.split(".")[0]
    return base.replace("-", " ").title()


def get_or_create_retailer(db: Session, url: str, domain: str | None = None) -> Retailer:
    domain = domain or domain_of(url)
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
