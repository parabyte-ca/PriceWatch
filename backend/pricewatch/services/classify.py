"""Sort search-result listings with Claude: the plain product, or a bundle, accessory, refurbished unit, other model or
marketplace seller.

Google Shopping mixes "Switch 2 + Mario Kart" bundles, cases and marketplace sellers in with the product itself, which
made the price comparison misleading. One Claude Haiku call per search reads all the titles at once (only titles,
stores and prices are sent); answers are cached per title, so a daily refresh mostly costs nothing. Without a Claude
key, or over the monthly cap, listings are kept as the matcher left them.
"""

import hashlib
import logging

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..models import LlmMatchCache
from . import claude
from .matching import ItemSpec

log = logging.getLogger(__name__)
LABELS = ("same", "bundle", "accessory", "refurbished", "different", "marketplace")
MAX_LISTINGS = 40
SYSTEM = (
    "You sort store listings for one product a shopper wants. For each listing answer one label: "
    "same (the product itself, new, sold on its own, any colour the shopper did not rule out), "
    "bundle (the product plus other products or games), accessory (a part, case, cable or add-on for it), "
    "refurbished (refurbished, renewed, open box or used), different (another model, generation, size or capacity), "
    "marketplace (the product, but plainly sold by a third-party seller rather than the store). "
    "Judge only from the text given. Return every listing by its number."
)


class Label(BaseModel):
    n: int
    label: str = Field(description="|".join(LABELS))


class Labels(BaseModel):
    listings: list[Label]


def _key(spec: ItemSpec, title: str, merchant: str) -> str:
    raw = f"classify\n{spec.name}\n{spec.brand or ''}\n{spec.model or ''}\n{title}\n{merchant}"
    return hashlib.sha256(raw.encode()).hexdigest()


def available() -> bool:
    if not claude.api_key():
        return False
    left = claude.budget_left()
    return left is None or left > 0.02


async def classify(db: Session, spec: ItemSpec, offers: list[dict], *, client_factory=None) -> dict[str, str]:
    """Return {url: label} for the offers (cached labels first, one Claude call for the rest)."""
    out: dict[str, str] = {}
    todo: list[tuple[str, dict]] = []
    for o in offers[:MAX_LISTINGS]:
        k = _key(spec, o["title"] or "", o["merchant"] or "")
        hit = db.get(LlmMatchCache, k)
        if hit is not None and hit.reason in LABELS:
            out[o["url"]] = hit.reason
        else:
            todo.append((k, o))
    if not todo or not available():
        return out
    import anthropic

    lines = "\n".join(f"{n}. {o['title']} | store: {o['merchant']} | {o['price_cents'] / 100:.2f}"
                      for n, (_, o) in enumerate(todo, 1))
    want = "; ".join(f"{k}: {v}" for k, v in (("name", spec.name), ("brand", spec.brand), ("model", spec.model)) if v)
    api = (client_factory or (lambda: anthropic.AsyncAnthropic(api_key=claude.api_key(), timeout=60.0,
                                                               max_retries=1)))()
    usd = 0.0
    try:
        resp = await api.messages.parse(
            model=claude.PRICE_MODEL, max_tokens=4000, system=SYSTEM, output_config={"effort": "low"},
            messages=[{"role": "user", "content": f"Shopper wants: {want}\nListings:\n{lines}"}],
            output_format=Labels)
        usd = claude.cost_usd(claude.PRICE_MODEL, getattr(resp, "usage", None))
        parsed: Labels | None = resp.parsed_output
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
        log.warning("listing classify failed: %s", type(exc).__name__)
        return out
    finally:
        if usd:
            claude.record_spend(usd)
        await api.close()
    for row in (parsed.listings if parsed else []):
        if 1 <= row.n <= len(todo) and row.label in LABELS:
            k, o = todo[row.n - 1]
            out[o["url"]] = row.label
            if db.get(LlmMatchCache, k) is None:
                db.add(LlmMatchCache(key=k, same_product=row.label == "same", confidence=None, reason=row.label,
                                     model=claude.PRICE_MODEL))
    db.commit()
    return out
