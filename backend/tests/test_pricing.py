import pytest

from pricewatch.pricing import PROVINCE_TAX, effective_shipping, landed_price, tax_rate

EXPECTED = {"AB": 5, "BC": 12, "MB": 12, "NB": 15, "NL": 15, "NS": 14, "NT": 5, "NU": 5,
            "ON": 13, "PE": 15, "QC": 14.975, "SK": 11, "YT": 5}


def test_all_provinces_covered():
    assert set(PROVINCE_TAX) == set(EXPECTED)


@pytest.mark.parametrize("prov,rate", EXPECTED.items())
def test_landed_price_each_province(prov, rate):
    result = landed_price(10000, 1000, prov)  # $100 + $10 shipping
    assert float(tax_rate(prov)) == rate
    assert result["subtotal_cents"] == 11000
    assert result["tax_cents"] == round(11000 * rate / 100)
    assert result["landed_cents"] == 11000 + result["tax_cents"]


def test_quebec_rounding():
    assert landed_price(9999, None, "qc")["tax_cents"] == 1497  # 9999 * 14.975% = 1497.35


def test_unknown_shipping_flagged():
    r = landed_price(5000, None, "ON")
    assert r["shipping_known"] is False and r["landed_cents"] == 5650


def test_unknown_province():
    with pytest.raises(ValueError):
        tax_rate("XX")


def test_effective_shipping():
    assert effective_shipping(5000, 799) == 799
    assert effective_shipping(5000, None, free_threshold_cents=3500) == 0
    assert effective_shipping(2000, None, free_threshold_cents=3500, default_shipping_cents=599) == 599
    assert effective_shipping(2000, None) is None
