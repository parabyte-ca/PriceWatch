# PriceWatch CA
> Self-hosted wishlist price tracker that finds the lowest landed price in Canada and tells real deals from inflated "was" prices.

![Version](https://img.shields.io/badge/version-0.2.0-blue)

## Overview
PriceWatch CA keeps your wishlist, checks Canadian retailer product pages on a schedule,
and stores every price it sees. Your own history, not the retailer's "was" price, decides
whether a sale is real. Built for Black Friday and Cyber Monday 2026: add items early so
there is history to compare against.

## Features
- Wishlist with target and maximum prices, priority, hot items (checked hourly), notes
- Add an item by pasting a product URL: name, brand, MPN, GTIN, image and price are read from schema.org JSON-LD
- Several retailer URLs per item; manual price entry for in-store or unsupported sites
- Discovery through Google Shopping Canada (SerpApi or Bright Data, optional keys): candidate listings are matched and shown as suggestions to confirm or reject; rejections are remembered; results cached 7 days with a monthly search limit
- Matching: GTIN (check-digit validated), then model number within brand, then fuzzy title similarity, with a model-number conflict check (XM5 is not XM6)
- Per-item exclusions: refurbished, open box, used, marketplace sellers, bundles, other colours/sizes/storage; refurbished or used listings found during checks are not counted
- Tracking parameters (utm, gclid, srsltid and similar) are stripped from URLs so duplicates are caught
- Generic adapter: JSON-LD Product/Offer (including `@graph`, `AggregateOffer`, strikethrough prices, shipping), microdata, OpenGraph; per-retailer CSS selector overrides
- Playwright browser sidecar for JavaScript-rendered pages (per retailer or automatic fallback)
- Polite fetching: robots.txt, 5 s minimum per domain plus jitter, ETag/Last-Modified, short response cache, honest User-Agent, automatic backoff on 403/429/503
- Landed price with provincial sales tax (all provinces and territories) and shipping
- 30/60/90-day and all-time lows, real discount against your observed 30-day median, fake-sale flag
- Status badges: BUY NOW, GOOD, WAIT, FAKE SALE
- Alerts through Apprise (ntfy by default): target hit, % drop, new all-time low, back in stock, source failing 24 h; de-duplicated per price level; quiet hours
- Price history chart per retailer, price-match flag per retailer
- System page with per-domain success rates, backoff state and recent fetches
- `/healthz`, Prometheus `/metrics`, structured JSON logs
- Single admin password, or `none` behind reverse proxy authentication
- Mobile-first UI, installable as a home-screen app

## Requirements
- Docker with the compose plugin (TrueNAS SCALE apps host)
- About 1.5 GB disk for the two images; 1 GB RAM for the browser sidecar
- Optional: `cosign` to verify release images; an ntfy topic (or any Apprise target) for alerts

## Setup
Port **8086** (registered in `dev-sop/ports.md`). Install folder on TrueNAS:
`/mnt/shared_vol/websites/pricewatch`.

```bash
sudo ss -tlnp | grep -E ':8086\b' || echo "8086 is free"     # measure twice
cd /mnt/shared_vol/websites
sudo git clone https://github.com/parabyte-ca/pricewatch.git
cd pricewatch
sudo ./setup.sh
```

`setup.sh` is idempotent. It creates `.env` (mode 600) from `.env.example`, generates the
admin password and prints it once, creates `data/` owned by uid 568, refuses to start if the
port is taken, pulls the signed release image (or builds locally), builds the browser
sidecar and waits for the health check.

Then open `http://192.168.2.15:8086`, go to **Settings**, add an Apprise URL such as
`ntfys://ntfy.sh/<private-topic>`, and press **Send test alert**.

Reverse proxy: add a Nginx Proxy Manager host (e.g. `pricewatch.moot.es` through the
Cloudflare Tunnel) pointing at `192.168.2.15:8086`; set `PRICEWATCH_COOKIE_SECURE=true` when
served over HTTPS. For proxy authentication instead of the built-in login, set
`PRICEWATCH_AUTH_MODE=none` and protect the host in the proxy.

While waiting for history, see `docs/phase0-stopgap.md` (changedetection.io stopgap).

## Update
```bash
cd /mnt/shared_vol/websites/pricewatch
sudo ./update.sh                    # latest release tag
sudo ./update.sh --version 0.2.0    # a specific release
sudo ./update.sh --ref main         # pre-release build from a branch
sudo ./update.sh --rollback         # previous deployment and its pre-update database
```
`update.sh` backs up the database (online SQLite backup), deploys a release tag, verifies
the image signature and revision when `cosign` is installed, waits for `/healthz`, and rolls
back automatically on failure. Log: `logs/update.log`. Backups: `data/backups/`.

## Configuration
All settings are in `.env` (see `.env.example`). Alert rules, province, quiet hours and
notification URLs are also editable on the Settings page.

| Variable | Default | Purpose |
|---|---|---|
| `PRICEWATCH_HOST_PORT` | `8086` | Host port |
| `PRICEWATCH_DATA_PATH` | `./data` | Database, backups, `.secret_key`, failure screenshots |
| `TZ` | `America/Toronto` | Quiet hours and display |
| `PRICEWATCH_AUTH_MODE` | `password` | `password` or `none` (reverse proxy auth) |
| `PRICEWATCH_ADMIN_PASSWORD` | generated | Admin login |
| `PRICEWATCH_COOKIE_SECURE` | `false` | `true` behind HTTPS |
| `PRICEWATCH_SECRET_KEY` | generated file | Session signing key |
| `PRICEWATCH_CONTACT` | `self-hosted` | Appended to the User-Agent |
| `PRICEWATCH_MIN_DOMAIN_INTERVAL` | `5` | Seconds between requests to one domain |
| `PRICEWATCH_DOMAIN_JITTER` | `3` | Extra random seconds |
| `PRICEWATCH_MAX_CONCURRENCY` | `4` | Parallel checks across domains |
| `PRICEWATCH_DEFAULT_INTERVAL_MINUTES` | `360` | Normal check interval |
| `PRICEWATCH_HOT_INTERVAL_MINUTES` | `60` | Interval for hot items |
| `PRICEWATCH_BROWSER_ENABLED` | `true` | Use the Playwright sidecar |
| `PRICEWATCH_BROWSER_TIMEOUT` | `30` | Per-page hard timeout (seconds) |
| `PRICEWATCH_NOTIFY_URLS` | empty | Extra Apprise URLs, comma separated |
| `PRICEWATCH_LOG_LEVEL` | `INFO` | Log level |
| `SERPAPI_KEY` | empty | Enables SerpApi Google Shopping discovery |
| `BRIGHTDATA_API_KEY` | empty | Enables Bright Data SERP discovery |
| `BRIGHTDATA_ZONE` | `serp_api1` | Bright Data SERP API zone name |

Search is used only for discovery, never for scheduled polling. The monthly search limit
(default 200), match threshold and auto-confirm on exact GTIN are on the Settings page. Google
Shopping results that only link to Google (no merchant URL) are listed but not added.

## Architecture
```
 phone / browser ──> Nginx Proxy Manager ──> pricewatch :8086 (FastAPI + React)
                                              │  scheduler tick (60 s) -> polite fetcher (httpx)
                                              │  adapters: JSON-LD, microdata, OpenGraph, CSS
                                              │  alerts -> Apprise -> ntfy
                                              │──ws──> pricewatch-browser :3000 (Playwright Chromium)
                                              └──> /data/pricewatch.db (SQLite WAL)
```
Design note: `docs/design.md`. Backlog: `BACKLOG.md`.

## Adapter authoring
Most Canadian retailers publish schema.org JSON-LD, which the generic adapter reads. When a
site does not:

1. **CSS overrides, no code:** `PATCH /api/retailers/{id}` with
   `{"selectors": {"price": ".price-now", "was_price": ".price-was", "name": "h1", "availability": ".stock", "image": "img.hero"}}`.
   Selectors win over structured data.
2. **Browser rendering:** set the retailer's fetch mode to `browser` on the System page when
   prices are rendered by JavaScript.
3. **Custom adapter:** add a class with `name` and
   `parse(html, url, retailer) -> ParsedProduct | None` in `backend/pricewatch/adapters/`,
   register it in `adapters/registry.py`, set `retailers.adapter` to its name, and add a saved
   page under `backend/tests/fixtures/` with a parser test.

## Development
```bash
cd backend && python -m venv .venv && .venv/bin/pip install -e '.[dev]' && .venv/bin/pytest
cd frontend && npm ci && npm run dev        # proxies /api to localhost:8086
scripts/smoke.sh --browser                  # full stack: add item, alert, browser render, restart
```

## Troubleshooting
| Symptom | Fix |
|---|---|
| `no_price` on a retailer | Open the System page error; try fetch mode `browser`, or add CSS selectors |
| `blocked` / backoff on a domain | The site returned 403/429. PriceWatch waits (15 min doubling to 24 h). Clear on the System page only if you changed something |
| `robots` | The site's robots.txt disallows the page. Untick "respect" only for pages you are comfortable fetching |
| `currency` | The page priced in another currency (US store); use the `.ca` URL |
| `excluded` | The page says the listing is refurbished or used and the item excludes that; change the item's matching rules if you want it |
| Discovery says "No search provider" | Set `SERPAPI_KEY` (or Bright Data) in `.env` and run `sudo docker compose up -d` |
| Discovery adds nothing | Expand the results list on the item page to see why each listing was skipped; set a custom search query on the item |
| Test alert says `logged` | No notification URL configured |
| Browser checks fail | `sudo docker logs pricewatch-browser`; screenshots of failed renders are in `data/screenshots/` |
| Forgot the password | It is `PRICEWATCH_ADMIN_PASSWORD` in `.env`; change it and run `sudo docker compose up -d` |
| Logs | `sudo docker logs --tail 100 pricewatch` |

## Changelog
See CHANGELOG.md

## License
Private, all rights reserved (parabyte-ca).
