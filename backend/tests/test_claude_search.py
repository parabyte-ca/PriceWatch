"""Claude web-search discovery provider and the household Claude key."""

from types import SimpleNamespace as NS

from pricewatch.serp.claude_web import ClaudeWebProvider


class FakeAPI:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    @property
    def messages(self):
        return self

    async def create(self, **kw):
        self.calls.append(kw)
        return self.responses.pop(0)

    async def close(self):
        pass


def _report(listings):
    return NS(stop_reason="tool_use", content=[NS(type="tool_use", name="report_listings", input={"listings": listings})])


async def test_provider_reports_candidates_and_limits_to_store_domains():
    paused = NS(stop_reason="pause_turn", content=[NS(type="server_tool_use", name="web_search", input={})])
    api = FakeAPI([paused, _report([
        {"title": "Sony WH-1000XM6 Headphones Black", "url": "https://www.staples.ca/products/123", "store": "Staples",
         "price": "$429.99"},
        {"title": "bad", "url": "javascript:alert(1)", "store": "x", "price": None},
    ])])
    p = ClaudeWebProvider("k", "claude-opus-5-5", ["bestbuy.ca", "staples.ca"], client_factory=lambda: api)
    cands = await p.search("Sony WH-1000XM6")
    assert [(c.url, c.price_cents, c.merchant, c.provider) for c in cands] == [
        ("https://www.staples.ca/products/123", 42999, "Staples", "claude")]
    assert len(api.calls) == 2  # resumed after pause_turn
    tool = api.calls[0]["tools"][0]
    assert tool["type"] == "web_search_20260209" and tool["allowed_domains"] == ["bestbuy.ca", "staples.ca"]
    assert tool["user_location"]["country"] == "CA" and api.calls[0]["tools"][1]["strict"] is True
    h = ClaudeWebProvider("k", "claude-haiku-5-5", [], client_factory=lambda: FakeAPI([]))
    assert h._search_tool()["type"] == "web_search_20250305" and "allowed_domains" not in h._search_tool()


async def test_provider_empty_when_nothing_reported():
    api = FakeAPI([NS(stop_reason="end_turn", content=[NS(type="text", text="none")])])
    assert await ClaudeWebProvider("k", "claude-sonnet-5-5", [], client_factory=lambda: api).search("x") == []


def test_household_key_is_encrypted_and_used(client, db_session, monkeypatch):
    from pricewatch.models import SettingKV
    from pricewatch.serp import registry
    from pricewatch.services import claude

    claude.save(db_session, True, "claude-sonnet-5-5", "medium", "sk-ant-test-123")
    raw = db_session.get(SettingKV, claude.API_KEY_KEY).value
    assert "sk-ant" not in raw and claude.stored_key(db_session) == "sk-ant-test-123"
    claude.forget_cache()
    assert claude.api_key() == "sk-ant-test-123"
    providers = registry.available_providers()
    assert "claude" in providers and providers["claude"].model == "claude-sonnet-5-5"
    assert "bestbuy.ca" in providers["claude"].domains
    client.patch("/api/settings", json={"web_search_enabled": False})
    assert "claude" not in registry.available_providers()
    claude.forget_key(db_session)
    assert claude.api_key() is None




async def test_ask_pricewatch_reads_through_its_own_api(client, db_session):
    from pricewatch import main
    from pricewatch.services import claude
    from pricewatch.services.assistant import Assistant

    client.post("/api/items", json={"name": "LEGO Titanic", "target_price_cents": 50000})
    lst = client.get("/api/lists").json()[0]
    client.post(f"/api/lists/{lst['id']}/share", json={})
    claude.save(db_session, True, "claude-opus-5-5", "low", "sk-ant-x")
    seen = {}

    class Beta:
        def __init__(self):
            self.n = 0

        async def create(self, **kw):
            self.n += 1
            seen.setdefault("calls", []).append(kw)
            if self.n == 1:
                return NS(stop_reason="tool_use", model=kw["model"], usage=NS(input_tokens=1, output_tokens=1),
                          content=[NS(type="tool_use", id="a", name="list_items", input={}),
                                   NS(type="tool_use", id="b", name="lists", input={})])
            return NS(stop_reason="end_turn", model=kw["model"], usage=NS(input_tokens=1, output_tokens=1),
                      content=[NS(type="text", text="Wait on the LEGO Titanic.")])

    beta = Beta()
    fake = NS(beta=NS(messages=beta), close=lambda: _noop())

    async def _noop():
        return None

    a = Assistant(client.app if hasattr(client, "app") else main.app, client_factory=lambda key: fake)
    ans = await a.ask([{"role": "user", "content": "Should I buy anything?"}], {})
    assert ans.text == "Wait on the LEGO Titanic." and ans.tools == ["list_items", "lists"]
    results = seen["calls"][1]["messages"][-1]["content"]
    assert "LEGO Titanic" in results[0]["content"] and "share_link" not in results[1]["content"]
    assert seen["calls"][0]["betas"] == ["server-side-fallback-2026-07-01"]
    assert client.get("/api/ask").json()["available"] is True
    assert client.get("/api/admin/claude").json()["key_saved"] is True
    assert client.put("/api/admin/claude", json={"model": "gpt-4", "effort": "low"}).status_code == 422
    assert client.put("/api/admin/claude", json={"model": "claude-haiku-5-5", "effort": "low",
                                                 "api_key": "not-a-key"}).status_code == 422
