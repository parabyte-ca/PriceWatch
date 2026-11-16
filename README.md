# PriceWatch CA
> Self-hosted wishlist price tracker that finds the lowest landed price in Canada and tells real deals from inflated "was" prices.

![Version](https://img.shields.io/badge/version-1.2.0-blue)

## Overview
Type a product, paste a store link or scan a barcode, and PriceWatch CA shows every Canadian
store's price for it, best first, with tax for your province. Press Watch and it keeps comparing
those stores about daily, records every price, and tells you when to buy. Your own history,
not the retailer's "was" price, decides whether a sale is real.

## Features
- One search box: a product name, a store link or a barcode (scan with the camera). PriceWatch works out the product and shows every Canadian store's price, cheapest first, with tax and shipping; marketplace sellers and unknown sites are folded away
- Watch tracks every recognised Canadian store at once (Best Buy, Walmart, Costco, Canadian Tire, Staples, Amazon.ca and about 35 more) and records each search price as history, so lows, alerts and the buy advice cover all stores. A suggested alert price (about 10% under today's best) is filled in
- Prices refresh about daily per item, hot and near-target items first, twice a day during sale events, paced so the monthly search limit lasts the month
- Sources: Google Shopping through SerpApi (one search plus the product's store list), Claude web search when needed, and each store's own page when it allows visits. Stores that block automated visits get their prices from searches; Verify asks Claude to read the store page right now
- Deals by category on Home (TVs, kitchen accessories, 3D printers, anything): RedFlagDeals threads sorted in by Claude, plus daily Google Shopping "on sale" searches during sale events; biggest drops on your items and matching forum threads
- Claude sorts out bundles, accessories, refurbished units and marketplace sellers so the comparison shows the product itself; "Not this" and "Only this" fix anything in one tap
- Photo search (Claude reads the product from a photo), in-store stock near your city, optional eBay Canada listings, and alerts with Open store and one-tap Bought
- Health check on the System page: failing stores, stale prices, search and Claude budgets, forum feed, backups
- Optional Claude check on uncertain matches (can reject a lookalike so it is not compared)
- Ask PriceWatch: plain-language questions about your lists and prices, answered by Claude from your own data (key saved in Household admin)
- Family link: share a gift list read-only, no account needed; price-match card to show at the till; edit or move any item
- Only public store pages are ever fetched: nothing on your home network can be reached through PriceWatch
- Simple to use: four tabs (Home, Add, Lists, Me), "Buy now" at the top of Home, and three-way presets for how eager to buy and when to be notified; every number is still there under Advanced
- Order-email import: forward a store's order confirmation to a dedicated mailbox and the purchase is recorded with its price protection, no typing
- Home Assistant sensors (buy-now count, claimable money, every item's price and verdict); see `docs/home-assistant.md`
- "Will it get cheaper?" estimate per item from its own history and the sale calendar, with reasons
- Weekly report every Sunday, optionally summarised by Claude Haiku
- Black Friday mode (Nov 26 to Dec 1) and Boxing Week mode (Dec 26 to 31): top hot items every 30 minutes, second digest, shorter alert window
- Basket planner: the cheapest way to split your buys across stores after free-shipping thresholds, tax and perks, with top-up tips
- App notifications on each phone or computer (Web Push from the installed app, over HTTPS) with Open deal and Snooze buttons, alongside ntfy/Apprise
- Savings page: what you spent, what you saved against the typical (60-day median) price, what you claimed back, per person and per list
- Gift lists with occasion, recipient, date and a budget (spent vs remaining)
- Per-store perks you enter (cash-back portal, discounted gift cards, card bonus): the best offer also shows an "after perks" price
- RedFlagDeals comment summary per matched thread: crowd verdict (good price, wait, likely over), price-match reports, lowest quoted price, coupon codes, and a warning when the crowd disagrees with PriceWatch's own history
- Weekly flyers (opt-in): Flipp search near your postal code once a day; flyer prices are hints and never price history
- In-app updates for admins (System page, Updates): pick a release, watch live progress, roll back. A root cron job on TrueNAS (the upgrade agent, installed with `midclt`) validates the request and runs `update.sh` (backup, signature check, health check, automatic rollback); the container can only drop a small JSON request
- Price protection: record a purchase ("Bought") and PriceWatch keeps checking that store through the protection window (Costco 30 days; Best Buy's Black Friday Price Guarantee on badged items; or the days you enter). A claimable drop sends an instant alert and saves a proof package (page snapshot, SHA-256, UTC and local timestamps, parsed price) you can download as a zip
- RedFlagDeals Hot Deals feed every 15 minutes: threads are matched to everyone's items by model number or title, linked to stores you already track, duplicate threads collapse into one alert, and a tracked store is re-checked right away. Threads are hints, never prices
- Household accounts for any number of people: each person has their own login, lists, alert rules, notification URLs, quiet hours, province, snoozes and daily digest; prices are fetched once for everyone
- Shared lists with any number of members: the owner creates a single-use friend code per person (expires in 7 days, can edit or view only); the other person enters it on the Lists page. Leaving or removing someone never deletes price history
- Wishlist with target and maximum prices, priority, hot items (every 2 hours; every 30 minutes for the top 25 in Black Friday mode), notes
- Buy rule: BUY at or within 2% of the seasonal low (lowest landed price since Oct 1 or 90 days) or at your target; BUY + PROTECT within 5% when the retailer's price protection covers the rest of the event; otherwise WAIT, with a history confidence (LOW under 14 days, MEDIUM, HIGH 60+). LOW history never triggers a seasonal BUY
- Black Friday board: one phone-friendly list sorted BUY, BUY + PROTECT, WAIT
- Price-match opportunities from editable per-retailer policies (Best Buy and Staples event exclusions, Costco 30-day adjustment, Walmart no competitor match, Canadian Tire unverified and off)
- Every observation records channel, seller type (first party or marketplace), condition, coupon, fetch method and parse confidence; marketplace and non-new offers are kept but not compared by default
- Several retailer URLs per item; manual price entry for in-store or unsupported sites
- Matching: GTIN (check-digit validated), then model number within brand, then fuzzy title similarity, with a model-number conflict check (XM5 is not XM6)
- Per-item exclusions: refurbished, open box, used, marketplace sellers, bundles, other colours/sizes/storage; refurbished or used listings found during checks are not counted
- Tracking parameters (utm, gclid, srsltid and similar) are stripped from URLs so duplicates are caught
- Generic adapter: JSON-LD Product/Offer (including `@graph`, `AggregateOffer`, strikethrough prices, shipping), microdata, OpenGraph; per-retailer CSS selector overrides
- Polite fetching: robots.txt, 20 s minimum per domain plus up to 30% jitter, ETag/Last-Modified, honest User-Agent. A 200 page without a price that looks like a bot challenge counts as BLOCKED (never out of stock); 3 blocks in a row pause the domain for 6 hours and send one alert. A failed fetch never writes a price
- Landed price with provincial sales tax (all provinces and territories) and shipping
- Seasonal, 30/60/90-day and all-time lows (landed), real discount against the 60-day median, fake-sale flag (stated sale but more than 2% above the seasonal low, or a price raised before the sale)
- Status badges: BUY NOW, BUY + PROTECT, WAIT, FAKE SALE
- Alerts: instant pushes only for BUY / BUY + PROTECT, back in stock and blocked domains (ntfy gets Bought, Snooze 24h and Raise target buttons); everything else goes to the daily digest at 07:30 (plus 19:30 in Black Friday mode); quiet hours; snooze per item
- Price history chart per store, price-match flag per store
- System page with per-domain success rates, backoff state and recent fetches
- `/healthz` (database writable, data freshness), Prometheus `/metrics`, structured JSON logs, nightly `VACUUM INTO` backup at 03:30
- Sign-in per person (scrypt password hashes, rate-limited), personal API tokens, or `none` behind reverse proxy authentication (everyone acts as the admin)
- Mobile-first UI, installable as a home-screen app

## Requirements
- Docker with the compose plugin (TrueNAS SCALE apps host)
- About 500 MB disk for the image; 512 MB RAM
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
port is taken, pulls the signed release image (or builds locally) and waits for the health check.

Then open `http://192.168.2.15:8086`, sign in as `admin`, go to **Settings**, add an Apprise URL such as
`ntfys://ntfy.sh/<private-topic>`, and press **Send test alert**.

Reverse proxy: add a Nginx Proxy Manager host (e.g. `pricewatch.moot.es` through the
Cloudflare Tunnel) pointing at `192.168.2.15:8086`; set `PRICEWATCH_COOKIE_SECURE=true` when
served over HTTPS. For proxy authentication instead of the built-in login, set
`PRICEWATCH_AUTH_MODE=none` and protect the host in the proxy.


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
| `PRICEWATCH_IMAP_HOST` / `_PORT` / `_USER` / `_PASSWORD` / `_FOLDER` | empty / `993` / empty / empty / `INBOX` | Mailbox for forwarded order emails (also turn import on in Settings) |
| `PRICEWATCH_ALLOW_PRIVATE_URLS` | `false` | Allow fetching home-network addresses (testing only) |
| `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` | empty | eBay Canada listings through the Browse API (free developer keys) |
| `ANTHROPIC_API_KEY` | empty | Fallback Claude key (better: save it in Household admin, stored encrypted) |
| `PRICEWATCH_LLM_MATCH_MODEL` | `claude-haiku-5-5` | Model for that check |
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
2. **Search results only:** set the store to "search results only" on the System page when its
   pages carry no readable price or block visits; its prices then come from the daily searches.
3. **Custom adapter:** add a class with `name` and
   `parse(html, url, retailer) -> ParsedProduct | None` in `backend/pricewatch/adapters/`,
   register it in `adapters/registry.py`, set `retailers.adapter` to its name, and add a saved
   page under `backend/tests/fixtures/` with a parser test.

## Development
```bash
cd backend && python -m venv .venv && .venv/bin/pip install -e '.[dev]' && .venv/bin/pytest
cd frontend && npm ci && npm run dev        # proxies /api to localhost:8086
scripts/smoke.sh                            # full stack: add item, alert, restart
```

## Troubleshooting
| Symptom | Fix |
|---|---|
| `no_price` on a store | The page has no readable price. Set the store to "search results only" on the System page; its prices then come from the daily searches |
| `blocked` / paused domain | The site returned 403/429/503 or a bot challenge. After 3 in a row the domain pauses for 6 hours (Retry-After is honoured). Its prices keep coming from the cross-store searches, and Claude reads the page when you press Verify. PriceWatch does not try to evade bot protection |
| `excluded` (marketplace) | A third-party seller or non-new listing was recorded but is not compared; change the item's matching rules to include it |
| `robots` | The site's robots.txt disallows the page. Untick "respect" only for pages you are comfortable fetching |
| `currency` | The page priced in another currency (US store); use the `.ca` URL |
| `excluded` | The page says the listing is refurbished or used and the item excludes that; change the item's matching rules if you want it |
| Discovery says "No search provider" | Set `SERPAPI_KEY` (or Bright Data) in `.env` and run `sudo docker compose up -d` |
| Discovery adds nothing | Expand the results list on the item page to see why each listing was skipped; set a custom search query on the item |
| Test alert says `logged` | No notification URL configured |
| A purchase never shows a drop | Protection only follows first-party, new-condition prices from the same store and channel (Costco online and warehouse are separate). Manual-only sources need prices logged by hand |
| Forgot a password | The admin resets it under Settings, People. Admin locked out: `sudo docker exec -it pricewatch python -m pricewatch.reset_password admin` |
| Logs | `sudo docker logs --tail 100 pricewatch` |

## Changelog
See CHANGELOG.md

## License
Private, all rights reserved (parabyte-ca).
