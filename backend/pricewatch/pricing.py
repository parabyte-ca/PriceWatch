"""Canadian sales tax and landed price.

Rates are combined GST/HST + PST/QST/RST as of 2026 for most consumer goods.
Verify against the CRA and provincial sites if a rate changes.
"""

from decimal import ROUND_HALF_UP, Decimal

# province code -> (name, combined rate in percent)
PROVINCE_TAX: dict[str, tuple[str, Decimal]] = {
    "AB": ("Alberta", Decimal("5")),
    "BC": ("British Columbia", Decimal("12")),
    "MB": ("Manitoba", Decimal("12")),
    "NB": ("New Brunswick", Decimal("15")),
    "NL": ("Newfoundland and Labrador", Decimal("15")),
    "NS": ("Nova Scotia", Decimal("14")),
    "NT": ("Northwest Territories", Decimal("5")),
    "NU": ("Nunavut", Decimal("5")),
    "ON": ("Ontario", Decimal("13")),
    "PE": ("Prince Edward Island", Decimal("15")),
    "QC": ("Quebec", Decimal("14.975")),
    "SK": ("Saskatchewan", Decimal("11")),
    "YT": ("Yukon", Decimal("5")),
}

DEFAULT_PROVINCE = "ON"


def tax_rate(province: str | None, overrides: dict | None = None) -> Decimal:
    """Combined rate in percent. `overrides` ({"ON": 13}) lets the user correct a rate without a release."""
    code = (province or DEFAULT_PROVINCE).upper()
    if code not in PROVINCE_TAX:
        raise ValueError(f"Unknown province code: {province}")
    if overrides and code in overrides:
        return Decimal(str(overrides[code]))
    return PROVINCE_TAX[code][1]


def _round_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def effective_shipping(
    price_cents: int,
    shipping_cents: int | None,
    free_threshold_cents: int | None = None,
    default_shipping_cents: int | None = None,
) -> int | None:
    """Shipping in cents, or None when unknown."""
    if shipping_cents is not None:
        return shipping_cents
    if free_threshold_cents is not None and price_cents >= free_threshold_cents:
        return 0
    return default_shipping_cents


def landed_price(price_cents: int, shipping_cents: int | None, province: str | None,
                 overrides: dict | None = None) -> dict:
    """Return pre-tax, tax, and landed totals in cents. Shipping is taxed like the goods."""
    ship = shipping_cents or 0
    subtotal = price_cents + ship
    tax = _round_cents(Decimal(subtotal) * tax_rate(province, overrides) / Decimal(100))
    return {
        "price_cents": price_cents,
        "shipping_cents": shipping_cents,
        "shipping_known": shipping_cents is not None,
        "subtotal_cents": subtotal,
        "tax_cents": tax,
        "landed_cents": subtotal + tax,
    }
