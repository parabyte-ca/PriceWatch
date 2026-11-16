"""Playwright fallback through the browser sidecar (remote WebSocket)."""

import logging
import re
import time
from pathlib import Path

log = logging.getLogger(__name__)


PRICE_SIGNAL = ('script[type="application/ld+json"], [itemprop="price"], meta[property="product:price:amount"], '
                '[data-testid*="price" i], [class*="price" i]')


async def settle(page, url: str, timeout: float) -> None:
    """Load the page and wait, within the time limit, until a price is likely on it.

    Script-heavy store pages (Sport Chek, Canadian Tire) can keep loading for a long time; waiting for the whole
    document can time out even though the product details are already there. So: wait for the first response, then
    for a price element (or the deadline), then briefly for the network, and return whatever has rendered instead of
    failing.
    """
    from .. import netguard

    await netguard.acheck(url)

    async def guard(route):
        # every request the page makes: no private hosts (an image or script pointing at the home network), and a
        # full DNS check for each navigation (redirects included)
        req_url = route.request.url
        try:
            if netguard.static_reason(req_url) and not req_url.startswith(("data:", "blob:")):
                raise netguard.BlockedURL(netguard.static_reason(req_url) or "")
            if route.request.is_navigation_request():
                await netguard.acheck(req_url)
        except netguard.BlockedURL:
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    await page.route("**/*", guard)
    deadline = time.monotonic() + timeout
    await page.goto(url, wait_until="commit", timeout=timeout * 1000)

    def left(cap: float) -> float:
        return max(0.5, min(cap, deadline - time.monotonic())) * 1000

    try:
        await page.wait_for_selector(PRICE_SIGNAL, state="attached", timeout=left(timeout))
        found = True
    except Exception:  # noqa: BLE001 - no price element by the deadline; the content is still checked afterwards
        found = False
    waits = [("networkidle", 2.0)] if found else [("domcontentloaded", 3.0), ("networkidle", 3.0)]
    for state, cap in waits:
        if time.monotonic() >= deadline:
            break
        try:
            await page.wait_for_load_state(state, timeout=left(cap))
        except Exception:  # noqa: BLE001 - best effort
            pass


async def render(url: str, ws_endpoint: str, timeout: float, user_agent: str,
                 screenshot_dir: Path | None = None) -> str:
    """Render a page in the sidecar and return the HTML. Screenshot on failure."""
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.connect(ws_endpoint, timeout=timeout * 1000)
        context = await browser.new_context(user_agent=user_agent, locale="en-CA")
        page = await context.new_page()
        try:
            await settle(page, url, timeout)
            return await page.content()
        except Exception:
            if screenshot_dir:
                try:
                    screenshot_dir.mkdir(parents=True, exist_ok=True)
                    safe = re.sub(r"[^A-Za-z0-9]+", "_", url)[:80]
                    path = screenshot_dir / f"{int(time.time())}_{safe}.png"
                    await page.screenshot(path=str(path), full_page=False)
                    log.warning("browser render failed, screenshot saved", extra={"path": str(path)})
                except Exception:  # noqa: BLE001
                    pass
            raise
        finally:
            await context.close()
            await browser.close()


async def screenshot(url: str, ws_endpoint: str, timeout: float, user_agent: str) -> bytes:
    """Full-page PNG of the page as a person would see it (for price-protection proof)."""
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.connect(ws_endpoint, timeout=timeout * 1000)
        context = await browser.new_context(user_agent=user_agent, locale="en-CA", viewport={"width": 1280, "height": 1600})
        page = await context.new_page()
        try:
            await settle(page, url, timeout)
            return await page.screenshot(full_page=True, timeout=timeout * 1000)
        finally:
            await context.close()
            await browser.close()
