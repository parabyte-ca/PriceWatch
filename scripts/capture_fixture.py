"""Save a product page as a test fixture, keeping only structured data.

Usage: python scripts/capture_fixture.py <url> <name>
Writes backend/tests/fixtures/<name>.html with JSON-LD, meta tags, microdata and the title,
and drops other scripts, inline styles, forms and comments so no session data is stored.
Uses the same honest User-Agent as the app. Review the file before committing it.
"""

import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup, Comment


def main(url: str, name: str) -> None:
    resp = httpx.get(url, follow_redirects=True, timeout=20,
                     headers={"User-Agent": "PriceWatchCA/fixture-capture (personal price tracker)"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup.find_all("script"):
        if "ld+json" not in (tag.get("type") or ""):
            tag.decompose()
    for tag in soup.find_all(["style", "iframe", "noscript", "form", "svg", "link"]):
        tag.decompose()
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    out = Path(__file__).resolve().parents[1] / "backend/tests/fixtures" / f"{name}.html"
    out.write_text(str(soup))
    print(f"saved {out} ({out.stat().st_size} bytes); review it for personal data before committing")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
