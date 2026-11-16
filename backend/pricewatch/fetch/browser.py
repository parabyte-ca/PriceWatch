"""Playwright fallback through the browser sidecar (remote WebSocket)."""

import logging
import re
import time
from pathlib import Path

log = logging.getLogger(__name__)


async def render(url: str, ws_endpoint: str, timeout: float, user_agent: str,
                 screenshot_dir: Path | None = None) -> str:
    """Render a page in the sidecar and return the HTML. Screenshot on failure."""
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.connect(ws_endpoint, timeout=timeout * 1000)
        context = await browser.new_context(user_agent=user_agent, locale="en-CA")
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            try:
                await page.wait_for_load_state("networkidle", timeout=min(10.0, timeout) * 1000)
            except Exception:  # noqa: BLE001 - networkidle is best effort
                pass
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
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            try:
                await page.wait_for_load_state("networkidle", timeout=min(10.0, timeout) * 1000)
            except Exception:  # noqa: BLE001
                pass
            return await page.screenshot(full_page=True, timeout=timeout * 1000)
        finally:
            await context.close()
            await browser.close()
