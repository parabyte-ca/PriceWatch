"""Basket optimiser: split a shopping list across stores for the lowest total after shipping, tax and perks.

Shipping is per order: free once the store's free-shipping threshold is reached, otherwise the store's flat rate
(or the listing's own shipping when the store has no rule). Small baskets are solved exactly; larger ones start from
each item's cheapest store and move items between stores while that lowers the total.
"""

import itertools
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..models import Item
from ..pricing import landed_price
from . import settings_store
from .perks import active_perks, after_perks

EXACT_LIMIT = 50_000
GAP_TIP_FRACTION = 0.35  # suggest topping up when the gap is under 35% of the threshold


@dataclass(frozen=True)
class Offer:
    item_id: int
    source_id: int
    retailer_key: str
    retailer_name: str
    domain: str | None
    price_cents: int
    shipping_cents: int | None
    url: str


def offers_for(item: Item) -> list[Offer]:
    from .summary import _offer_counts

    out = []
    for s in item.sources:
        if s.status != "confirmed" or s.last_price_cents is None or s.last_in_stock is False:
            continue
        if (s.channel or "online") != "online" or not _offer_counts(item, s.last_condition, s.last_seller_type):
            continue
        r = s.retailer
        out.append(Offer(item.id, s.id, r.domain if r else s.url, r.name if r else (s.title or s.url),
                         r.domain if r else None, s.last_price_cents, s.last_shipping_cents, s.url))
    return out


class _Store:
    def __init__(self, retailer, perks):
        self.threshold = retailer.free_shipping_threshold_cents if retailer else None
        self.flat = retailer.default_shipping_cents if retailer else None
        self.perks = perks


def _group_cost(offers: list[Offer], store: _Store, province: str, overrides: dict, use_perks: bool) -> dict:
    subtotal = sum(o.price_cents for o in offers)
    if store.threshold is not None and subtotal >= store.threshold:
        shipping, known = 0, True
    elif store.flat is not None:
        shipping, known = store.flat, True
    else:
        known = all(o.shipping_cents is not None for o in offers)
        shipping = sum(o.shipping_cents or 0 for o in offers)
    landed = landed_price(subtotal, shipping, province, overrides)
    total = landed["landed_cents"]
    perk_info = after_perks(total, store.perks) if (use_perks and store.perks) else None
    return {"subtotal_cents": subtotal, "shipping_cents": shipping, "shipping_known": known,
            "tax_cents": landed["tax_cents"], "total_cents": total,
            "after_perks_cents": perk_info["after_perks_cents"] if perk_info else total,
            "perks": perk_info["perks"] if perk_info else []}


def optimise(db: Session, items: list[Item], user_id: int | None, use_perks: bool = True) -> dict:
    cfg = settings_store.get_all(db, user_id)
    province, overrides = cfg["province"], cfg.get("tax_overrides") or {}
    choices: dict[int, list[Offer]] = {}
    missing = []
    stores: dict[str, _Store] = {}
    for item in items:
        offers = offers_for(item)
        if not offers:
            missing.append({"item_id": item.id, "name": item.name})
            continue
        choices[item.id] = offers
        by_id = {s.id: s for s in item.sources}
        for o in offers:
            if o.retailer_key not in stores:
                stores[o.retailer_key] = _Store(by_id[o.source_id].retailer,
                                                active_perks(db, o.domain) if o.domain else [])
    names = {i.id: i.name for i in items}

    def cost(assign: dict[int, Offer]) -> int:
        groups = defaultdict(list)
        for o in assign.values():
            groups[o.retailer_key].append(o)
        return sum(_group_cost(g, stores[k], province, overrides, use_perks)["after_perks_cents"]
                   for k, g in groups.items())

    ids = list(choices)
    combos = 1
    for i in ids:
        combos *= len(choices[i])
    if not ids:
        best, method = {}, "none"
    elif combos <= EXACT_LIMIT:
        method = "exact"
        best, best_cost = None, None
        for picks in itertools.product(*(choices[i] for i in ids)):
            assign = dict(zip(ids, picks, strict=True))
            c = cost(assign)
            if best_cost is None or c < best_cost:
                best, best_cost = assign, c
    else:
        method = "local search"
        best = {i: min(choices[i], key=lambda o: cost({i: o})) for i in ids}
        best_cost, improved = cost(best), True
        while improved:
            improved = False
            for i in ids:
                for o in choices[i]:
                    if o is best[i]:
                        continue
                    trial = {**best, i: o}
                    c = cost(trial)
                    if c < best_cost:
                        best, best_cost, improved = trial, c, True

    # each item bought on its own, at its cheapest store
    separately = sum(min(cost({i: o}) for o in choices[i]) for i in ids)
    groups = defaultdict(list)
    for o in (best or {}).values():
        groups[o.retailer_key].append(o)
    plan, tips = [], []
    for key, offers in sorted(groups.items(), key=lambda kv: kv[1][0].retailer_name):
        store = stores[key]
        g = _group_cost(offers, store, province, overrides, use_perks)
        gap = (store.threshold - g["subtotal_cents"]) if store.threshold and g["subtotal_cents"] < store.threshold else 0
        if gap and store.flat and gap <= store.threshold * GAP_TIP_FRACTION:
            tips.append(f"{offers[0].retailer_name}: add ${gap / 100:,.2f} more for free shipping "
                        f"(saves ${store.flat / 100:,.2f} shipping).")
        plan.append({"retailer": offers[0].retailer_name, "domain": offers[0].domain,
                     "items": [{"item_id": o.item_id, "name": names[o.item_id], "price_cents": o.price_cents,
                                "url": o.url, "source_id": o.source_id} for o in offers],
                     "free_shipping_threshold_cents": store.threshold, "free_shipping_gap_cents": gap, **g})
    total = sum(p["after_perks_cents"] for p in plan)
    return {"stores": plan, "total_cents": total, "separately_cents": separately,
            "saving_cents": separately - total, "missing": missing, "tips": tips, "method": method,
            "use_perks": use_perks, "province": province,
            "unknown_shipping": any(not p["shipping_known"] for p in plan)}
