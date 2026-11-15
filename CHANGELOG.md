# Changelog

## [0.3.0] - 2026-11-15
### Added
- Buy rule from the 2026-11-15 delta review: seasonal low (since Oct 1 or 90 days, landed), history confidence (LOW/MEDIUM/HIGH), BUY within 2%, BUY + PROTECT within 5% when price protection covers the event, WAIT otherwise; rationale shown in the UI
- Black Friday mode (Nov 26 to Dec 1): top 25 hot items every 30 minutes, second daily digest, 2-hour alert window per item; Black Friday board page
- Price policies table (editable): Best Buy Canada, Staples, Costco, Walmart, Canadian Tire (unverified, off); price-match opportunities with event-exclusion caveats
- Keepa adapter for Amazon.ca (optional key), with history seeding; Amazon defaults to Keepa or manual entry, never direct scraping
- changedetection.io bridge: hand a source to a restock watch, sync its price and stock every 15 minutes
- Observation fields: channel, seller type, condition, coupon, parse confidence; marketplace and non-new offers recorded but not compared by default
- Block detection for 200 responses that are bot challenges; circuit breaker (3 blocks, 6 hours) with one alert
- ntfy action buttons (Bought, Snooze 24h, Raise target) through signed links; snooze per item
- Daily digest (07:30, plus 19:30 in Black Friday mode); drops, new lows and failing sources go to the digest by default
- Quick add: paste a list, bookmarklet, PWA share target, API token for an iPhone Shortcut
- Nightly `VACUUM INTO` backup; `/healthz` reports write check, freshness and changedetection.io
- Manual prices take a channel, condition and proof note
- Operations guide for TrueNAS (datasets, snapshot tasks, Tailscale access, browser recycle)

### Changed
- Politeness: 20 s per domain plus up to 30% jitter, one browser page per domain at a time, schedule jitter plus or minus 30%, hot items every 2 hours
- Lows and the fake-sale test use landed prices; GOOD badge replaced by the buy rule
- Retailer seed: The Source removed (now Best Buy Express); Sport Chek, Indigo, Shoppers Drug Mart added; Walmart and Costco default to the browser at 60 s spacing

### Fixed
- Database migrations now run with SQLite foreign keys off, so table rebuilds can no longer cascade-delete sources and price history

## [0.2.0] - 2026-11-15
### Added
- Search provider interface with SerpApi and Bright Data (Google Shopping, gl=ca), 7-day cache, monthly limit and usage on the System page
- Discovery: "Search Google Shopping" on each item and automatic search when adding by name; results stored as suggestions
- Matching pipeline: GTIN with check digit, model number within brand, fuzzy title (rapidfuzz) with model conflict check; confidence and reasons shown
- Confirm, reject and restore suggested listings; rejections are remembered
- Per-item exclusion toggles and custom search query; global match threshold and GTIN auto-confirm
- Refurbished or used listings detected during checks are recorded as `excluded`
- Retailer free-shipping threshold and default shipping editable on the System page
- Tracking parameters stripped from URLs

### Fixed
- Image signature check in setup.sh and update.sh now matches the repository name case-insensitively (GitHub reports `parabyte-ca/PriceWatch`)

## [0.1.0] - 2026-11-15
### Added
- Wishlist items with targets, priority, hot flag and exclusion toggles
- Add by URL with JSON-LD, microdata and OpenGraph parsing; CSS selector overrides per retailer
- Polite fetcher: robots.txt, per-domain spacing with jitter, conditional requests, response cache, backoff on 403/429/503
- Playwright browser sidecar with per-page timeout and screenshot on failure
- Scheduler: every 6 hours, hourly for hot items, failure backoff
- Observations, landed price with provincial tax, 30/60/90-day and all-time lows, real discount, fake-sale flag, badges
- Apprise alerts: target, % drop, all-time low, back in stock, failing source; de-duplication and quiet hours
- React PWA: wishlist, item detail with history chart, add item, settings, system health
- `/healthz`, `/metrics`, JSON logs, password or reverse proxy auth
- Docker image (non-root), compose with browser sidecar, setup.sh, update.sh with backup and rollback, smoke test, CI and signed release workflow
- Design note, Phase 0 changedetection.io stopgap guide, backlog (RedFlagDeals intelligence)
