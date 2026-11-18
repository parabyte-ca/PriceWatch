"""Deals for a category through Claude's web search, for kinds of products Google Shopping and the forum rarely show.

Claude searches the web from Canada for products in the category currently on sale at Canadian online stores and
reports each one through a small strict tool: title, store, link, price and regular price. Anthropic's search tool
identifies itself and follows sites' rules; PriceWatch keeps its own limits on top: Google pages, CamelCamelCamel,
Keepa and Rakuten are excluded, only https links are kept, and a deal needs a regular price above today's.

Each search counts against the household's monthly Claude cap (Household admin, Claude card).
"""

import logging
from dataclasses import dataclass

from ..adapters.base import parse_price
from ..fetch.http import domain_of
from . import claude

log = logging.getLogger(__name__)
EST_USD = 0.06  # rough cost of one category search, used to stop before the cap is passed
BLOCKED = ["google.com", "google.ca", "camelcamelcamel.com", "keepa.com", "rakuten.ca", "rakuten.com"]
MAX_DEALS = 15

REPORT_TOOL = {
    "name": "report_deals",
    "description": "Report the sale listings you found. Call once, at the end.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["deals"],
        "properties": {
            "deals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["title", "store", "url", "price", "was_price"],
                    "properties": {
                        "title": {"type": "string", "description": "Product title as the store shows it"},
                        "store": {"type": "string", "description": "Store name"},
                        "url": {"type": "string", "description": "The store's product page URL"},
                        "price": {"type": "string", "description": "Current sale price in CAD as shown, e.g. $49.99"},
                        "was_price": {"type": ["string", "null"], "description": "Regular price as shown, else null"},
                    },
                },
            },
        },
    },
}
SYSTEM = ("You find current sale prices for a kind of product at online stores that sell to Canada, in Canadian "
          "dollars. Use web_search, then report only listings you actually saw with a sale price and a higher regular "
          "price, each with the store's own product page link. Prefer Canadian stores. Skip marketplaces' third-party "
          "sellers, coupons, price trackers and listings without a price. Never guess or estimate. Report at most "
          f"{MAX_DEALS} listings, best discounts first, then call report_deals once. If you find none, report an empty "
          "list.")


@dataclass
class FoundDeal:
    title: str
    store: str
    url: str
    price_cents: int
    was_cents: int


class Unavailable(Exception):
    """No key, or the monthly cap is reached."""


def ready() -> tuple[bool, str]:
    if not claude.api_key():
        return False, "no Claude key saved"
    left = claude.budget_left()
    if left is not None and left < EST_USD:
        return False, "this month's Claude spending cap is reached"
    return True, ""


def _tools(model: str) -> list[dict]:
    search = {"type": "web_search_20250305" if "haiku" in model else "web_search_20260209", "name": "web_search",
              "max_uses": 3, "blocked_domains": BLOCKED,
              "user_location": {"type": "approximate", "country": "CA", "timezone": "America/Toronto"}}
    return [search, REPORT_TOOL]


def _clean(rows: list[dict]) -> list[FoundDeal]:
    out, seen = [], set()
    for r in rows or []:
        url = str(r.get("url") or "")
        host = domain_of(url).removeprefix("www.") if url.startswith("https://") else ""
        if not host or any(host == b or host.endswith("." + b) for b in BLOCKED) or url in seen:
            continue
        price, was = parse_price(r.get("price")), parse_price(r.get("was_price"))
        if not price or price <= 0 or not was or was <= price:
            continue
        seen.add(url)
        out.append(FoundDeal(title=str(r.get("title") or "")[:500], store=str(r.get("store") or host)[:120], url=url,
                             price_cents=price, was_cents=was))
    return out[:MAX_DEALS]


async def find(category: str, words: list[str], min_discount_pct: int, *, client_factory=None) -> list[FoundDeal]:
    """Ask Claude for current sale listings in a category. Raises Unavailable without a key or budget."""
    import anthropic

    ok, why = ready()
    if not ok:
        raise Unavailable(why)
    key = claude.api_key()
    model = claude.PRICE_MODEL
    api = (client_factory or (lambda: anthropic.AsyncAnthropic(api_key=key, timeout=120.0, max_retries=1)))()
    prompt = (f"Category: {category}\n" + (f"Search words: {', '.join(words)}\n" if words != [category] else "")
              + f"Only listings at least {min_discount_pct}% below their regular price.")
    msgs: list = [{"role": "user", "content": prompt}]
    usd, searches = 0.0, 0
    try:
        for _ in range(4):
            resp = await api.messages.create(model=model, max_tokens=6000, system=SYSTEM, messages=msgs,
                                             tools=_tools(model), output_config={"effort": "low"})
            usd += claude.cost_usd(model, resp.usage)
            stu = getattr(resp.usage, "server_tool_use", None)
            searches += (getattr(stu, "web_search_requests", 0) or 0) if stu is not None else 0
            if resp.stop_reason == "refusal":
                return []
            report = next((b for b in resp.content if b.type == "tool_use" and b.name == "report_deals"), None)
            if report is not None:
                deals = [d for d in _clean((report.input or {}).get("deals") or [])
                         if (d.was_cents - d.price_cents) * 100 / d.was_cents >= (min_discount_pct or 0)]
                return deals
            if resp.stop_reason != "pause_turn":
                return []
            msgs.append({"role": "assistant", "content": resp.content})
        return []
    except anthropic.APIError as exc:
        log.info("claude deals: %s", exc)
        return []
    finally:
        claude.record_spend(usd, searches=searches, check=True)
        await api.close()
