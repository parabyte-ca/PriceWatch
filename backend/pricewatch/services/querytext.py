"""Turn a deal headline into product search terms.

Forum and store headlines carry prices, editions, store tags and sale words that make a shopping search miss:
"[Best Buy] Grand Theft Auto VI Pre-Order (Xbox Digital Code): Standard $96.50, Ultimate $122" should search for
"Grand Theft Auto VI Xbox". Product names that are already clean pass through unchanged.
"""

import re

TAG = re.compile(r"^\s*\[[^\]]{1,60}\]\s*")
PRICE = r"(?:C?\$\s?\d[\d,]*(?:\.\d{1,2})?|(?<![\w.])\d[\d,]*(?:\.\d{1,2})?\s?\$(?!\d))"  # $9.99 or 9,99$
PRICE_RE = re.compile(PRICE, re.I)
# "(Reg $549)", "was $99", "reg. 89.99$"
REG_RE = re.compile(rf"\(?\b(?:reg(?:ular)?|was|orig(?:inal)?|msrp|list)\.?\s*:?\s*{PRICE}\)?", re.I)
PCT_RE = re.compile(r"(?:\bsave\s+)?-?\d{1,2}\s?%\s*(?:off)?|\bsave\s+" + PRICE, re.I)
NOISE = [
    r"pre-?orders?", r"digital\s+(?:code|download|key)", r"download\s+code", r"\bcode\b", r"ymmv",
    r"free\s+shipping", r"\bfs\b", r"clearance", r"price\s+(?:error|drop)", r"all[\s-]time\s+low", r"\batl\b",
    r"lowest\s+price(?:\s+ever)?", r"\bhot\s+deal\b", r"\bdeal\b", r"\bsale\b", r"in[\s-]store(?:\s+only)?",
    r"online\s+only", r"\bb&m\b", r"after\s+(?:mail-?in\s+)?rebate", r"starting\s+(?:at|from)", r"\bonly\b",
    r"\bnow\b", r"\bnew\s+low\b", r"\bexpired\b", r"\bback\b(?=\s|$)",
]
NOISE_RE = re.compile("|".join(NOISE), re.I)
# "w/ code ABC", "with promo code", "+ free gift ..." end a headline's product part
TAIL_RE = re.compile(r"\s(?:w/|with\s+(?:code|promo|coupon)|\+\s*free|\bfor\s+" + PRICE + r"|@\s*" + PRICE + r").*$", re.I)


def tidy(text: str) -> str:
    """Product search terms from a headline; an already clean name comes back as it was."""
    s = (text or "").strip()
    if not s:
        return s
    s = TAG.sub("", s)
    # "Product (Platform): Standard $96.50, Ultimate $122" -> the part before the colon names the product
    if ":" in s:
        left, right = s.split(":", 1)
        if PRICE_RE.search(right) and len(left.split()) >= 2:
            s = left
    s = TAIL_RE.sub("", s)
    s = REG_RE.sub(" ", s)
    s = PCT_RE.sub(" ", s)
    s = PRICE_RE.sub(" ", s)
    s = NOISE_RE.sub(" ", s)
    s = re.sub(r"\(\s*([^()]*?)\s*\)", lambda m: f" {m.group(1)} " if m.group(1).strip() else " ", s)  # keep "(Xbox)"
    s = re.sub(r"[\[\]{}]", " ", s)
    s = re.sub(r"\s*[-–|,/:;!]+\s*$", "", re.sub(r"^\s*[-–|,/:;!]+\s*", "", s))
    s = re.sub(r"\s+([,.)])", r"\1", re.sub(r"\s{2,}", " ", s)).strip(" -–|,/:;.!")
    return s if len(s) >= 3 else (text or "").strip()
