# PriceWatch CA: Design Note (v0.1)

Date: 2026-11-15. Status: approved to proceed (no blockers found).

## 1. Build versus extend

| Option | Strengths | Gaps for this use case |
|---|---|---|
| changedetection.io | Mature, Playwright support, restock/price plugin, history per URL | One URL = one watch. No product concept across retailers, no GTIN/MPN matching, no landed price, no fake-sale logic, no SERP discovery. Extending means forking a large Flask codebase. |
| PriceBuddy | Product with several store URLs, price history, notifications | PHP/Laravel stack (different from the rest of the homelab), scraper config per store via CSS only, no JSON-LD first approach, no matching pipeline, no tax/landed price, no deal feed. |
| Custom build | Product-centric model, JSON-LD first, Canadian tax and price-match logic, matching and SERP layers designed in from day one | Must be written; mitigated by a small MVP scope and the stopgap below. |

**Decision: custom build**, with changedetection.io as the Phase 0 stopgap
(see `docs/phase0-stopgap.md`). Reasons:

1. The core value (one item, many retailer listings, best landed price, real
   discount versus observed history) is the data model. Neither tool has it, and
   retrofitting it is more work than writing it.
2. Python/FastAPI matches the other parabyte-ca apps (NetWatch, MediaMate), so
   the same CI, setup.sh and update.sh patterns apply.
3. changedetection.io history can be exported to CSV and imported later
   (Phase 3 CSV import), so nothing collected in the stopgap is lost.

## 2. Architecture

```
            browser / PWA
                 |
        reverse proxy (NPM)  optional auth
                 |
   +-------------------------------+        ws://browser:3000
   | pricewatch (FastAPI, uvicorn) |------------------------+
   |  - REST API  /api/*           |                        |
   |  - SPA (React build)          |              +-------------------+
   |  - APScheduler tick (60 s)    |              | browser sidecar    |
   |  - polite fetcher (httpx)     |              | playwright run-    |
   |  - adapters (JSON-LD, CSS)    |              | server (Chromium)  |
   |  - alerts (Apprise -> ntfy)   |              +-------------------+
   +-------------------------------+
                 |
       /data/pricewatch.db  (SQLite WAL, bind mount on a TrueNAS dataset)
```

## 3. Schema (initial, money in integer cents, times in UTC)

- `items`: name, brand, model/MPN, GTIN, category, target, max acceptable,
  condition, notes, priority, deadline, hot flag, exclusion toggles
  (refurbished, open box, used, marketplace, bundles, variants), image.
- `retailers`: domain (unique), name, adapter, min interval seconds, CSS
  selector overrides (JSON), free shipping threshold, default shipping,
  price-match flag and notes, respect robots flag, backoff state.
- `source_links`: item, retailer, URL, status (suggested, confirmed, rejected),
  match confidence and method, fetch mode (auto, http, browser), ETag and
  Last-Modified, last price/stock, next check time, consecutive failures.
- `observations`: item, source link, observed at, price, was-price, shipping,
  currency, in stock, seller, payload hash, method (http, browser, manual).
- `fetch_runs`: source link, domain, started, duration, status, HTTP code, error.
- `alerts`: item, rule type, dedup key, title, body, status (sent, deferred,
  failed), created/sent times.
- `alert_rules`: per-item or global (item null) rule type, enabled, threshold.
- `settings`: key/value JSON (province, quiet hours, notification URLs, etc.).
- `deal_feed_entries`: feed, title, URL, published, matched item, score (Phase 3).

Postgres later: only portable SQLAlchemy types are used; SQLite pragmas are
applied in a dialect-guarded connect hook; `DATABASE_URL` selects the engine.

## 4. Adapter interface

```python
class Adapter(Protocol):
    name: str
    def parse(self, html: str, url: str, retailer: RetailerConfig) -> ParsedProduct | None: ...

@dataclass
class ParsedProduct:
    name, brand, mpn, gtin, sku, image, url
    price_cents, was_price_cents, currency, in_stock, seller, shipping_cents
    condition, source  # "jsonld" | "microdata" | "opengraph" | "css"
```

Order inside the generic adapter: JSON-LD Product/Offer (handles `@graph`,
`AggregateOffer`, offer lists, `priceSpecification`), then microdata
`itemprop=price`, then OpenGraph `product:price:amount`. Per-domain CSS
overrides in `retailers.selectors` win when present. A retailer row can switch
`fetch_mode` to `browser` to render with the Playwright sidecar first; `auto`
falls back to the browser only when httpx returns no price and
`PRICEWATCH_BROWSER_ENABLED=true`.

## 5. Polite fetching

Per-domain async lock plus minimum interval (default 5 s, jittered +0-3 s),
robots.txt cached 24 h, ETag/Last-Modified conditional requests, 5 minute
response cache for previews, honest User-Agent, exponential backoff on
403/429 (15 min doubling to 24 h, honouring `Retry-After`). Never logs in,
never solves CAPTCHAs.

## 6. Status badge

- BUY NOW: best landed price at or below target.
- FAKE SALE: retailer shows a was-price but the price is not at least
  `fake_sale_pct` below the observed 30-day median, or the price rose in the
  14 days before the drop.
- GOOD: within 3% of the observed 30-day low (or the all-time low).
- WAIT: everything else, or not enough history.

## 7. Port and paths

- Port **8086** (free in the registry range 8086-8089). setup.sh refuses to
  start if anything already listens on it. Audit TrueNAS with
  `sudo ss -tlnp | grep 8086` before first deploy; 8083 and 8085 were
  found occupied outside the registry before.
- Install folder: `/mnt/shared_vol/websites/pricewatch` (same pattern as
  NetWatch). Data: `./data` inside it (database, `backups/`, `.secret_key`).

## 8. Delta review, 2026-11-15 (v0.3.0)

Adopted from the delta review:
- Amazon: PA-API is retired and the Creators API needs 10 qualifying Associates sales, so Amazon.ca uses the
  Keepa API (optional, paid) or manual entry. No direct Amazon scraping.
- Buy rule on the seasonal low with history confidence; BUY + PROTECT where price protection covers the event.
- Price-match terms are data (`price_policies`), corrected for Canada: Walmart has no competitor match since 2020,
  Best Buy Canada and Staples exclude event prices, Canadian Tire is unverified and off, Best Buy US holiday
  policy does not apply.
- Politeness: 20 s per domain, plus or minus 30% schedule jitter, one browser page per domain, block detection on
  200 challenge pages, circuit breaker, failed fetches never write a price.
- Observation fields: channel, seller type, condition, coupon, fetch method, parse confidence.

Decided differently:
- **Fetch engine.** The review suggested changedetection.io as the fetch engine. PriceWatch's own fetcher was
  already built and tested, so it stays primary; changedetection.io is an optional per-source bridge (user
  decision, 2026-11-15).
- **Stealth browsers.** The review suggested Patchright or Camoufox. Not adopted: evading bot protection conflicts
  with the polite-scraping rules (honest User-Agent, stop on blocks). Blocked retailers fall back to manual entry.
- **Retailer JSON endpoints** (Best Buy province pricing, Canadian Tire store pricing): not built yet because they
  could not be tested from the build sandbox. Capture fixtures on TrueNAS with `scripts/capture_fixture.py` first.
