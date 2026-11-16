"""Outbound URL guard: PriceWatch only fetches public web addresses.

Anyone signed in can ask PriceWatch to fetch a URL (preview, add a store link, import a list). Without a guard that
lets them reach the household's own network through the server: the router admin page, TrueNAS, other containers.
Every request (and every redirect, and every page the browser navigates to) is checked: http or https only, and the
host must not be, or resolve to, a private, loopback, link-local or otherwise non-public address. A name that does
not resolve is let through; the fetch then fails on its own.

PRICEWATCH_ALLOW_PRIVATE_URLS=true turns the guard off (the smoke test's local fixture server needs it).
"""

import asyncio
import ipaddress
import socket
import time
from urllib.parse import urlsplit

import httpx

from .config import get_settings

LOCAL_SUFFIXES = (".localhost", ".local", ".lan", ".internal", ".home", ".home.arpa", ".intranet", ".corp", ".localdomain")
_cache: dict[str, tuple[float, str | None]] = {}
CACHE_S = 300


class BlockedURL(httpx.RequestError):
    """Raised for a URL PriceWatch will not fetch (an httpx error, so existing handlers treat it as a failed fetch)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason

    def __str__(self) -> str:
        return self.reason


def _ip_reason(ip: str) -> str | None:
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    if not addr.is_global or addr.is_multicast:
        return f"{ip} is not a public address"
    return None


def static_reason(url: str) -> str | None:
    """Checks that need no DNS lookup."""
    if get_settings().allow_private_urls:
        return None
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return "only http and https addresses can be checked"
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        return "the address has no host"
    if parts.username or parts.password:
        return "addresses with a user name or password are not allowed"
    ip_reason = _ip_reason(host)
    if ip_reason:
        return ip_reason
    try:
        ipaddress.ip_address(host)
        return None  # a public IP literal
    except ValueError:
        pass
    if host == "localhost" or host.endswith(LOCAL_SUFFIXES) or "." not in host:
        return f"{host} is a local network name"
    return None


def host_of(url: str) -> str | None:
    """Host of any scheme://host/... URL (Apprise URLs included); None when there is none."""
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    return host.rstrip(".").lower() if host else None


def _resolve_reason(host: str) -> str | None:
    now = time.monotonic()
    hit = _cache.get(host)
    if hit and now - hit[0] < CACHE_S:
        return hit[1]
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, OSError):
        reason = None  # does not resolve: the fetch itself will fail
    else:
        reason = next((r for r in (_ip_reason(i[4][0]) for i in infos) if r), None)
        if reason:
            reason = f"{host} points to a private address ({reason.split(' ')[0]})"
    _cache[host] = (now, reason)
    return reason


def check(url: str) -> None:
    """Raise BlockedURL if PriceWatch must not fetch this URL (blocking DNS lookup)."""
    reason = static_reason(url)
    if reason is None and not get_settings().allow_private_urls:
        host = (urlsplit(url).hostname or "").rstrip(".").lower()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            reason = _resolve_reason(host)
    if reason:
        raise BlockedURL(reason)


async def acheck(url: str) -> None:
    reason = static_reason(url)
    if reason:
        raise BlockedURL(reason)
    if get_settings().allow_private_urls:
        return
    await asyncio.to_thread(check, url)


async def httpx_hook(request: httpx.Request) -> None:
    """httpx request hook: checks every request, including each redirect."""
    await acheck(str(request.url))
