"""Claude reads prices from stores that block PriceWatch's own check (v0.15.0)."""

from types import SimpleNamespace as NS

import pytest

from pricewatch.fetch.http import FetchResult

URL = "https://www.bestbuy.ca/en-ca/product/anker-solix-f3800-plus/18275631"


class FakeAPI:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    @property
    def messages(self):
        return self

    async def create(self, **kw):
        self.calls.append(kw)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    async def close(self):
        pass


def _usage(searches=1):
    return NS(input_tokens=20000, output_tokens=300, cache_read_input_tokens=0, cache_creation_input_tokens=0,
              server_tool_use=NS(web_search_requests=searches))


def _report(**kw):
    data = {"found": True, "title": "Anker SOLIX F3800 Plus Portable Power Station", "price": "$4,299.99",
            "was_price": "$4,999.99", "in_stock": True, "seen_on": "product_page", "product_url": URL}
    data.update(kw)
    return NS(stop_reason="tool_use", usage=_usage(), content=[NS(type="tool_use", name="report_price", input=data)])


@pytest.fixture
def with_key(db_session, monkeypatch):
    from pricewatch.services import claude, claude_price

    claude.save(db_session, True, "claude-opus-5-5", "medium", "sk-ant-test-1", monthly_cap_usd=15)
    claude.forget_cache()
    claude_price._recent.clear()
    return claude


def _fake(monkeypatch, responses):
    import anthropic

    api = FakeAPI(responses)
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **kw: api)
    return api


def _blocked(monkeypatch, module):
    async def fake(url, retailer, mode, **kw):
        return FetchResult(url=url, outcome="blocked", status_code=403, error="HTTP 403"), None, "http"

    monkeypatch.setattr(module, "fetch_and_parse", fake)


async def test_lookup_reads_price_store_only_and_counts_spend(with_key, db_session, monkeypatch):
    from pricewatch.services import claude_price

    api = _fake(monkeypatch, [_report()])
    found = await claude_price.lookup(URL, "Solix F3800 Plus")
    assert (found.price_cents, found.was_price_cents, found.in_stock, found.seen_on) == (429999, 499999, True,
                                                                                         "product_page")
    call = api.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    search, fetch, report = call["tools"]
    assert search["allowed_domains"] == ["bestbuy.ca"] and fetch["allowed_domains"] == ["bestbuy.ca"]
    assert search["type"] == "web_search_20250305" and fetch["type"] == "web_fetch_20250910"
    assert report["strict"] is True and URL in call["messages"][0]["content"]
    s = with_key.spend(db_session)
    assert s["checks"] == 1 and s["searches"] == 1 and 0.01 < s["usd"] < 0.02
    # reused by the check right after saving, not paid for twice
    assert (await claude_price.lookup(URL)) is found and len(api.calls) == 1


async def test_lookup_rejects_guesses_and_other_sites(with_key, monkeypatch):
    from pricewatch.services import claude_price

    _fake(monkeypatch, [_report(found=False, price=None, seen_on="not_found")])
    assert await claude_price.lookup(URL) is None
    _fake(monkeypatch, [_report(product_url="https://evil.example.com/x", seen_on="search_result")])
    found = await claude_price.lookup(URL)
    assert found.url == URL and found.confidence == 0.6


async def test_lookup_retries_without_fetch_on_bad_request(with_key, monkeypatch):
    import anthropic
    import httpx

    from pricewatch.services import claude_price

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    bad = anthropic.BadRequestError("web fetch not enabled", response=httpx.Response(400, request=req), body=None)
    api = _fake(monkeypatch, [bad, _report()])
    assert (await claude_price.lookup(URL)).price_cents == 429999
    assert [t["name"] for t in api.calls[1]["tools"]] == ["web_search", "report_price"]


async def test_cap_and_switch_stop_lookups(with_key, db_session, monkeypatch):
    from pricewatch.services import claude_price

    with_key.save(db_session, True, "claude-opus-5-5", "medium", None, monthly_cap_usd=0.01)
    assert claude_price.ready() == (False, "this month's Claude spending cap is reached")
    with_key.save(db_session, True, "claude-opus-5-5", "medium", None, monthly_cap_usd=0)  # 0 = no cap
    assert claude_price.ready()[0]
    with_key.save(db_session, True, "claude-opus-5-5", "medium", None, price_fallback=False)
    with pytest.raises(claude_price.Unavailable):
        await claude_price.lookup(URL)


def test_preview_falls_back_to_claude_when_store_blocks(client, with_key, monkeypatch):
    from pricewatch.api import items

    _blocked(monkeypatch, items)
    _fake(monkeypatch, [_report()])
    r = client.post("/api/preview", json={"url": URL}).json()
    assert r["outcome"] == "blocked" and r["method"] == "claude"
    assert r["product"]["price_cents"] == 429999 and r["claude"]["found"] is True


def test_preview_explains_when_no_key(client, db_session, monkeypatch):
    from pricewatch.api import items
    from pricewatch.services import claude

    claude.forget_cache()
    _blocked(monkeypatch, items)
    r = client.post("/api/preview", json={"url": URL}).json()
    assert r["product"]["price_cents"] is None
    assert r["claude"] == {"used": False, "reason": "no Claude key saved"}


async def test_blocked_check_records_claude_price_twice_a_day_at_most(client, with_key, db_session, monkeypatch):
    from pricewatch.models import Observation
    from pricewatch.services import checker, claude_price

    _blocked(monkeypatch, checker)
    item = client.post("/api/items", json={"name": "Solix F3800 Plus"}).json()
    src = client.post(f"/api/items/{item['id']}/sources", json={"url": URL}).json()
    api = _fake(monkeypatch, [_report(), _report(price="$3,999.99")])
    assert await checker.check_source(src["id"]) == "ok"
    obs = db_session.query(Observation).filter_by(source_link_id=src["id"]).all()
    assert [(o.price_cents, o.method) for o in obs] == [(429999, "claude")]
    detail = client.get(f"/api/items/{item['id']}").json()
    assert detail["sources"][0]["last_method"] == "claude" and detail["sources"][0]["last_price_cents"] == 429999
    claude_price._recent.clear()
    assert await checker.check_source(src["id"]) == "blocked"  # within 12 h: no second paid lookup
    assert len(api.calls) == 1


async def test_verify_reads_a_search_only_store_now(client, with_key, db_session, monkeypatch):
    from pricewatch.models import Observation
    from pricewatch.services import checker

    item = client.post("/api/items", json={"name": "Nintendo Switch 2"}).json()
    src = client.post(f"/api/items/{item['id']}/sources",
                      json={"url": "https://www.walmart.ca/en/ip/nintendo-switch-2/6000201"}).json()
    client.patch(f"/api/sources/{src['id']}", json={"fetch_mode": "search"})
    assert await checker.check_source(src["id"]) == "skipped"  # the schedule never visits it
    _fake(monkeypatch, [_report(product_url="https://www.walmart.ca/en/ip/nintendo-switch-2/6000201")])
    assert client.post(f"/api/sources/{src['id']}/check").json()["outcome"] == "ok"  # Verify pressed
    obs = db_session.query(Observation).filter_by(source_link_id=src["id"]).one()
    assert (obs.method, obs.price_cents) == ("claude", 429999)
