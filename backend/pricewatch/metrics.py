from prometheus_client import Counter, Gauge, Histogram

FETCH_TOTAL = Counter("pricewatch_fetch_total", "Fetch attempts", ["domain", "status", "method"])
FETCH_SECONDS = Histogram("pricewatch_fetch_seconds", "Fetch duration", ["method"],
                          buckets=(0.25, 0.5, 1, 2, 5, 10, 20, 40))
ALERTS_TOTAL = Counter("pricewatch_alerts_total", "Alerts by rule and delivery status", ["rule", "status"])
ITEMS_GAUGE = Gauge("pricewatch_items", "Active wishlist items")
SOURCES_GAUGE = Gauge("pricewatch_sources", "Confirmed source links")
