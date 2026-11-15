# Changelog

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
