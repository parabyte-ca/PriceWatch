"""Retailer price-match and price-protection policies (Canada). Stored as data; this is only the seed.

Sources: retailer help pages and the 2026-11-15 delta review. Each seed row records whether it was
verified; unverified rows are disabled until the user confirms the current policy.
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import PricePolicy
from .events import EVENT_LABELS, EVENTS_2026

SEED = [
    {
        "domain": "bestbuy.ca", "competitor_match": True, "own_price_adjustment": False,
        "window_days": 30, "member_window_days": 60,
        "excluded_events": ["black_friday", "cyber_monday", "boxing_day"],
        "excludes_marketplace": True, "excludes_open_box": True,
        "event_guarantee": "Black Friday Price Guarantee on badged items during the Black Friday sale (from Nov 19). "
                           "Check for the badge on the product page.",
        "verified": True, "enabled": True,
        "notes": "Low Price Guarantee: matches authorized Canadian dealers in your province. Excludes marketplace "
                 "sellers, Black Friday, Cyber Monday and Boxing Day prices, limited quantity and limited time offers. "
                 "The US Holiday Price Match Guarantee does not apply in Canada.",
        "source_url": "https://www.bestbuy.ca/en-ca/help/paying-and-purchasing/low-price-guarantee",
    },
    {
        "domain": "staples.ca", "competitor_match": True, "own_price_adjustment": False,
        "window_days": 30, "electronics_window_days": 14,
        "excluded_events": ["black_friday", "cyber_monday", "cyber_week", "boxing_week", "prime_day"],
        "excludes_marketplace": True, "excludes_open_box": True, "verified": True, "enabled": True,
        "notes": "Matches authorized resellers. Excludes marketplace, open box, refurbished, Black Friday, Cyber Week, "
                 "Boxing Week and Prime Day pricing, limited quantities.",
        "source_url": "https://help.staples.ca/hc/en-us/articles/360026191891-Price-match-information-and-policies",
    },
    {
        "domain": "costco.ca", "competitor_match": False, "own_price_adjustment": True, "window_days": 30,
        "excluded_events": [], "verified": True, "enabled": True,
        "notes": "Adjusts to its own lower price within 30 days (online via the Costco.ca form). Online and warehouse "
                 "prices are not interchangeable.",
    },
    {
        "domain": "walmart.ca", "competitor_match": False, "own_price_adjustment": False,
        "excluded_events": [], "verified": True, "enabled": True,
        "notes": "No competitor Ad Match since Oct 15, 2020. Stores match walmart.ca prices for identical items.",
    },
    {
        "domain": "canadiantire.ca", "competitor_match": False, "own_price_adjustment": False,
        "excluded_events": [], "verified": False, "enabled": False,
        "notes": "UNVERIFIED. Reported to have stopped price matching in August 2022; Associate Dealer stores may "
                 "differ. Ask your home store before relying on it.",
    },
]


def seed_policies(db: Session) -> None:
    existing = set(db.scalars(select(PricePolicy.domain)).all())
    for row in SEED:
        if row["domain"] not in existing:
            db.add(PricePolicy(**row))
    db.commit()


def policy_for(db: Session, domain: str | None) -> PricePolicy | None:
    if not domain:
        return None
    return db.scalar(select(PricePolicy).where(PricePolicy.domain == domain))


def events_excluded_today(policy: PricePolicy, today: date) -> list[str]:
    excluded = set(policy.excluded_events or [])
    return [EVENT_LABELS.get(e, e) for e, (start, end) in EVENTS_2026.items() if e in excluded and start <= today <= end]


def protection(policy: PricePolicy | None, purchase_day: date, horizon: date, member: bool) -> str | None:
    """How buying today stays protected through the horizon date, or None.

    Own-price adjustment counts when its window reaches the horizon (Costco: 30 days). An event guarantee
    (Best Buy's Black Friday Price Guarantee) counts during Black Friday week, on badged items only.
    """
    if policy is None or not policy.enabled:
        return None
    if policy.own_price_adjustment:
        days = (policy.member_window_days if member and policy.member_window_days else policy.window_days) or 0
        if purchase_day + timedelta(days=days) >= horizon:
            return f"{days}-day price adjustment"
    bf_start, bf_end = EVENTS_2026["black_friday_week"]
    if policy.event_guarantee and bf_start <= purchase_day <= bf_end:
        return "event price guarantee (badged items only)"
    return None
