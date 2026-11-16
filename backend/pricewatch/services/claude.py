"""The household's Claude (Anthropic) set-up, entered in Household admin like NetWatch's Ask NetWatch.

The API key is stored encrypted with a key derived from ``data/.secret_key`` (never returned by the API, never logged).
``ANTHROPIC_API_KEY`` in .env still works as a fallback. Every Claude feature (Ask PriceWatch, the match check,
the weekly summary, reading order emails) uses this one key.
"""

import base64
import hashlib
import logging
import time

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import session_scope
from ..models import SettingKV

log = logging.getLogger(__name__)
CONFIG_KEY = "assistant_config"
API_KEY_KEY = "assistant_api_key"
MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")
EFFORTS = ("low", "medium", "high")
PRICE_MODEL = "claude-haiku-5-5"  # price checks are simple reads; the cheapest model keeps them affordable
DEFAULT_CAP_USD = 15.0
SPEND_KEY = "claude_spend"
# USD per million tokens (input, output) and per web search; used only for the household's spend meter
RATES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}
SEARCH_USD = 0.01
_cache: tuple[float, str | None] | None = None
CACHE_S = 30


def _box() -> Fernet:
    from ..auth import load_secret_key

    secret = load_secret_key(get_settings()).encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"pricewatch-claude:" + secret).digest()))


def _get(db: Session, key: str):
    row = db.get(SettingKV, key)
    return row.value if row is not None else None


def _set(db: Session, key: str, value) -> None:
    row = db.get(SettingKV, key)
    if row is None:
        db.add(SettingKV(key=key, value=value))
    else:
        row.value = value


def config(db: Session) -> dict:
    c = _get(db, CONFIG_KEY) or {}
    model = c.get("model") if c.get("model") in MODELS else MODELS[0]
    effort = c.get("effort") if c.get("effort") in EFFORTS else "medium"
    cap = c.get("monthly_cap_usd", DEFAULT_CAP_USD)
    cap = float(cap) if isinstance(cap, (int, float)) and cap >= 0 else DEFAULT_CAP_USD
    return {"enabled": bool(c.get("enabled", True)), "model": model, "effort": effort,
            "price_fallback": bool(c.get("price_fallback", True)), "monthly_cap_usd": cap}


def stored_key(db: Session) -> str | None:
    token = _get(db, API_KEY_KEY)
    if not token:
        return None
    try:
        return _box().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        log.warning("saved Anthropic key could not be decrypted (was data/.secret_key replaced?)")
        return None


def api_key() -> str | None:
    """The key to use: the one saved in Household admin, else ANTHROPIC_API_KEY. Safe to call from any thread."""
    global _cache
    now = time.monotonic()
    if _cache and now - _cache[0] < CACHE_S:
        return _cache[1]
    db = session_scope()
    try:
        key = stored_key(db) if config(db)["enabled"] else None
    finally:
        db.close()
    key = key or get_settings().anthropic_api_key
    _cache = (now, key)
    return key


def forget_cache() -> None:
    global _cache
    _cache = None


def status(db: Session) -> dict:
    return {**config(db), "spend": spend(db), "key_saved": _get(db, API_KEY_KEY) is not None,
            "env_key": bool(get_settings().anthropic_api_key), "models": list(MODELS), "efforts": list(EFFORTS)}


def save(db: Session, enabled: bool, model: str, effort: str, key: str | None, *, price_fallback: bool = True,
         monthly_cap_usd: float = DEFAULT_CAP_USD) -> None:
    _set(db, CONFIG_KEY, {"enabled": enabled, "model": model, "effort": effort, "price_fallback": price_fallback,
                          "monthly_cap_usd": max(0.0, float(monthly_cap_usd))})
    if key:
        _set(db, API_KEY_KEY, _box().encrypt(key.encode()).decode())
    db.commit()
    forget_cache()


def forget_key(db: Session) -> None:
    _set(db, API_KEY_KEY, None)
    db.commit()
    forget_cache()


def _month() -> str:
    from ..timeutil import utcnow

    return utcnow().strftime("%Y-%m")


def spend(db: Session) -> dict:
    """This month's estimated Claude spend in USD (price checks and store searches)."""
    row = _get(db, SPEND_KEY) or {}
    if row.get("month") != _month():
        row = {}
    return {"month": _month(), "usd": round(float(row.get("usd", 0.0)), 4), "checks": int(row.get("checks", 0)),
            "searches": int(row.get("searches", 0))}


def cost_usd(model: str, usage) -> float:
    """Estimate one response's cost from its usage block (tokens plus web searches)."""
    if usage is None:
        return 0.0
    rin, rout = RATES.get(model, RATES[MODELS[0]])
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    tokens_in = (getattr(usage, "input_tokens", 0) or 0) + cache_write * 1.25 + cache_read * 0.1
    tokens_out = getattr(usage, "output_tokens", 0) or 0
    stu = getattr(usage, "server_tool_use", None)
    searches = (getattr(stu, "web_search_requests", 0) or 0) if stu is not None else 0
    return tokens_in / 1e6 * rin + tokens_out / 1e6 * rout + searches * SEARCH_USD


def record_spend(usd: float, *, searches: int = 0, check: bool = False) -> None:
    db = session_scope()
    try:
        cur = spend(db)
        _set(db, SPEND_KEY, {"month": cur["month"], "usd": cur["usd"] + usd, "checks": cur["checks"] + int(check),
                             "searches": cur["searches"] + searches})
        db.commit()
    finally:
        db.close()


def budget_left() -> float | None:
    """USD left under the monthly cap (None when no cap: 0 means unlimited)."""
    db = session_scope()
    try:
        cap = config(db)["monthly_cap_usd"]
        return None if cap == 0 else max(0.0, cap - spend(db)["usd"])
    finally:
        db.close()


def price_fallback_on() -> bool:
    db = session_scope()
    try:
        return bool(config(db)["price_fallback"])
    finally:
        db.close()


async def test(model: str, key: str | None) -> dict:
    """Check a key against the chosen model without spending tokens (models endpoint)."""
    import anthropic

    key = key or api_key()
    if not key:
        return {"ok": False, "error": "no API key saved"}
    client = anthropic.AsyncAnthropic(api_key=key, timeout=30.0, max_retries=1)
    try:
        m = await client.models.retrieve(model)
    except anthropic.AuthenticationError:
        return {"ok": False, "error": "the API key was rejected"}
    except anthropic.PermissionDeniedError:
        return {"ok": False, "error": "the API key may not use this model"}
    except anthropic.NotFoundError:
        return {"ok": False, "error": f"model {model} is not available to this key"}
    except anthropic.APIConnectionError:
        return {"ok": False, "error": "could not reach api.anthropic.com"}
    except anthropic.APIStatusError as exc:
        return {"ok": False, "error": f"Anthropic API error {exc.status_code}"}
    finally:
        await client.close()
    return {"ok": True, "model": m.id, "display_name": getattr(m, "display_name", m.id)}
