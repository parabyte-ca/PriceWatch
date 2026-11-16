"""Ask PriceWatch: questions about your list in plain language, answered by Claude (same design as Ask NetWatch).

Claude gets read-only tools that call PriceWatch's own API in-process with the asking person's sign-in, so it sees
exactly what that person sees in the app and cannot change anything (the tools only GET, plus the basket planner,
which computes and saves nothing). What the tools return (item names, prices, stores, purchases) is sent to
Anthropic to answer the question. Share links and notification addresses are removed before that.
"""

import asyncio
import json
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import anthropic
import httpx

from ..config import get_settings
from ..db import session_scope
from . import claude

log = logging.getLogger(__name__)

FALLBACK_MODELS = frozenset({"claude-opus-5-5", "claude-sonnet-5-5"})  # server-side refusal fallback (not Haiku)
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TURNS = 12
MAX_TOOL_CHARS = 24_000
MAX_HISTORY = 20
PER_HOUR = 40

SYSTEM = """You are Ask PriceWatch, the assistant built into PriceWatch, a self-hosted Canadian price tracker for a \
household's wishlists and gift lists. PriceWatch checks store pages on a schedule, keeps price history, works out \
landed prices (provincial sales tax and shipping), compares them with each item's seasonal low and target, and \
labels each item BUY, BUY + PROTECT (good price and the store refunds a later drop) or WAIT. It also tracks \
purchases and price-protection windows, cash-back perks, RedFlagDeals threads, weekly flyers and price-match \
policies.

Answer the person's question using the tools: look things up rather than guessing, and say so when the data does \
not cover the question. Lead with the answer, then the evidence (prices, stores, dates). Prices from the tools are \
in cents unless labelled; show dollars, and say whether a price is before tax or landed. Be honest about \
uncertainty: price history can be short, and a forecast is an estimate. You cannot buy, change settings, add items \
or run checks; say what to tap in the app instead. Keep answers short and plain, Canadian English; use a short \
list when it helps."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    properties: dict
    build: Callable[[dict], list[tuple[str, str, dict]]]  # input -> [(method, path, params or json)]
    shape: Callable[[list[Any]], Any] = lambda rs: rs[0] if len(rs) == 1 else rs
    required: tuple[str, ...] = ()

    def schema(self) -> dict:
        return {"name": self.name, "description": self.description,
                "input_schema": {"type": "object", "properties": self.properties, "required": list(self.required),
                                 "additionalProperties": False}}


def _item_row(i: dict) -> dict:
    s = i.get("summary") or {}
    best = s.get("best") or {}
    return {"id": i.get("id"), "name": i.get("name"), "list_id": i.get("list_id"), "verdict": s.get("decision"),
            "reason": s.get("decision_reason"), "best_price_before_tax": s.get("best_price_cents"),
            "best_landed": s.get("best_landed_cents"), "store": best.get("retailer"), "target": i.get("target_price_cents"),
            "seasonal_low_landed": s.get("seasonal_low_cents"), "history": s.get("history_confidence"),
            "fake_sale": s.get("fake_sale"), "stale": s.get("stale"), "active": i.get("active"),
            "price_match": s.get("price_match") or []}


def _items(rs: list[Any]) -> list[dict]:
    return [_item_row(i) for i in rs[0]][:200]


def _detail(rs: list[Any]) -> dict:
    item, hist, forecast, deals, flyers = rs
    series = []
    for s in hist.get("series", []):
        pts = [p for p in s.get("points", []) if p.get("price_cents") is not None]
        prices = [p["price_cents"] for p in pts]
        series.append({"store": s.get("name"), "points": len(pts), "first": pts[0]["t"] if pts else None,
                       "min": min(prices) if prices else None, "max": max(prices) if prices else None,
                       "latest": pts[-1] if pts else None, "recent": pts[-15:]})
    sources = [{k: src.get(k) for k in ("retailer_name", "url", "status", "last_price_cents", "last_in_stock",
                                        "last_checked_at", "last_error", "channel")} for src in item.get("sources") or []]
    return {"item": {**_item_row(item), **{k: item.get(k) for k in ("brand", "model", "gtin", "notes", "hot")},
                     "summary": item.get("summary")}, "stores": sources, "history_by_store": series,
            "will_it_get_cheaper": forecast, "forum_threads": deals[:10], "flyers": flyers[:10]}


def _lists(rs: list[Any]) -> list[dict]:
    return [{k: v for k, v in lst.items() if k not in ("share_link",)} for lst in rs[0]]


TOOLS: tuple[Tool, ...] = (
    Tool("list_items", "Every item on the person's lists with its verdict (BUY / BUY_AND_PROTECT / WAIT / NO_DATA), "
         "best price before tax and landed, store, target, seasonal low and price-match chances. Start here.",
         {"include_bought": {"type": "boolean", "description": "Also items no longer tracked (bought). Default false."}},
         lambda i: [("GET", "/api/items", {"include_inactive": "true"} if i.get("include_bought") else {})], _items),
    Tool("item_detail", "One item in depth: every store and its latest price, price history per store (min, max, "
         "recent points), the 'will it get cheaper' estimate, RedFlagDeals threads and flyer matches.",
         {"item_id": {"type": "integer"}, "days": {"type": "integer", "description": "History days, 7-365, default 120."}},
         lambda i: [("GET", f"/api/items/{int(i['item_id'])}", {}),
                    ("GET", f"/api/items/{int(i['item_id'])}/history",
                     {"days": max(7, min(int(i.get("days") or 120), 365))}),
                    ("GET", f"/api/items/{int(i['item_id'])}/forecast", {}),
                    ("GET", f"/api/items/{int(i['item_id'])}/deals", {}),
                    ("GET", f"/api/items/{int(i['item_id'])}/flyers", {})], _detail, ("item_id",)),
    Tool("purchases", "What the person bought: store, price, date, price-protection window and status, money "
         "claimable or claimed.", {}, lambda i: [("GET", "/api/purchases", {})]),
    Tool("savings", "Spending and savings totals: spent, saved against the usual price, claimed back, still to claim; "
         "by person and by list.", {}, lambda i: [("GET", "/api/savings", {})]),
    Tool("lists", "The person's lists: name, occasion, recipient, date, budget, spent and remaining.", {},
         lambda i: [("GET", "/api/lists", {})], _lists),
    Tool("plan_basket", "The cheapest way to buy several items across stores after free-shipping thresholds, tax "
         "and perks (computes only, saves nothing).",
         {"item_ids": {"type": "array", "items": {"type": "integer"}, "description": "Items to buy (max 60)."}},
         lambda i: [("POST", "/api/basket", {"item_ids": [int(x) for x in i["item_ids"]][:60]})], required=("item_ids",)),
    Tool("store_policies", "Price-match and price-adjustment policies per store (windows, exclusions, notes).", {},
         lambda i: [("GET", "/api/policies", {})]),
    Tool("perks", "Cash-back, gift-card and credit-card perks the household entered per store.", {},
         lambda i: [("GET", "/api/perks", {})]),
    Tool("recent_alerts", "The person's recent alerts (buy, drops, back in stock, protection claims, digests).",
         {"limit": {"type": "integer", "description": "1-100, default 30."}},
         lambda i: [("GET", "/api/alerts", {"limit": max(1, min(int(i.get("limit") or 30), 100))})]),
    Tool("sale_calendar", "Whether Black Friday or Boxing Week mode is on now, and their dates.", {},
         lambda i: [("GET", "/api/sale-mode", {})]),
)
BY_NAME = {t.name: t for t in TOOLS}


def _compact(value: Any) -> str:
    text = json.dumps(value, separators=(",", ":"), default=str)
    if len(text) > MAX_TOOL_CHARS:
        text = text[:MAX_TOOL_CHARS] + '…"[truncated: ask a narrower question]"'
    return text


class AskError(Exception):
    """A failure the person should see (no key, bad key, rate limit, Anthropic down)."""


@dataclass
class Answer:
    text: str
    tools: list[str] = field(default_factory=list)
    model: str = ""
    usage: dict = field(default_factory=dict)
    stop_reason: str | None = None


class Assistant:
    def __init__(self, app: Any, client_factory: Callable[[str], Any] | None = None) -> None:
        self.app = app  # the ASGI app the tools call
        self.client_factory = client_factory or (
            lambda key: anthropic.AsyncAnthropic(api_key=key, timeout=120.0, max_retries=2))
        self._recent: deque[float] = deque()
        self._slots = asyncio.Semaphore(2)

    def _config(self) -> dict:
        db = session_scope()
        try:
            return claude.config(db)
        finally:
            db.close()

    def available(self) -> bool:
        return bool(claude.api_key()) and self._config()["enabled"]

    def _throttle(self) -> None:
        now = time.monotonic()
        while self._recent and self._recent[0] < now - 3600:
            self._recent.popleft()
        if len(self._recent) >= PER_HOUR:
            raise AskError(f"limit of {PER_HOUR} questions an hour reached; try again later")
        self._recent.append(now)

    async def _call_tool(self, name: str, args: dict, auth: dict) -> tuple[str, bool]:
        tool = BY_NAME.get(name)
        if tool is None:
            return f"unknown tool {name}", True
        try:
            calls = tool.build(args or {})
        except (KeyError, TypeError, ValueError) as exc:
            return f"bad input: {exc}", True
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost", headers=auth, timeout=60) as http:
            results = []
            for method, path, params in calls:
                if method == "GET":
                    r = await http.get(path, params=params)
                elif method == "POST" and path == "/api/basket":  # the one read-only POST
                    r = await http.post(path, json=params)
                else:
                    return "not allowed", True
                if r.status_code >= 400:
                    return f"{path} answered {r.status_code}: {r.text[:300]}", True
                results.append(r.json())
        return _compact(tool.shape(results)), False

    async def ask(self, history: list[dict], auth: dict) -> Answer:
        key = await asyncio.to_thread(claude.api_key)
        cfg = await asyncio.to_thread(self._config)
        if not cfg["enabled"] or not key:
            raise AskError("Ask PriceWatch is off: the household admin saves an Anthropic API key in Household admin")
        self._throttle()
        zone = ZoneInfo(get_settings().timezone)
        now = datetime.now(zone)
        msgs: list[dict] = [{"role": m["role"], "content": m["content"]} for m in history[-MAX_HISTORY:]]
        # the clock goes with the question, not the system prompt, so the prompt stays cached
        msgs[-1] = {"role": "user", "content": f"{msgs[-1]['content']}\n\n(Now: {now:%Y-%m-%d %H:%M %Z}, "
                                                f"time zone {zone.key}.)"}
        model = cfg["model"]
        extra: dict[str, Any] = {}
        if model in FALLBACK_MODELS:
            extra = {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        tools = [t.schema() for t in TOOLS]
        used: list[str] = []
        usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}
        client = self.client_factory(key)
        try:
            async with self._slots:
                for _ in range(MAX_TURNS):
                    try:
                        resp = await client.beta.messages.create(
                            model=model, max_tokens=16000, system=SYSTEM, tools=tools, messages=msgs,
                            output_config={"effort": cfg["effort"]}, cache_control={"type": "ephemeral"}, **extra)
                    except anthropic.AuthenticationError:
                        raise AskError("the saved Anthropic API key was rejected") from None
                    except anthropic.RateLimitError:
                        raise AskError("Anthropic's rate limit was hit; try again shortly") from None
                    except anthropic.APIConnectionError:
                        raise AskError("could not reach api.anthropic.com") from None
                    except anthropic.APIStatusError as exc:
                        log.warning("Anthropic API error", extra={"status": exc.status_code})
                        raise AskError(f"Anthropic API error {exc.status_code}") from None
                    for k in usage:
                        usage[k] += getattr(resp.usage, k, 0) or 0
                    if resp.stop_reason == "refusal":
                        return Answer("Claude declined to answer that question.", used, resp.model, usage, "refusal")
                    if resp.stop_reason == "pause_turn":
                        msgs.append({"role": "assistant", "content": resp.content})
                        continue
                    calls = [b for b in resp.content if b.type == "tool_use"]
                    if resp.stop_reason != "tool_use" or not calls:
                        text = "\n\n".join(b.text for b in resp.content if b.type == "text")
                        if resp.stop_reason == "max_tokens":
                            text += "\n\n(The answer was cut short.)"
                        return Answer(text.strip(), used, resp.model, usage, resp.stop_reason)
                    msgs.append({"role": "assistant", "content": resp.content})
                    results = []
                    for b in calls:
                        used.append(b.name)
                        out, err = await self._call_tool(b.name, b.input, auth)
                        results.append({"type": "tool_result", "tool_use_id": b.id, "content": out}
                                       | ({"is_error": True} if err else {}))
                    msgs.append({"role": "user", "content": results})
        finally:
            await client.close()
        return Answer("That took too many steps; try a narrower question.", used, model, usage, "max_turns")
