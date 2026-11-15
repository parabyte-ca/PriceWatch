"""Process-wide singletons: the polite fetcher and in-flight bookkeeping."""

import asyncio

from ..config import get_settings
from ..fetch.http import PoliteFetcher, default_user_agent

_fetcher: PoliteFetcher | None = None
in_flight: set[int] = set()
_semaphore: asyncio.Semaphore | None = None
_browser_locks: dict[str, asyncio.Lock] = {}


def browser_lock(domain: str) -> asyncio.Lock:
    """At most one browser page per domain at a time."""
    if domain not in _browser_locks:
        _browser_locks[domain] = asyncio.Lock()
    return _browser_locks[domain]


def get_fetcher() -> PoliteFetcher:
    global _fetcher
    if _fetcher is None:
        s = get_settings()
        _fetcher = PoliteFetcher(
            user_agent=s.user_agent or default_user_agent(s.contact),
            min_interval=s.min_domain_interval,
            jitter=s.domain_jitter,
            timeout=s.request_timeout,
        )
    return _fetcher


def set_fetcher(fetcher: PoliteFetcher | None) -> None:
    global _fetcher
    _fetcher = fetcher


def semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(get_settings().max_concurrency)
    return _semaphore


async def close() -> None:
    global _fetcher, _semaphore
    if _fetcher is not None:
        await _fetcher.close()
    _fetcher = None
    _semaphore = None
    _browser_locks.clear()
