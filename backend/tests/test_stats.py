from datetime import datetime, timedelta

from pricewatch.services.stats import (
    Point,
    decide,
    fake_sale,
    history_confidence,
    low_since,
    median_since,
    raised_before,
    window_low,
)

NOW = datetime(2026, 11, 27, 12, 0)


def series(prices, step_days=1):
    start = NOW - timedelta(days=step_days * (len(prices) - 1))
    return [Point(start + timedelta(days=i * step_days), p) for i, p in enumerate(prices)]


def test_window_low_and_season():
    pts = series([100, 90, 95, 120])
    assert window_low(pts, NOW, 1) == 95
    assert window_low(pts, NOW, None) == 90
    assert low_since(pts, NOW - timedelta(days=1)) == 95
    assert median_since(pts, NOW - timedelta(days=10)) == 97


def test_history_confidence_levels():
    assert history_confidence([])[0] == "LOW"
    assert history_confidence(series([1] * 14))[0] == "LOW"     # 13 days span
    assert history_confidence(series([1] * 15))[0] == "MEDIUM"  # 14 days
    assert history_confidence(series([1] * 61))[0] == "HIGH"


def test_fake_sale_rules():
    pts = series([8000] * 20 + [8500])
    fake, reasons = fake_sale(8500, 12000, 8500, 8000, pts, 2)
    assert fake and "season" in reasons[0]
    assert not fake_sale(8100, 12000, 8100, 8000, series([8000] * 20 + [8100]), 2)[0]  # within 2%
    assert not fake_sale(9000, None, 9000, 8000, pts, 2)[0]  # no stated sale
    raised = series([8000] * 10 + [9500, 9500, 9500] + [8000])
    assert raised_before(raised)
    assert fake_sale(8000, 9500, 8000, 7000, raised, 2)[0]


def d(**kw):
    base = dict(current=10000, compare=10000, target=None, seasonal_low=10000, confidence="MEDIUM", buy_pct=2,
                protect_pct=5, protection=None, is_fake=False, horizon="Cyber Monday")
    base.update(kw)
    return decide(**base)


def test_decision_table():
    assert d(current=None).action == "NO_DATA"
    assert d(target=10000).action == "BUY"                                   # target hit
    assert d(current=10200).action == "BUY"                                 # within 2% of low
    assert d(current=10300).action == "WAIT"                                # 3% above, no protection
    assert d(current=10400, protection="30-day price adjustment").action == "BUY_AND_PROTECT"
    assert d(current=10600, protection="30-day price adjustment").action == "WAIT"  # over 5%
    assert d(current=10000, confidence="LOW").action == "WAIT"              # low history never auto-buys
    assert d(current=10000, confidence="LOW", target=10000).action == "BUY"
    assert d(current=11000, is_fake=True).badge == "FAKE SALE"
    assert d(current=10000).badge == "BUY NOW"
