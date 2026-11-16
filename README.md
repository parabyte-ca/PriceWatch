# PriceWatch CA
> Self-hosted wishlist price tracker that finds the lowest landed price in Canada and tells real deals from inflated "was" prices.

![Version](https://img.shields.io/badge/version-0.12.0-blue)

## Overview
PriceWatch CA keeps your wishlist, checks Canadian retailer product pages on a schedule,
and stores every price it sees. Your own history, not the retailer's "was" price, decides
whether a sale is real. Built for Black Friday and Cyber Monday 2026: add items early so
there is history to compare against.

## Features
- Simple to use: four tabs (Home, Add, Lists, Me), "Buy now" at the top of Home, and three-way presets for how eager to buy and when to be notified; every number is still there under Advanced
- Order-email import: forward a store's order confirmation to a dedicated mailbox and the purchase is recorded with its price protection, no typing
- Home Assistant sensors (buy-now count, claimable money, every item's price and verdict); see `docs/home-assistant.md`
- Scan a barcode in a store to add an item with its UPC, for exact matching
- "Will it get cheaper?" estimate per item from its own history and the sale calendar, with reasons
- Weekly report every Sunday, optionally summarised by Claude Haiku
- Sale-mode readiness checklist (System page) with a dry run of the Black Friday schedule against each store's polite limit, plus an automatic database copy before each sale mode starts
- Black Friday mode (Nov 26 to Dec 1) and Boxing Week mode (Dec 26 to 31): top hot items every 30 minutes, second digest, shorter alert window
- Basket planner: the cheapest way to split your buys across stores after free-shipping thresholds, tax and perks, with top-up tips
- Optional Claude Haiku check on uncertain product matches (your Anthropic API key; can reject lookalikes, never confirms)
- App notifications on each phone or computer (Web Push from the installed app, over HTTPS) with Open deal and Snooze buttons, alongside ntfy/Apprise
- Savings page: what you spent, what you saved against the typical (60-day median) price, what you claimed back, per person and per list
- Gift lists with occasion, recipient, date and a budget (spent vs remaining)
- Per-store perks you enter (cash-back portal, discounted gift cards, card bonus): the best offer also shows an "after perks" price
- RedFlagDeals comment summary per matched thread: crowd verdict (good price, wait, likely over), price-match reports, lowest quoted price, coupon codes, and a warning when the crowd disagrees with PriceWatch's own history
- Weekly flyers (opt-in): Flipp search near your postal code once a day; flyer prices are hints and never price history
- Test a product page (System): see what PriceWatch reads from a real retailer page and save a cleaned fixture for a new parser
- In-app updates for admins (System page, Updates): pick a release, watch live progress, roll back. A root cron job on TrueNAS (the upgrade agent, installed with `midclt`) validates the request and runs `update.sh` (backup, signature check, health check, automatic rollback); the container can only drop a small JSON request
- Price protection: record a purchase ("Bought") and PriceWatch keeps checking that store through the protection window (Costco 30 days; Best Buy's Black Friday Price Guarantee on badged items; or the days you enter). A claimable drop sends an instant alert and saves a proof package (page snapshot, SHA-256, UTC and local timestamps, parsed price) you can download as a zip
- RedFlagDeals Hot Deals feed every 15 minutes: threads are matched to everyone's items by model number or title, linked to stores you already track, duplicate threads collapse into one alert, and a tracked store is re-checked right away. Threads are hints, never prices
- Household accounts for any number of people: each person has their own login, lists, alert rules, notification URLs, quiet hours, province, snoozes and daily digest; prices are fetched once for everyone
- Shared lists with any number of members: the owner creates a single-use friend code per person (expires in 7 days, can edit or view only); the other person enters it on the Lists page. Leaving or removing someone never deletes price history
- Wishlist with target and maximum prices, priority, hot items (every 2 hours; every 30 minutes for the top 25 in Black Friday mode), notes
- Buy rule: BUY at or within 2% of the seasonal low (lowest landed price since Oct 1 or 90 days) or at your target; BUY + PROTECT within 5% when the retailer's price protection covers the rest of the event; otherwise WAIT, with a history confidence (LOW under 14 days, MEDIUM, HIGH 60+). LOW history never triggers a seasonal BUY
- Black Friday board: one phone-friendly list sorted BUY, BUY + PROTECT, WAIT
- Price-match opportunities from editable per-retailer policies (Best Buy and Staples event exclusions, Costco 30-day adjustment, Walmart no competitor match, Canadian Tire unverified and off)
- Amazon.ca through the Keepa API (optional, paid); history is seeded on first add. No direct Amazon scraping
- Optional changedetection.io bridge: hand any source to a changedetection.io restock watch and PriceWatch reads its price and stock
- Quick add: paste a list, bookmarklet, Android share target, iPhone Shortcut with a personal API token
- Every observation records channel, seller type (first party or marketplace), condition, coupon, fetch method and parse confidence; marketplace and non-new offers are kept but not compared by default
- Add an item by pasting a product URL: name, brand, MPN, GTIN, image and price are read from schema.org JSON-LD
- Several retailer URLs per item; manual price entry for in-store or unsupported sites
- Discovery through Google Shopping Canada (SerpApi or Bright Data, optional keys): candidate listings are matched and shown as suggestions to confirm or reject; rejections are remembered; results cached 7 days with a monthly search limit
- Matching: GTIN (check-digit validated), then model number within brand, then fuzzy title similarity, with a model-number conflict check (XM5 is not XM6)
- Per-item exclusions: refurbished, open box, used, marketplace sellers, bundles, other colours/sizes/storage; refurbished or used listings found during checks are not counted
- Tracking parameters (utm, gclid, srsltid and similar) are stripped from URLs so duplicates are caught
- Generic adapter: JSON-LD Product/Offer (including `@graph`, `AggregateOffer`, strikethrough prices, shipping), microdata, OpenGraph; per-retailer CSS selector overrides
- Playwright browser sidecar for JavaScript-rendered pages (per retailer or automatic fallback)
- Polite fetching: robots.txt, 20 s minimum per domain plus up to 30% jitter, one browser page per domain at a time, ETag/Last-Modified, honest User-Agent. A 200 page without a price that looks like a bot challenge counts as BLOCKED (never out of stock); 3 blocks in a row pause the domain for 6 hours and send one alert. A failed fetch never writes a price
- Landed price with provincial sales tax (all provinces and territories) and shipping
- Seasonal, 30/60/90-day and all-time lows (landed), real discount against the 60-day median, fake-sale flag (stated sale but more than 2% above the seasonal low, or a price raised before the sale)
- Status badges: BUY NOW, BUY + PROTECT, WAIT, FAKE SALE
- Alerts: instant pushes only for BUY / BUY + PROTECT, back in stock and blocked domains (ntfy gets Bought, Snooze 24h and Raise target buttons); everything else goes to the daily digest at 07:30 (plus 19:30 in Black Friday mode); quiet hours; snooze per item
- Price history chart per retailer, price-match flag per retailer
- System page with per-domain success rates, backoff state and recent fetches
- `/healthz` (database writable, data freshness, changedetection.io reachability), Prometheus `/metrics`, structured JSON logs, nightly `VACUUM INTO` backup at 03:30
- Sign-in per person (scrypt password hashes, rate-limited), personal API tokens, or `none` behind reverse proxy authentication (everyone acts as the admin)
- Mobile-first UI, installable as a home-screen app

## Requirements
- Docker with the compose plugin (TrueNAS SCALE apps host)
- About 1.5 GB disk for the two images; 512 MB RAM for the app and up to 2 GB for the browser sidecar
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

Then open `http://192.168.2.15:8086`, sign in as `admin`, go to **Settings**, add an Apprise URL such as
`ntfys://ntfy.sh/<private-topic>`, and press **Send test alert**.

Reverse proxy: add a Nginx Proxy Manager host (e.g. `pricewatch.moot.es` through the
Cloudflare Tunnel) pointing at `192.168.2.15:8086`; set `PRICEWATCH_COOKIE_SECURE=true` when
served over HTTPS. For proxy authentication instead of the built-in login, set
`PRICEWATCH_AUTH_MODE=none` and protect the host in the proxy.

While waiting for history, see `docs/phase0-stopgap.md` (changedetection.io stopgap).

### Adding your household

Settings, People in this household, Add person (username, display name, temporary password). They sign in,
change their password under Your account, and set their own notification URL. To share a list: Lists, Invite,
then they enter the friend code under Join a shared list.

## Update
**From the app (recommended):** System, Updates, choose the release, Update. Install the agent once:
```bash
cd /mnt/shared_vol/websites/pricewatch && sudo scripts/upgrade-agent.sh --install   # setup.sh does this on TrueNAS
sudo scripts/upgrade-agent.sh --status                                             # agent, status and releases
```
Folders: `upgrade/` (request inbox the container writes), `upgrade-status/` (agent replies and the live log,
read-only in the container), `.state/` (root-only, never mounted). Keep all three when moving the install.

**By hand:**
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
| `PRICEWATCH_ADMIN_USERNAME` | `admin` | First account, created on first start |
| `PRICEWATCH_ADMIN_PASSWORD` | generated | Password for the first account (only used until it is changed in the app) |
| `PRICEWATCH_COOKIE_SECURE` | `false` | `true` behind HTTPS |
| `PRICEWATCH_SECRET_KEY` | generated file | Session signing key |
| `PRICEWATCH_CONTACT` | `self-hosted` | Appended to the User-Agent |
| `PRICEWATCH_MIN_DOMAIN_INTERVAL` | `20` | Seconds between requests to one domain |
| `PRICEWATCH_DOMAIN_JITTER` | `0.3` | Extra random spacing (fraction of the interval) |
| `PRICEWATCH_MAX_CONCURRENCY` | `4` | Parallel checks across domains |
| `PRICEWATCH_DEFAULT_INTERVAL_MINUTES` | `360` | Normal check interval |
| `PRICEWATCH_HOT_INTERVAL_MINUTES` | `120` | Interval for hot items |
| `PRICEWATCH_BLACKFRIDAY_INTERVAL_MINUTES` | `30` | Interval for the top hot items in Black Friday mode |
| `PRICEWATCH_BLACKFRIDAY_MAX_ITEMS` | `25` | How many hot items get the Black Friday interval |
| `PRICEWATCH_BREAKER_BLOCKS` / `_HOURS` | `3` / `6` | Circuit breaker for blocking domains |
| `PRICEWATCH_PUBLIC_URL` | empty | Address your phone uses; enables ntfy action buttons. Use the https:// address for app notifications |
| `KEEPA_API_KEY` | empty | Amazon.ca prices and history via Keepa |
| `PRICEWATCH_IMAP_HOST` / `_PORT` / `_USER` / `_PASSWORD` / `_FOLDER` | empty / `993` / empty / empty / `INBOX` | Mailbox for forwarded order emails (also turn import on in Settings) |
| `ANTHROPIC_API_KEY` | empty | Claude Haiku second opinion on uncertain matches (also on in Settings) |
| `PRICEWATCH_LLM_MATCH_MODEL` | `claude-haiku-5-5` | Model for that check |
| `CHANGEDETECTION_URL` / `CHANGEDETECTION_API_KEY` | empty | changedetection.io bridge |
| `PRICEWATCH_BROWSER_ENABLED` | `true` | Use the Playwright sidecar |
| `PRICEWATCH_BROWSER_TIMEOUT` | `30` | Per-page hard timeout (seconds) |
| `PRICEWATCH_NOTIFY_URLS` | empty | Extra Apprise URLs, comma separated |
| `PRICEWATCH_LOG_LEVEL` | `INFO` | Log level |
| `SERPAPI_KEY` | empty | Enables SerpApi Google Shopping discovery |
| `BRIGHTDATA_API_KEY` | empty | Enables Bright Data SERP discovery |
| `BRIGHTDATA_ZONE` | `serp_api1` | Bright Data SERP API zone name |

App notifications (Web Push) need the app opened over HTTPS (Tailscale Serve or your reverse proxy); plain
http:// on the LAN cannot subscribe. The server's VAPID key is `data/vapid_private.pem` (keep it with your
backups; replacing it means each device turns notifications on again). Weekly flyer matching is off by default
(Settings, household section, with a postal code); it uses Flipp's public search, which is unofficial and may
stop answering, in which case it simply does nothing.

Order-email import reads one folder of a mailbox you create for it (for Gmail: turn on 2-step verification, create
an app password, use `imap.gmail.com`). Each person enters the address they forward from in Settings so purchases
land on their own list; anything else goes to the admin. Imported purchases keep deal alerts on unless the match
is near certain (model number, MPN, GTIN or identical title), so a wrong match never silences an item.

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
Design note: `docs/design.md`. Operations on TrueNAS (datasets, snapshots, access): `docs/operations.md`.
Backlog: `BACKLOG.md`.

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
| `blocked` / paused domain | The site returned 403/429/503 or a bot challenge. After 3 in a row the domain pauses for 6 hours (Retry-After is honoured). Log prices by hand meanwhile, or hand the source to changedetection.io. PriceWatch does not try to evade bot protection |
| `needs_keepa` | Amazon.ca needs `KEEPA_API_KEY`; meanwhile log Amazon prices by hand and use Amazon's Price History panel |
| `excluded` (marketplace) | A third-party seller or non-new listing was recorded but is not compared; change the item's matching rules to include it |
| `robots` | The site's robots.txt disallows the page. Untick "respect" only for pages you are comfortable fetching |
| `currency` | The page priced in another currency (US store); use the `.ca` URL |
| `excluded` | The page says the listing is refurbished or used and the item excludes that; change the item's matching rules if you want it |
| Discovery says "No search provider" | Set `SERPAPI_KEY` (or Bright Data) in `.env` and run `sudo docker compose up -d` |
| Discovery adds nothing | Expand the results list on the item page to see why each listing was skipped; set a custom search query on the item |
| Test alert says `logged` | No notification URL configured |
| Browser checks fail | `sudo docker logs pricewatch-browser`; screenshots of failed renders are in `data/screenshots/` |
| A purchase never shows a drop | Protection only follows first-party, new-condition prices from the same store and channel (Costco online and warehouse are separate). Manual-only sources need prices logged by hand |
| Forgot a password | The admin resets it under Settings, People. Admin locked out: `sudo docker exec -it pricewatch python -m pricewatch.reset_password admin` |
| Logs | `sudo docker logs --tail 100 pricewatch` |

## Changelog
See CHANGELOG.md

## License
Private, all rights reserved (parabyte-ca).
