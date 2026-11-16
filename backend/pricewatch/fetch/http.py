"""Polite HTTP fetcher: per-domain spacing with jitter, robots.txt, conditional requests, caching."""

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from .. import __version__, netguard

log = logging.getLogger(__name__)

ROBOTS_TTL = 24 * 3600
CACHE_TTL = 300
MAX_BYTES = 6 * 1024 * 1024


def domain_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def default_user_agent(contact: str) -> str:
    return f"PriceWatchCA/{__version__} (personal price tracker; +{contact})"


def parse_retry_after(value: str | None) -> int | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return int(value)
    try:
        dt = parsedate_to_datetime(value)
        return max(0, int(dt.timestamp() - time.time()))
    except (TypeError, ValueError):
        return None


CHALLENGE_MARKERS = (
    "px-captcha", "_pxhd", "perimeterx", "captcha-delivery", "geo.captcha-delivery", "cf-chl-", "challenge-platform",
    "cf_chl_opt", "/_incapsula_resource", "access denied", "robot or human", "are you a robot",
    "pardon our interruption", "request unsuccessful. incapsula", "akamai bot", "bm-verify", "_abck",
    "verify you are human", "unusual traffic",
)


def looks_like_challenge(html: str | None) -> bool:
    """A 200 page that is really a bot challenge. Checked only when no price was parsed."""
    if not html:
        return True
    head = html[:200_000].lower()
    return any(marker in head for marker in CHALLENGE_MARKERS)


@dataclass
class FetchResult:
    url: str
    outcome: str  # ok | not_modified | http_error | blocked | robots | error
    status_code: int | None = None
    html: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    retry_after: int | None = None
    error: str | None = None
    elapsed_ms: int = 0
    from_cache: bool = False


class PoliteFetcher:
    def __init__(
        self,
        user_agent: str,
        min_interval: float = 5.0,
        jitter: float = 0.3,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.min_interval = min_interval
        self.jitter = jitter
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
            event_hooks={"request": [netguard.httpx_hook]},
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-CA,en;q=0.9,fr-CA;q=0.7",
            },
        )
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}
        self._robots: dict[str, tuple[float, RobotFileParser | None]] = {}
        self._cache: dict[str, tuple[float, FetchResult]] = {}

    async def close(self) -> None:
        await self._client.aclose()

    def _lock(self, domain: str) -> asyncio.Lock:
        if domain not in self._locks:
            self._locks[domain] = asyncio.Lock()
        return self._locks[domain]

    async def _space(self, domain: str, min_interval: float | None) -> None:
        interval = max(self.min_interval, min_interval or 0)
        last = self._last.get(domain)
        if last is not None:
            wait = last + interval * (1 + random.uniform(0, self.jitter)) - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
        self._last[domain] = time.monotonic()

    async def _robots_for(self, url: str) -> RobotFileParser | None:
        parts = urlsplit(url)
        key = f"{parts.scheme}://{parts.netloc}"
        cached = self._robots.get(key)
        if cached and time.monotonic() - cached[0] < ROBOTS_TTL:
            return cached[1]
        parser: RobotFileParser | None = None
        try:
            resp = await self._client.get(f"{key}/robots.txt")
            self._last[domain_of(url)] = time.monotonic()
            if resp.status_code == 200:
                parser = RobotFileParser()
                parser.parse(resp.text.splitlines())
            elif resp.status_code in (401, 403):
                parser = RobotFileParser()
                parser.disallow_all = True
        except httpx.HTTPError as exc:
            log.info("robots.txt unavailable", extra={"url": key, "error": str(exc)})
        self._robots[key] = (time.monotonic(), parser)
        return parser

    async def allowed(self, url: str) -> bool:
        parser = await self._robots_for(url)
        if parser is None:
            return True
        return parser.can_fetch(self.user_agent, url)

    async def fetch(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        respect_robots: bool = True,
        min_interval: float | None = None,
        use_cache: bool = False,
    ) -> FetchResult:
        if use_cache:
            hit = self._cache.get(url)
            if hit and time.monotonic() - hit[0] < CACHE_TTL:
                res = hit[1]
                return FetchResult(**{**vars(res), "from_cache": True})
        try:
            await netguard.acheck(url)
        except netguard.BlockedURL as exc:
            return FetchResult(url=url, outcome="error", error=f"Not fetched: {exc}")
        domain = domain_of(url)
        async with self._lock(domain):
            if respect_robots and not await self.allowed(url):
                return FetchResult(url=url, outcome="robots", error="Disallowed by robots.txt")
            await self._space(domain, min_interval)
            headers = {}
            if etag:
                headers["If-None-Match"] = etag
            if last_modified:
                headers["If-Modified-Since"] = last_modified
            start = time.monotonic()
            try:
                resp = await self._client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                return FetchResult(
                    url=url, outcome="error", error=f"{type(exc).__name__}: {exc}",
                    elapsed_ms=int((time.monotonic() - start) * 1000),
                )
            elapsed = int((time.monotonic() - start) * 1000)
        result = FetchResult(
            url=str(resp.url),
            outcome="ok",
            status_code=resp.status_code,
            etag=resp.headers.get("ETag"),
            last_modified=resp.headers.get("Last-Modified"),
            elapsed_ms=elapsed,
        )
        if resp.status_code == 304:
            result.outcome = "not_modified"
        elif resp.status_code in (403, 429, 503):
            result.outcome = "blocked"
            result.retry_after = parse_retry_after(resp.headers.get("Retry-After"))
            result.error = f"HTTP {resp.status_code}"
        elif resp.status_code >= 400:
            result.outcome = "http_error"
            result.error = f"HTTP {resp.status_code}"
        else:
            result.html = resp.content[:MAX_BYTES].decode(resp.encoding or "utf-8", errors="replace")
            self._cache[url] = (time.monotonic(), result)
        return result
