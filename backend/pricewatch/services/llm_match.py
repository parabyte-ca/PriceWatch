"""Optional second opinion from Claude Haiku on uncertain product matches (fuzzy score 80 to 94).

Off unless ANTHROPIC_API_KEY is set and the household setting llm_match_enabled is on. Only the item's name,
brand and model and the listing's title, merchant and condition go to Anthropic. Answers are cached by content, so
each pair is asked once. Claude can turn a suggestion down (a lookalike) but never confirms a listing by itself.
"""

import asyncio
import hashlib
import logging

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import LlmMatchCache
from . import claude, settings_store
from .matching import Candidate, ItemSpec

log = logging.getLogger(__name__)
LOW, HIGH = 80.0, 95.0
SYSTEM = (
    "You compare a wishlist item with one store listing and decide whether the listing is the same product. "
    "Same product means the same model and generation, and the same storage, size and colour when the item names "
    "them. A different generation (for example XM5 versus XM6), an accessory, a case, a replacement part, a bundle "
    "with other products, or a refurbished, open-box or used unit is not the same product. If the listing does not "
    "give enough detail to tell, answer false with low confidence. Keep the reason under 20 words."
)


class Verdict(BaseModel):
    same_product: bool
    confidence: float = Field(description="0 to 1")
    reason: str


def enabled(db: Session) -> bool:
    return bool(claude.api_key()) and bool(settings_store.get(db, "llm_match_enabled"))


def similarity(confidence: float) -> float:
    """Title similarity (0 to 100) behind a fuzzy match's confidence, which the matcher scales to 0 to 0.9."""
    return confidence / 0.9 * 100


def in_band(confidence: float) -> bool:
    """True for fuzzy matches whose title similarity is 80 to 94: likely, but worth a second opinion."""
    return LOW <= round(similarity(confidence), 1) < HIGH


def _describe(spec: ItemSpec, cand: Candidate) -> tuple[str, str]:
    item = "; ".join(f"{k}: {v}" for k, v in (("name", spec.name), ("brand", spec.brand), ("model", spec.model))
                     if v)
    listing = "; ".join(f"{k}: {v}" for k, v in (("title", cand.title), ("merchant", cand.merchant),
                                                  ("condition", cand.condition)) if v)
    return item, listing


def _key(model: str, item: str, listing: str) -> str:
    return hashlib.sha256(f"{model}\n{item}\n{listing}".encode()).hexdigest()


def _ask(model: str, item: str, listing: str) -> Verdict | None:
    import anthropic

    client = anthropic.Anthropic(api_key=claude.api_key(), timeout=30.0, max_retries=2)
    try:
        response = client.messages.parse(
            model=model,
            max_tokens=2000,
            system=SYSTEM,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": f"Wishlist item: {item}\nStore listing: {listing}"}],
            output_format=Verdict,
        )
    except anthropic.RateLimitError:
        log.warning("llm match rate limited")
        return None
    except anthropic.APIStatusError as exc:
        log.warning("llm match API error", extra={"status": exc.status_code, "request_id": exc.request_id})
        return None
    except anthropic.APIConnectionError:
        log.warning("llm match connection error")
        return None
    if response.stop_reason == "refusal" or response.parsed_output is None:
        log.info("llm match gave no answer", extra={"stop_reason": response.stop_reason})
        return None
    return response.parsed_output


async def check(db: Session, spec: ItemSpec, cand: Candidate, asker=None) -> dict | None:
    """Return {same_product, confidence, reason, model, cached} or None when unavailable."""
    model = get_settings().llm_match_model
    item, listing = _describe(spec, cand)
    key = _key(model, item, listing)
    row = db.get(LlmMatchCache, key)
    if row is not None:
        return {"same_product": row.same_product, "confidence": row.confidence, "reason": row.reason,
                "model": row.model, "cached": True}
    verdict = await asyncio.to_thread(asker or _ask, model, item, listing)  # only the HTTP call leaves the loop
    if verdict is None:
        return None
    db.add(LlmMatchCache(key=key, same_product=verdict.same_product, confidence=verdict.confidence,
                         reason=verdict.reason[:300], model=model))
    db.flush()
    return {"same_product": verdict.same_product, "confidence": verdict.confidence, "reason": verdict.reason[:300],
            "model": model, "cached": False}


def cached(db: Session, spec: ItemSpec, cand: Candidate) -> dict | None:
    """A cached answer only (no API call), for synchronous code paths."""
    model = get_settings().llm_match_model
    item, listing = _describe(spec, cand)
    row = db.get(LlmMatchCache, _key(model, item, listing))
    if row is None:
        return None
    return {"same_product": row.same_product, "confidence": row.confidence, "reason": row.reason, "model": row.model,
            "cached": True}


def vetoed(db: Session, spec: ItemSpec, cand: Candidate, result) -> bool:
    """True when a fuzzy, uncertain match has a cached "not the same product" answer."""
    if result.method != "fuzzy" or not in_band(result.confidence):
        return False
    ans = cached(db, spec, cand)
    return bool(ans and not ans["same_product"])


async def prefetch(db: Session, pairs, limit: int = 20) -> int:
    """Ask about uncertain (spec, candidate, result) pairs ahead of a synchronous ingest. Returns how many were asked."""
    if not enabled(db):
        return 0
    asked = 0
    for spec, cand, result in pairs:
        if asked >= limit:
            break
        if result.accepted and result.method == "fuzzy" and in_band(result.confidence) and cached(db, spec, cand) is None:
            if await check(db, spec, cand) is not None:
                asked += 1
    db.commit()
    return asked
