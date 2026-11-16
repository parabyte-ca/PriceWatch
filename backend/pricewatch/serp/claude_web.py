"""Find the same product at other Canadian stores with Claude's web search (Anthropic's search tool).

Used for discovery when no SerpApi or Bright Data key is set and the household has a Claude key. Claude searches only
the store domains PriceWatch knows (Canadian retailers), reports product-page links through a small tool, and those
links then go through PriceWatch's normal matcher and polite fetcher like any other suggestion. Nothing here scrapes
a search engine's result pages.
"""

import logging

import httpx

from ..adapters.base import parse_price
from ..services.matching import Candidate
from .base import ProviderError

log = logging.getLogger(__name__)
MAX_SEARCHES = 5
REPORT_TOOL = {
    "name": "report_listings",
    "description": "Report the product pages found, one entry per store. Call once, at the end.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["listings"],
        "properties": {"listings": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["title", "url", "store", "price"],
            "properties": {
                "title": {"type": "string", "description": "Product title as the store shows it"},
                "url": {"type": "string", "description": "Direct product page URL on the store's own site"},
                "store": {"type": "string"},
                "price": {"type": ["string", "null"], "description": "Price as shown, e.g. $429.99, or null"},
            }}}},
    },
}
SYSTEM = ("You find where a product is sold in Canada. Search the allowed Canadian store sites for the exact product "
          "(same model, size, colour and generation; new, sold by the store). Report direct product-page links on the "
          "stores' own sites, never search, category, marketplace-seller or review pages, at most one per store and at "
          "most 10 in all, then call report_listings once. If nothing matches, call it with an empty list.")


class ClaudeWebProvider:
    name = "claude"

    def __init__(self, api_key: str, model: str, domains: list[str], client_factory=None) -> None:
        import anthropic

        self.api_key = api_key
        self.model = model
        self.domains = domains[:64]
        self.client_factory = client_factory or (lambda: anthropic.AsyncAnthropic(api_key=api_key, timeout=180.0,
                                                                                   max_retries=1))

    def _search_tool(self) -> dict:
        kind = "web_search_20250305" if "haiku" in self.model else "web_search_20260209"
        tool = {"type": kind, "name": "web_search", "max_uses": MAX_SEARCHES,
                "user_location": {"type": "approximate", "country": "CA", "timezone": "America/Toronto"}}
        if self.domains:
            tool["allowed_domains"] = self.domains
        return tool

    async def search(self, query: str, client: httpx.AsyncClient | None = None) -> list[Candidate]:
        import anthropic

        from ..services import claude

        left = claude.budget_left()
        if left is not None and left < 0.05:
            raise ProviderError("this month's Claude spending cap is reached")
        api = self.client_factory()
        msgs: list = [{"role": "user", "content": f"Product: {query}"}]
        usd, searches = 0.0, 0
        try:
            for _ in range(4):  # a long server-side search can pause; resend to let it continue
                try:
                    resp = await api.messages.create(
                        model=self.model, max_tokens=8000, system=SYSTEM, messages=msgs,
                        tools=[self._search_tool(), REPORT_TOOL], output_config={"effort": "low"})
                except anthropic.APIStatusError as exc:
                    raise ProviderError(f"Claude web search failed (HTTP {exc.status_code})") from exc
                except anthropic.APIConnectionError as exc:
                    raise ProviderError("could not reach api.anthropic.com") from exc
                usd += claude.cost_usd(self.model, getattr(resp, "usage", None))
                stu = getattr(getattr(resp, "usage", None), "server_tool_use", None)
                searches += (getattr(stu, "web_search_requests", 0) or 0) if stu is not None else 0
                if resp.stop_reason == "refusal":
                    return []
                report = next((b for b in resp.content if b.type == "tool_use" and b.name == "report_listings"), None)
                if report is not None:
                    return self._candidates(report.input)
                if resp.stop_reason != "pause_turn":
                    return []
                msgs.append({"role": "assistant", "content": resp.content})
            return []
        finally:
            claude.record_spend(usd, searches=searches)
            await api.close()

    def _candidates(self, data: dict) -> list[Candidate]:
        out = []
        for row in (data or {}).get("listings", [])[:10]:
            url, title = str(row.get("url") or ""), str(row.get("title") or "")
            if not url.startswith(("http://", "https://")) or not title:
                continue
            out.append(Candidate(title=title[:500], url=url, price_cents=parse_price(row.get("price")),
                                 merchant=str(row.get("store") or "")[:100] or None, provider=self.name))
        return out
