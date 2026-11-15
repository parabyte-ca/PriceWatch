from datetime import datetime, timedelta

from pricewatch.services.stats import Point, badge, fake_sale, raised_before, window_low

NOW = datetime(2026, 11, 27, 12, 0)


def series(prices, was=None, step_days=1):
    start = NOW - timedelta(days=step_days * (len(prices) - 1))
    return [Point(start + timedelta(days=i * step_days), p, was if i == len(prices) - 1 else None)
            for i, p in enumerate(prices)]


def test_window_low():
    pts = series([100, 90, 95, 120])
    assert window_low(pts, NOW, 1) == 95
    assert window_low(pts, NOW, None) == 90


def test_real_sale_not_fake():
    pts = series([10000] * 20 + [8000], was=10000)
    r = fake_sale(pts, NOW, 5)
    assert r["claims_sale"] and not r["fake"]
    assert r["real_discount_pct"] == 20.0


def test_fake_sale_inflated_was_price():
    pts = series([8000] * 20 + [7900], was=12000)  # only 1.25% below the median
    r = fake_sale(pts, NOW, 5)
    assert r["fake"] and "median" in r["reasons"][0]


def test_fake_sale_price_raised_before():
    pts = series([8000] * 10 + [9500, 9500, 9500] + [8000], was=9500)
    assert raised_before(pts)
    assert fake_sale(pts, NOW, 5)["fake"]


def test_no_claim_no_flag():
    pts = series([8000] * 5 + [9000])
    assert not fake_sale(pts, NOW, 5)["fake"]


def test_insufficient_history_does_not_flag_on_median():
    pts = series([7900], was=12000)
    assert not fake_sale(pts, NOW, 5)["fake"]


def test_badges():
    assert badge(None, None, 100, None, None, False, False, 3) == "NO DATA"
    assert badge(9000, 9000, 9500, 9000, 9000, True, True, 3) == "BUY NOW"
    assert badge(9000, 9000, 8000, 9000, 9000, True, True, 3) == "FAKE SALE"
    assert badge(9200, 9200, 8000, 9000, 9000, False, True, 3) == "GOOD"
    assert badge(9500, 9500, 8000, 9000, 9000, False, True, 3) == "WAIT"
    assert badge(9000, 9000, None, 9000, 9000, False, False, 3) == "WAIT"
