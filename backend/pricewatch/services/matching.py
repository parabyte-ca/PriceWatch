"""Product matching: GTIN, then MPN within brand, then fuzzy title, plus exclusion rules."""

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from rapidfuzz import fuzz

# ---------- identifiers ----------


def normalize_gtin(value: str | None) -> str | None:
    """Digits only, zero-padded to GTIN-14; None when the check digit is wrong."""
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) not in (8, 12, 13, 14):
        return None
    digits = digits.zfill(14)
    body, check = digits[:-1], int(digits[-1])
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(body))
    return digits if (10 - total % 10) % 10 == check else None


def normalize_mpn(value: str | None) -> str | None:
    if not value:
        return None
    norm = re.sub(r"[^A-Z0-9]", "", str(value).upper())
    return norm or None


def normalize_brand(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"[^a-z0-9]", "", str(value).lower()) or None


# ---------- URLs ----------

TRACKING_PARAMS = re.compile(
    r"^(utm_.*|gclid|gclsrc|dclid|fbclid|msclkid|srsltid|ref|ref_|tag|cmp|icid|irclickid|clickid|"
    r"cjevent|cjdata|affid|aff_id|mc_.*|_ga|epik|yclid|spm|sca_ref)$",
    re.I,
)


def normalize_url(url: str) -> str:
    """Lowercase host, drop fragments and tracking parameters, unwrap Google redirects."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if host.endswith("google.com") or host.endswith("google.ca"):
        qs = dict(parse_qsl(parts.query))
        for key in ("url", "q", "adurl"):
            if qs.get(key, "").startswith("http"):
                return normalize_url(qs[key])
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not TRACKING_PARAMS.match(k)]
    netloc = host + (f":{parts.port}" if parts.port else "")
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower() or "https", netloc, path, urlencode(query), ""))


# ---------- title attributes ----------

REFURB_RE = re.compile(r"\b(refurb(ished)?|renewed|reconditioned|remanufactured|recertified|seller refurbished)\b", re.I)
OPEN_BOX_RE = re.compile(r"\bopen[\s-]?box\b", re.I)
USED_RE = re.compile(r"\b(used|pre[\s-]?owned|second[\s-]?hand|like new)\b", re.I)
KNOCKOFF_RE = re.compile(r"\b(compatible (with|for)|\w+[- ]compatible|replacement for|for use with|"
                         r"knock-?off|dupe|alternative to)\b", re.I)
BUNDLE_RE = re.compile(
    r"\b(bundle|combo|kit with|with (?:case|charger|mount|stand|bag|controller|game)|\+\s*\w+|"
    r"2[\s-]?pack|3[\s-]?pack|4[\s-]?pack|set of \d|pack of \d)\b",
    re.I,
)
STORAGE_RE = re.compile(r"\b(\d{2,4})\s?(gb|tb)\b", re.I)
SCREEN_RE = re.compile(r"\b(\d{2,3}(?:\.\d)?)\s?(?:\"|''|in\b|inch(?:es)?\b|po\b|”)", re.I)
COLOURS = (
    "black", "white", "silver", "grey", "gray", "graphite", "blue", "navy", "red", "green", "pink", "purple",
    "gold", "rose gold", "yellow", "orange", "beige", "brown", "midnight", "starlight", "titanium", "charcoal",
    "noir", "blanc", "argent", "bleu", "rouge", "vert", "rose",
)
COLOUR_RE = re.compile(r"\b(" + "|".join(sorted(COLOURS, key=len, reverse=True)) + r")\b", re.I)
MARKETPLACE_SOURCES = re.compile(r"(ebay|kijiji|facebook|marketplace|- seller|via |aliexpress|temu|wish\.com)", re.I)
MARKETPLACE_DOMAINS = ("ebay.ca", "ebay.com", "kijiji.ca", "facebook.com", "aliexpress.com", "temu.com", "wish.com")


def _storage(title: str) -> set[str]:
    out = set()
    for num, unit in STORAGE_RE.findall(title):
        gb = int(num) * (1024 if unit.lower() == "tb" else 1)
        if gb >= 16:  # ignore RAM-like small values only when they look like storage
            out.add(str(gb))
    return out


def _colours(title: str) -> set[str]:
    norm = {"gray": "grey"}
    return {norm.get(c.lower(), c.lower()) for c in COLOUR_RE.findall(title)}


def _screens(title: str) -> set[str]:
    return {s.rstrip("0").rstrip(".") for s in SCREEN_RE.findall(title)}


@dataclass
class Candidate:
    title: str
    url: str
    price_cents: int | None = None
    merchant: str | None = None
    gtin: str | None = None
    mpn: str | None = None
    brand: str | None = None
    condition: str | None = None
    shipping_cents: int | None = None
    provider: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class ItemSpec:
    name: str
    brand: str | None = None
    model: str | None = None
    gtin: str | None = None
    exclude_refurbished: bool = True
    exclude_open_box: bool = True
    exclude_used: bool = True
    exclude_marketplace: bool = True
    exclude_bundles: bool = True
    exclude_variants: bool = True

    @classmethod
    def from_item(cls, item) -> "ItemSpec":
        return cls(**{k: getattr(item, k) for k in cls.__dataclass_fields__})


@dataclass
class MatchResult:
    confidence: float
    method: str  # gtin | mpn | fuzzy | none
    accepted: bool
    reasons: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)


def exclusions_for(spec: ItemSpec, cand: Candidate) -> list[str]:
    text = cand.title or ""
    cond = (cand.condition or "").lower()
    out = []
    if spec.exclude_refurbished and (REFURB_RE.search(text) or cond == "refurbished"):
        out.append("refurbished")
    if spec.exclude_open_box and (OPEN_BOX_RE.search(text) or "open" in cond):
        out.append("open box")
    if spec.exclude_used and (USED_RE.search(text) or cond == "used"):
        out.append("used")
    if spec.exclude_marketplace:
        domain = (urlsplit(cand.url).hostname or "").lower().removeprefix("www.")
        if MARKETPLACE_SOURCES.search(cand.merchant or "") or domain in MARKETPLACE_DOMAINS:
            out.append("marketplace seller")
    if spec.exclude_bundles and BUNDLE_RE.search(text) and not BUNDLE_RE.search(spec.name):
        out.append("bundle")
    if KNOCKOFF_RE.search(text) and not KNOCKOFF_RE.search(spec.name):
        out.append("not the brand's own product (compatible / replacement)")
    if spec.exclude_variants:
        for label, fn in (("storage", _storage), ("colour", _colours), ("size", _screens)):
            want, got = fn(spec.name), fn(text)
            if want and got and not (want & got):
                out.append(f"different {label} ({', '.join(sorted(got))} vs {', '.join(sorted(want))})")
    return out


UNIT_TOKEN = re.compile(r"^\d+(?:\.\d+)?(GB|TB|MB|INCH|INCHES|IN|PO|MM|CM|HZ|W|MAH|K|P|MP|V|L|QT|PC|PCS|PACK|X)$")


def model_tokens(text: str) -> set[str]:
    """Model-like tokens (letters and digits mixed, 4+ characters), normalised: 'WH-1000XM6' -> 'WH1000XM6'."""
    out = set()
    for raw in re.split(r"[\s,()\[\]]+", text or ""):
        tok = normalize_mpn(raw)
        if not tok or len(tok) < 4 or UNIT_TOKEN.match(tok):
            continue
        if re.search(r"[A-Z]", tok) and re.search(r"\d", tok):
            out.add(tok)
    return out


def _models_conflict(item_tokens: set[str], cand_tokens: set[str]) -> bool:
    if not item_tokens or not cand_tokens:
        return False
    for a in item_tokens:
        for b in cand_tokens:
            if a == b or (min(len(a), len(b)) >= 5 and (a.startswith(b) or b.startswith(a))):
                return False
    return True


def _clean_title(text: str) -> str:
    text = re.sub(r"[^\w\s.\-\"]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def match(spec: ItemSpec, cand: Candidate, threshold: float = 85.0) -> MatchResult:
    """Score a candidate listing against a wishlist item."""
    exclusions = exclusions_for(spec, cand)
    item_gtin, cand_gtin = normalize_gtin(spec.gtin), normalize_gtin(cand.gtin)
    if item_gtin and cand_gtin:
        if item_gtin == cand_gtin:
            return MatchResult(1.0, "gtin", not exclusions, ["GTIN matches"], exclusions)
        return MatchResult(0.0, "gtin", False, ["GTIN differs"], exclusions)

    item_mpn = normalize_mpn(spec.model)
    item_brand = normalize_brand(spec.brand)
    cand_brand = normalize_brand(cand.brand)
    brand_ok = not (item_brand and cand_brand) or item_brand == cand_brand or item_brand in cand_brand
    if item_mpn and len(item_mpn) >= 4:
        cand_mpn = normalize_mpn(cand.mpn)
        title_tokens = normalize_mpn(cand.title) or ""
        if brand_ok and (cand_mpn == item_mpn or (not cand_mpn and item_mpn in title_tokens)):
            return MatchResult(0.95, "mpn", not exclusions, ["model number matches"], exclusions)
        if cand_mpn and cand_mpn != item_mpn and brand_ok:
            return MatchResult(0.0, "mpn", False, [f"model number differs ({cand.mpn})"], exclusions)

    if not brand_ok:
        return MatchResult(0.0, "fuzzy", False, ["brand differs"], exclusions)
    item_models = model_tokens(spec.name) | model_tokens(spec.model or "")
    cand_models = model_tokens(cand.title) | model_tokens(cand.mpn or "")
    if _models_conflict(item_models, cand_models):
        return MatchResult(0.1, "fuzzy", False, [f"different model ({', '.join(sorted(cand_models))})"], exclusions)
    shared = {a for a in item_models for b in cand_models
              if a == b or (min(len(a), len(b)) >= 5 and (a.startswith(b) or b.startswith(a)))}
    accessory = bool(re.search(r"\b(for|compatible with|pour|case|cover|replacement)\b", _clean_title(cand.title))
                     and not re.search(r"\b(for|pour|case|cover)\b", _clean_title(spec.name)))
    brand_in_title = item_brand is not None and item_brand in _clean_title(cand.title).replace(" ", "")
    brand_fits = item_brand is None or cand_brand == item_brand or (cand_brand is None and brand_in_title)
    if shared and not accessory and brand_fits:
        return MatchResult(0.9, "model", not exclusions, [f"model {sorted(shared)[0]} in the title"], exclusions)
    left = _clean_title(" ".join(filter(None, [spec.brand, spec.name])))
    right = _clean_title(cand.title)
    score = fuzz.token_set_ratio(left, right)
    # penalise candidates with many extra words (accessories, cases "for" the product)
    if re.search(r"\b(for|compatible with|pour)\b", right) and not re.search(r"\b(for|pour)\b", left):
        score -= 25
    confidence = round(max(score, 0) / 100 * 0.9, 3)
    accepted = score >= threshold and not exclusions
    return MatchResult(confidence, "fuzzy", accepted, [f"title similarity {score:.0f}%"], exclusions)
