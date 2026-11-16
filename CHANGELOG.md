# Changelog

## [1.2.0] - 2026-11-16
### Added
- Photo search on Add: take a photo of a product or its box and Claude reads what it is (and the barcode number when visible), then the comparison runs. The photo is not stored
- Alerts you can act on: ntfy and app notifications have Open store (the store's page), Bought (records the purchase at the cheapest watched store's price in one tap, so price protection starts) and Snooze. Opening the Bought link without pressing the button records nothing
- In-store stock near you: set your city (Settings, "Your city, for in-store stock") and search results show Google's "In stock nearby" and "Pick up today" notes
- eBay Canada through the official Browse API (optional `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET`): new, fixed-price listings appear with the marketplace sellers for reference
- Health check (System page, and a line in the admin's weekly report): stores whose checks mostly fail, watched stores without a fresh price, items without any price, search and Claude budgets, the forum feed and backups

## [1.1.0] - 2026-11-16
### Added
- Deals by category on Home: follow kinds of products ("TVs", "kitchen accessories", "3D printers", "women's clothing"; presets included) and PriceWatch collects their deals. New RedFlagDeals threads are sorted into your categories by Claude Haiku (titles only; by the category's words without a key), and a Google Shopping "on sale" search runs per category daily in Black Friday week and Boxing Week (weekly otherwise), keeping listings at least 20% under their was-price. Each deal has Watch (opens Add with it) and Hide
- Biggest drops on your items (latest store price against the week's high) and forum threads about your items, on Home
- Claude sorts search listings: bundles, accessories, refurbished units, other models and marketplace sellers are folded away instead of compared or tracked (one Haiku call per search, cached per title, within the monthly cap)
- Add shows stores as they are found (streamed: the first search, then store lists, then Claude), instead of after the whole search
- One-tap fixes: "Not this" on any listing (on Add and on the item page) hides it from that search and item for good; "Only this" on a watched store hides the others

## [1.0.2] - 2026-11-16
### Fixed
- Home showed only "List not found" when it remembered a list that no longer exists (with a single list there was no list picker to change it). It now falls back to all items
- Lists page: each list's name and a "View items" button open Home showing that list's items

## [1.0.1] - 2026-11-16
### Fixed
- Updating from 0.x to 1.0 failed at "Download and verify" with "no such service: browser": the old update script still built the browser sidecar that 1.0 removed. A placeholder service (never started) lets older update scripts finish, and `docker compose up` now removes the old browser container
- Updates now deploy with the new release's own update script, and a failure while deploying (not only a failed health check) rolls back automatically

## [1.0.0] - 2026-11-16
PriceWatch is now product-first: you name a product and it compares every Canadian store.

### Added
- One search box on Add for a name, a store link or a barcode (camera scan). PriceWatch works out the product and shows every Canadian store's price, cheapest first, with tax for your province and shipping, before anything is saved. Marketplace sellers and sites that are not known Canadian stores are folded away
- Watch: saves the product and tracks every recognised store at once, reusing the comparison's search (no second paid search). A suggested alert price, about 10% under today's best, is filled in
- Each store found becomes a watched store for the item and every search price is recorded as its history, so lows, the buy advice, price-match tips and alerts cover all stores
- About 40 Canadian stores recognised by the names search results use (Walmart.ca, Best Buy, EB Games, Costco and so on); The Source maps to Best Buy
- Smarter refresh: hot items and items close to their target first, twice a day during sale events, still paced to the monthly search limit
- Verify on a watched store: stores that block visits are read by Claude right away
- Item page leads with prices across stores; hidden stores can be watched again

### Changed
- Stores that block automated visits (Walmart, Costco, Canadian Tire, Sport Chek, Amazon.ca, Superstore) get prices from searches ("search results only") instead of the browser or Keepa
- "Sources" is now "Stores watched"; "Check" is "Verify"; "Search other stores" is "Refresh prices"
- Listings are no longer suggested for you to confirm: recognised stores are watched automatically and you hide any you do not want

### Removed
- The Playwright browser sidecar (one container less, about 2 GB less memory). `update.sh` removes the old container
- Keepa (Amazon.ca), the changedetection.io bridge, the Best Buy product JSON mode, proof screenshots, the page tester and fixtures tool, and the sale-mode readiness check
- Paste-a-list, bookmarklet and iPhone Shortcut instructions on Add (the Android share target and the API still work)
- Settings for auto-confirming matches and the browser fallback; `KEEPA_API_KEY`, `CHANGEDETECTION_*` and `PRICEWATCH_BROWSER_*` are ignored

## [0.16.0] - 2026-11-16
### Added
- Prices across stores: every search keeps the lowest price each store shows for the item (Google Shopping through SerpApi, or Claude web search), one row per store, cheapest first. Used and refurbished listings and poor matches are left out. Each row opens the store's page (or Google Shopping when Google gives no store link) and has a Track button to check that store's page on a schedule
- Item page: "Best price found online" at the top, with the store, the number of stores compared and when it was seen. Home shows it for items with no tracked price yet
- Alert when the best price found online reaches your target (once per price)
- Searches now refresh about daily per item instead of weekly, paced so the monthly search limit lasts the whole month

## [0.15.1] - 2026-11-16
### Fixed
- "Other stores" found results but no store links: Google Shopping now hides the stores' own links. PriceWatch opens the store list of the best matching product (one SerpApi search each, at most two, cached a week) and tracks the stores' own product pages. If that still gives no store link, it asks Claude's web search (when a key is saved)
- The results list shows store links first; Google-only results are folded away as "prices for reference only"
- Ask PriceWatch on phones: the question box sat under Android's gesture bar. The panel now fills the screen above the system bars, the box stays above the keyboard, and the app keeps clear of the status and gesture bars when installed

## [0.15.0] - 2026-11-16
### Added
- Prices from stores that block PriceWatch: when Best Buy, Walmart, Canadian Tire or another store answers PriceWatch's own check with a bot check (HTTP 403) or shows no price, Claude reads the current price instead, using Anthropic's web fetch and web search limited to that one store's site. PriceWatch itself still never tries to get past a bot check. Claude must report a price it actually saw for the exact product (never a guess), and links to other sites are ignored
- The Add page shows the price straight away for those stores, with a note that Claude read it; the item page marks such prices "price read by Claude"
- Stores paused after repeated blocks still get prices through Claude, without PriceWatch knocking again
- Household admin, Claude card: "Read prices with Claude when a store blocks PriceWatch" switch, a monthly spending cap (default US$15, 0 for none) and this month's estimated spend, price checks and searches. Price checks use Claude Haiku at low effort, at most twice a day per link; a Preview's answer is reused by the first check after saving. Store searches (finding the same product elsewhere) count toward the same cap

## [0.14.0] - 2026-11-16
### Added
- PriceWatch finds the same product at other stores by itself: right after an item is added (by link, name or barcode) and again about weekly. With a Claude key and no SerpApi/Bright Data key, it uses Claude's web search limited to the Canadian stores PriceWatch knows; results go through the usual matcher and polite checker, and the monthly search cap applies. Same model number or barcode: tracked at once and checked right away; close matches wait for you to confirm. The item page shows the search while it runs
- Ask PriceWatch: ask about your lists, prices, purchases and savings in plain language (same design as Ask NetWatch). Claude reads through PriceWatch's own API as you and cannot change anything; 40 questions an hour
- Household admin, Claude card: save the Anthropic key (stored encrypted with `data/.secret_key`, never shown again), pick the model and effort, test, forget. Every Claude feature uses it; `ANTHROPIC_API_KEY` in .env still works
- In-app updates like NetWatch and MediaMate: live steps (requested, agent started, backup, download and verify, restart, health check, done) read from the update log, a timer, a time estimate from past updates, a striped progress bar, the latest log line, a success or failure finish (with "rolled back automatically" when that happened), a slim bar across the top of every page for admins with the percentage in the tab title, and update history. The page keeps going while PriceWatch restarts. `update.sh` logs in UTC with a line per step; the host agent keeps `history.jsonl` (last 50)
- Prices embedded as page data (Next.js `__NEXT_DATA__`, the shape Walmart Canada uses) are read when a page has no standard product markup

### Fixed
- The Add page says when a store answered with a "Robot or human?" check instead of reporting "ok" with no price (PriceWatch never tries to get past those)

## [0.13.0] - 2026-11-16
### Security
- PriceWatch no longer fetches addresses on your own network. Store links, previews, list imports, the page test, the browser (every navigation and every request a page makes) and redirects must be public http(s) addresses: private, loopback, link-local and carrier-grade ranges, `localhost`, `.local`/`.lan`/single-label names, and names that resolve to them are refused. Before, anyone signed in could make the server read the router or TrueNAS pages. `PRICEWATCH_ALLOW_PRIVATE_URLS=true` turns this off (the smoke test's fixture server uses it)
- Web-push subscriptions must point at a public push service; household members (not admins) can't send notifications to a home-network address
- Security headers on every response (Content-Security-Policy, X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy) and `Cache-Control: no-store` on the API

### Added
- Edit an item's name, brand, model number and barcode, and move it to another list, on its page
- Price-match helper: "Show at the till" opens a full-screen card with the competitor's price, when and where it was seen, a button to open the live page, and the store's policy and caveats
- Family link for a list: a read-only page anyone with the link can open without an account (items, current best price and store link, optionally what's already bought). Never budgets, prices paid, notes or names. Turn it off any time. Migration 0009

## [0.12.0] - 2026-11-16
### Changed
- Simpler app: four tabs (Home, Add, Lists, Me), with a tab bar at the bottom on phones. Home replaces Wishlist and Board: "Buy now" cards, "Waiting for a better price" and "Getting set up", each with one plain sentence. Me holds Bought, Savings, Basket, Settings and, for admins, Household admin. Old links (/board) still work
- Settings start with "The basics": where you shop, "How eager to buy?" (Patient, Balanced, Eager) and "When should we notify you?" (Only when to buy, Buys and big drops, Everything), notifications on this device, daily summary and quiet hours. Everything else, including your account and API token, is under Advanced
- New default: forum-thread and flyer matches go to the daily summary instead of a notification ("Only when to buy"); a flyer match with flyer alerts off now lands in the summary instead of being dropped

## [0.11.0] - 2026-11-16
### Added
- Order-email import: forward order confirmations to a mailbox PriceWatch reads every 10 minutes (IMAP, opt-in). It finds the store, order number and date and your tracked items in the email and records each as a purchase with the store's price-protection terms, then alerts you. Lines it cannot match are listed on the Bought page to link by hand. Each person sets the address they forward from. Optionally Claude Haiku reads the email instead (household setting, off by default; the email text goes to Anthropic)
- Listings that are "compatible with", "replacement for" or "for use with" a product are excluded as not the brand's own product

### Fixed
- The Claude Haiku second opinion (v0.8.0 onward) never ran outside tests: its 80-to-94 band was compared with the matcher's 0-to-0.9 confidence. It now uses the title similarity behind the score, with a regression test on real matcher output

## [0.10.1] - 2026-11-16
### Fixed
- Browser checks no longer fail when a store page keeps loading (Sport Chek "Timeout 30000ms exceeded"): PriceWatch waits for the first response, then for a price on the page, and reads what has rendered by the deadline
- Page titles that are not product names ("General PDP Template", error and challenge pages, the store's own name) are replaced with a name taken from the product URL
- Sport Chek defaults to browser mode with 45 s spacing, like Canadian Tire (same platform); existing installs still on "auto" are switched
- Clearer message when no price is found, with the next steps

## [0.10.0] - 2026-11-16
### Added
- "Will it get cheaper?" on each item: a low, medium or high chance of a lower price soon, a likely low, and the reasons (drops seen, price against its usual level, two-week trend, next sale event); needs 10 days of prices
- Weekly report, Sunday 18:00 (each person can turn it off): what to buy, what moved, what you bought and saved, money to claim; with the Claude check set up, Claude Haiku adds a two or three sentence summary on top

## [0.9.0] - 2026-11-16
### Added
- Home Assistant REST sensors: `/api/ha/summary` (buy-now count, counts by verdict, claimable money, sale mode, every item) and `/api/ha/items/<id>`, using a personal API token; setup and an example automation in `docs/home-assistant.md`
- Scan a barcode to add an item (Add page): camera scanning where the browser supports it (Chrome on Android, HTTPS), or type the UPC/EAN; PriceWatch looks it up once (cached) and you pick the product, which is saved with its barcode
- The optional Claude Haiku check now also screens RedFlagDeals threads and flyer matches that score 80 to 94, before any alert

## [0.8.0] - 2026-11-16
### Added
- Sale-mode readiness (System page): sale mode on, scheduler, hot items without a store, store links without a good check in 24 h, paused or weak stores, alert delivery for each person, browser sidecar, backup age, disk space, and a dry run of the faster schedule against each store's polite request limit
- Automatic database copy in the 6 hours before each sale mode starts (`data/backups/pre-blackfriday-2026.sqlite`, kept outside the nightly rotation)
- Board shows when a sale mode is on and flags items whose price may be stale
- Basket page: pick items (BUY ones are picked to start) and get the cheapest split across stores after free-shipping thresholds, flat shipping, tax and perks, the saving against buying one by one, and "add $X for free shipping" tips. Exact for normal baskets, search for very large ones
- Boxing Week mode (Dec 26 to 31 by default): the same faster schedule, second digest and alert window as Black Friday mode
- Optional Claude Haiku second opinion on uncertain discovery matches (scores 80 to 94): needs `ANTHROPIC_API_KEY` and the household setting; it can turn down a lookalike but never confirms a listing; answers are cached; only the item name, brand and model and the listing title, merchant and condition are sent
- Database migration 0007

## [0.7.0] - 2026-11-16
### Added
- App notifications (Web Push) on each device from the installed app, with Open deal and Snooze 7 days buttons; Settings, "Notifications on this device". Needs HTTPS; on iPhone/iPad the app must be added to the home screen (iOS 16.4+). VAPID keys are created once in the data folder
- Savings page: spent, saved against the 60-day typical price when you bought, claimed back and still to claim; by person and by list
- Gift lists: occasion, recipient, date and budget per list, with spent vs remaining on the Lists page
- Cash back, gift card and card perks per store (System page, entered by hand): item pages show the best offer "after perks"
- RedFlagDeals comment summary for matched threads (every 2 hours while under 7 days old): all-time-low and wait signals, price-match reports, stock and expiry, lowest quoted price, coupon codes, and a note when the crowd disagrees with PriceWatch's own history. No usernames or post text are stored
- Weekly flyer matching (opt-in, off by default): one Flipp search per item per day near your postal code; matches are hints, alert instantly at or under target, otherwise in the digest
- Proof packages now include a full-page browser screenshot (with its SHA-256) when the browser sidecar is on
- System page, "Test a product page": robots.txt, status, bot challenge, JSON-LD types and parsed price over HTTP and optionally the browser; saves a cleaned fixture to `data/fixtures/` for new parsers
- Best Buy product JSON fetch mode (beta, opt-in on the System page for bestbuy.ca); falls back to the product page if it does not answer

### Changed
- Canadian Tire defaults to browser mode with 45 s spacing (prices are rendered by script); existing installs still on "auto" are switched
- Alerts count as sent when either an app notification or an Apprise URL accepts them
- Database migration 0006

## [0.6.1] - 2026-11-16
### Fixed
- Phone layout: the menu is one sideways-scrolling row (it overflowed and stretched the active tab), and the user name and Sign out moved to the top bar
- Inputs in two-column settings rows line up when one label wraps
- Item page fits narrow screens: sources table shows stock, last check and actions under the store name; the manual price form wraps
- Long codes and URLs wrap instead of widening the page; alert toggles stack on phones

## [0.6.0] - 2026-11-15
### Added
- In-app updates for admins (System page): choose a release, check for updates, roll back, live log and status
- Host upgrade agent (`scripts/upgrade-agent.sh`, root cron job via `midclt`, every minute): validates the request strictly (regular file, size limit, strict JSON with known keys, X.Y.Z that is a real tag; never sourced or eval'd), runs `update.sh`, reports through a read-only status folder; `--install`, `--uninstall`, `--status`
- setup.sh creates the `upgrade/`, `upgrade-status/` and `.state/` folders with the right owners and installs the agent on TrueNAS
- Test covering many household members and a list shared with several people

## [0.5.0] - 2026-11-15
### Added
- Purchases ("Bought" on an item, Bought page): protection terms from the retailer policy (Costco 30 days, Best Buy Black Friday Price Guarantee when badged) or your own number of days; protected stores keep being checked even after the item stops alerting
- Claimable drop alerts (instant) with a proof package: page HTML, SHA-256, UTC and local timestamps, parsed price and seller, downloadable as a zip
- RedFlagDeals Hot Deals feed matching (every 15 minutes, robots-respecting, XML parsed without entity expansion): links threads to items and already-tracked stores, collapses duplicate threads, triggers a confirming check
- Model-number matching: a shared model number (same brand, not an accessory) is a strong match for discovery and the deal feed
- Digest lists claimable drops and protection windows ending within 3 days

## [0.4.0] - 2026-11-15
### Added
- Household accounts: per-person login (scrypt), lists, settings (province, alerts, quiet hours, notification URLs, digest, My Best Buy membership), snoozes, alerts and digests
- Lists page: create, rename, delete empty lists; share with a single-use friend code (7 days, editor or viewer); leave or remove members
- People admin: add people, reset passwords, disable accounts; personal API tokens (stored hashed, shown once)
- `python -m pricewatch.reset_password <username>` for a locked-out admin

### Changed
- Sign-in asks for a username (`admin` for the first account); `PRICEWATCH_ADMIN_PASSWORD` sets the first account's password
- Upgrade moves existing items to the admin's "My list" and personal settings to the admin's account (migration 0004, tested on a populated database)
- Operational alerts (blocked retailers) go to admins only

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
