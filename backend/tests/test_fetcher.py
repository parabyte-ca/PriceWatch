import time

import httpx
import pytest

from pricewatch.fetch.http import PoliteFetcher, domain_of, parse_retry_after


def make(handler, **kw):
    return PoliteFetcher("PriceWatchCA/test", transport=httpx.MockTransport(handler), **kw)


def test_domain_of():
    assert domain_of("https://www.BestBuy.ca/en-ca/product/1") == "bestbuy.ca"


def test_retry_after():
    assert parse_retry_after("120") == 120
    assert parse_retry_after(None) is None


async def test_rate_limit_spacing_per_domain():
    hits = []

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        hits.append((req.url.host, time.monotonic()))
        return httpx.Response(200, text="<html></html>")

    f = make(handler, min_interval=0.3, jitter=0)
    await f.fetch("https://a.ca/1")
    await f.fetch("https://a.ca/2")
    await f.fetch("https://b.ca/1")
    a = [t for h, t in hits if h == "a.ca"]
    assert a[1] - a[0] >= 0.29
    await f.close()


async def test_robots_disallow():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        return httpx.Response(200, text="ok")

    f = make(handler, min_interval=0)
    assert (await f.fetch("https://a.ca/private/x")).outcome == "robots"
    assert (await f.fetch("https://a.ca/public")).outcome == "ok"
    assert (await f.fetch("https://a.ca/private/x", respect_robots=False)).outcome == "ok"
    await f.close()


@pytest.mark.parametrize("code,outcome", [(429, "blocked"), (403, "blocked"), (404, "http_error"), (304, "not_modified")])
async def test_status_outcomes(code, outcome):
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(code, headers={"Retry-After": "600"})

    r = await make(handler, min_interval=0).fetch("https://a.ca/p")
    assert r.outcome == outcome
    if code == 429:
        assert r.retry_after == 600


async def test_conditional_headers_and_cache():
    seen = []

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        seen.append(dict(req.headers))
        return httpx.Response(200, text="x", headers={"ETag": '"v1"'})

    f = make(handler, min_interval=0)
    r = await f.fetch("https://a.ca/p", etag='"v0"', last_modified="Mon, 01 Jan 2026 00:00:00 GMT")
    assert r.etag == '"v1"'
    assert seen[0]["if-none-match"] == '"v0"'
    assert "if-modified-since" in seen[0]
    r2 = await f.fetch("https://a.ca/p", use_cache=True)
    assert r2.from_cache and len(seen) == 1
    assert "PriceWatchCA" in seen[0]["user-agent"]
