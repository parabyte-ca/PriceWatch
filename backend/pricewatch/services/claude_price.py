"""Read a product's current price with Claude when the store blocks PriceWatch's own page check.

Big Canadian stores (Best Buy, Walmart, Canadian Tire) often answer a home connection with a bot check. PriceWatch
never tries to get past those. Instead, when the household has a Claude key and the fallback is on, Claude looks the
product up with Anthropic's web search and web fetch tools, limited to that one store's site, and reports the price
it saw through a small strict tool. Anthropic's tools identify themselves and follow the sites' rules; if the store
refuses them too, nothing is recorded.

Each lookup is counted against the household's monthly cap (Household admin, Claude card).
"""

import logging
import time
from dataclasses import dataclass

from ..adapters.base import parse_price
from ..fetch.http import domain_of
from . import claude

log = logging.getLogger(__name__)
MIN_HOURS = 12  # a blocked source is read through Claude at most twice a day
EST_CHECK_USD = 0.03  # rough cost of one lookup, used to stop before the cap is passed
REUSE_S = 30 * 60  # a preview's answer is reused by the first check after saving, so it is not paid for twice
_recent: dict[str, tuple[float, "ClaudePrice"]] = {}

REPORT_TOOL = {
    "name": "report_price",
    "description": "Report the product's current price at this store. Call once, at the end.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["found", "title", "price", "was_price", "in_stock", "seen_on", "product_url"],
        "properties": {
            "found": {"type": "boolean", "description": "True only if you saw a current price for this exact product"},
            "title": {"type": ["string", "null"], "description": "Product title as the store shows it"},
            "price": {"type": ["string", "null"], "description": "Current selling price in CAD as shown, e.g. $429.99"},
            "was_price": {"type": ["string", "null"], "description": "Regular price if shown as on sale, else null"},
            "in_stock": {"type": ["boolean", "null"], "description": "Online availability if shown, else null"},
            "seen_on": {"type": "string", "enum": ["product_page", "search_result", "not_found"]},
            "product_url": {"type": ["string", "null"], "description": "The store's product page URL"},
        },
    },
}
SYSTEM = ("You read the current price of one product at one Canadian store. Use web_fetch on the product URL if one is "
          "given; if that fails or none is given, use web_search on the store's site. Report only a price you actually "
          "saw for this exact product (same model, size and colour), sold new by the store, in Canadian dollars. Never "
          "guess or estimate. If the page or results do not show a price, report found=false. Then call report_price "
          "once.")


@dataclass
class ClaudePrice:
    price_cents: int
    was_price_cents: int | None
    in_stock: bool | None
    title: str | None
    url: str
    seen_on: str
    usd: float

    @property
    def confidence(self) -> float:
        return 0.8 if self.seen_on == "product_page" else 0.6


class Unavailable(Exception):
    """No key, fallback switched off, or the monthly cap is reached."""


def ready() -> tuple[bool, str]:
    if not claude.api_key():
        return False, "no Claude key saved"
    if not claude.price_fallback_on():
        return False, "Claude price checks are switched off"
    left = claude.budget_left()
    if left is not None and left < EST_CHECK_USD:
        return False, "this month's Claude spending cap is reached"
    return True, ""


def _tools(model: str, domain: str, with_fetch: bool) -> list[dict]:
    basic = "haiku" in model
    search = {"type": "web_search_20250305" if basic else "web_search_20260209", "name": "web_search", "max_uses": 2,
              "allowed_domains": [domain],
              "user_location": {"type": "approximate", "country": "CA", "timezone": "America/Toronto"}}
    tools = [search]
    if with_fetch:
        tools.append({"type": "web_fetch_20250910" if basic else "web_fetch_20260209", "name": "web_fetch",
                      "max_uses": 1, "allowed_domains": [domain], "max_content_tokens": 12000})
    return [*tools, REPORT_TOOL]


async def lookup(url: str, name: str | None = None, *, client_factory=None) -> ClaudePrice | None:
    """Ask Claude for the current price of the product at ``url``. Returns None when no price was seen."""
    import anthropic

    hit = _recent.get(url)
    if hit and time.monotonic() - hit[0] < REUSE_S:
        return hit[1]
    ok, why = ready()
    if not ok:
        raise Unavailable(why)
    key = claude.api_key()
    model = claude.PRICE_MODEL
    domain = domain_of(url).removeprefix("www.")
    api = (client_factory or (lambda: anthropic.AsyncAnthropic(api_key=key, timeout=120.0, max_retries=1)))()
    prompt = f"Store: {domain}\nProduct URL: {url}\n" + (f"Product name: {name}\n" if name else "")
    msgs: list = [{"role": "user", "content": prompt}]
    usd, searches, with_fetch = 0.0, 0, True
    try:
        for _ in range(4):
            try:
                resp = await api.messages.create(model=model, max_tokens=4000, system=SYSTEM, messages=msgs,
                                                 tools=_tools(model, domain, with_fetch),
                                                 output_config={"effort": "low"})
            except anthropic.BadRequestError as exc:
                if with_fetch:  # an account or model without web fetch: try search alone
                    log.info("claude price: retrying without web fetch (%s)", exc.message)
                    with_fetch = False
                    continue
                raise
            usd += claude.cost_usd(model, resp.usage)
            stu = getattr(resp.usage, "server_tool_use", None)
            searches += (getattr(stu, "web_search_requests", 0) or 0) if stu is not None else 0
            if resp.stop_reason == "refusal":
                return None
            report = next((b for b in resp.content if b.type == "tool_use" and b.name == "report_price"), None)
            if report is not None:
                found = _result(report.input, url, usd)
                if found is not None:
                    _recent[url] = (time.monotonic(), found)
                    if len(_recent) > 200:
                        _recent.pop(next(iter(_recent)))
                return found
            if resp.stop_reason != "pause_turn":
                return None
            msgs.append({"role": "assistant", "content": resp.content})
        return None
    finally:
        claude.record_spend(usd, searches=searches, check=True)
        await api.close()


def _result(data: dict, url: str, usd: float) -> ClaudePrice | None:
    if not data or not data.get("found") or data.get("seen_on") == "not_found":
        return None
    price = parse_price(data.get("price"))
    if not price or price <= 0:
        return None
    was = parse_price(data.get("was_price"))
    page = str(data.get("product_url") or "")
    # only trust a page on the same store; otherwise keep the link the household saved
    same_store = page.startswith("https://") and domain_of(page).removeprefix("www.") == domain_of(url).removeprefix("www.")
    return ClaudePrice(price_cents=price, was_price_cents=was if was and was > price else None,
                       in_stock=data.get("in_stock"), title=(data.get("title") or None),
                       url=page if same_store else url, seen_on=str(data.get("seen_on")), usd=usd)
