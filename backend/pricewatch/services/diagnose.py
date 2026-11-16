"""Test a product URL step by step (admin): robots, HTTP status, bot challenge, structured data, parsed price.

Optionally saves a cleaned copy of the page as a test fixture (scripts and tracking removed) so parsing problems
on real retailer pages can be fixed and covered by tests.
"""

import re
import time

from bs4 import BeautifulSoup, Comment

from ..adapters.base import RetailerConfig
from ..adapters.generic import _load_jsonld_blocks
from ..adapters.registry import get_adapter
from ..config import get_settings
from ..fetch import browser
from ..fetch.http import domain_of, looks_like_challenge
from ..timeutil import utcnow
from . import runtime


def clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all("script"):
        if "ld+json" not in (tag.get("type") or ""):
            tag.decompose()
    for tag in soup.find_all(["style", "iframe", "noscript", "form", "svg", "link"]):
        tag.decompose()
    for c in soup.find_all(string=lambda x: isinstance(x, Comment)):
        c.extract()
    return str(soup)


def _report(html: str | None, url: str, retailer) -> dict:
    if not html:
        return {"bytes": 0}
    soup = BeautifulSoup(html, "lxml")
    blocks = _load_jsonld_blocks(soup)
    types = []
    for b in blocks:
        for node in (b if isinstance(b, list) else [b]):
            if isinstance(node, dict):
                types.append(str(node.get("@type")))
                types += [str(g.get("@type")) for g in node.get("@graph", []) if isinstance(g, dict)]
    cfg = RetailerConfig(domain=retailer.domain if retailer else domain_of(url),
                         selectors=retailer.selectors if retailer else None)
    parsed = get_adapter(retailer.adapter if retailer else None).parse(html, url, cfg)
    return {
        "bytes": len(html),
        "title": (soup.title.get_text(strip=True)[:200] if soup.title else None),
        "challenge": looks_like_challenge(html) and not (parsed and parsed.has_price),
        "jsonld_blocks": len(blocks),
        "jsonld_types": sorted(set(types))[:20],
        "has_microdata_price": soup.find(attrs={"itemprop": "price"}) is not None,
        "has_og_price": soup.find("meta", attrs={"property": re.compile("price:amount")}) is not None,
        "parsed": parsed.to_dict() if parsed else None,
    }


async def diagnose(url: str, retailer, use_browser: bool, save_fixture: bool) -> dict:
    s = get_settings()
    fetcher = runtime.get_fetcher()
    out: dict = {"url": url, "domain": domain_of(url), "retailer": retailer.name if retailer else None,
                 "fetch_mode": retailer.fetch_mode if retailer else "auto", "user_agent": fetcher.user_agent}
    respect = retailer.respect_robots if retailer else True
    out["robots_allowed"] = await fetcher.allowed(url)
    t0 = time.monotonic()
    res = await fetcher.fetch(url, respect_robots=respect, min_interval=retailer.min_interval_seconds if retailer else None)
    out["http"] = {"outcome": res.outcome, "status": res.status_code, "error": res.error, "final_url": res.url,
                   "ms": int((time.monotonic() - t0) * 1000), **_report(res.html, url, retailer)}
    html_for_fixture = res.html
    if use_browser and s.browser_enabled:
        t0 = time.monotonic()
        try:
            async with runtime.browser_lock(out["domain"]):
                html = await browser.render(url, s.browser_ws, s.browser_timeout, fetcher.user_agent,
                                            s.data_dir / "screenshots")
            out["browser"] = {"outcome": "ok", "ms": int((time.monotonic() - t0) * 1000), **_report(html, url, retailer)}
            if not (out["http"].get("parsed") or {}).get("price_cents"):
                html_for_fixture = html
        except Exception as exc:  # noqa: BLE001
            out["browser"] = {"outcome": "error", "error": f"{type(exc).__name__}: {exc}"}
    elif use_browser:
        out["browser"] = {"outcome": "disabled", "error": "PRICEWATCH_BROWSER_ENABLED is false"}
    verdict = "ok"
    best = out.get("browser", {}).get("parsed") or out["http"].get("parsed")
    if not out["robots_allowed"]:
        verdict = "robots.txt disallows this page"
    elif out["http"]["outcome"] == "blocked" or out["http"].get("challenge"):
        verdict = "blocked or bot challenge: try browser mode, or log prices by hand"
    elif not (best and best.get("price_cents")):
        verdict = "no price found: save a fixture and send it so a parser can be added"
    out["verdict"] = verdict
    if save_fixture and html_for_fixture:
        folder = s.data_dir / "fixtures"
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{out['domain']}-{utcnow():%Y%m%d-%H%M%S}.html"
        (folder / name).write_text(clean_html(html_for_fixture))
        out["fixture"] = f"data/fixtures/{name}"
    out["note"] = "Fixtures have scripts, styles and comments removed; check them for personal data before sharing."
    return out
