---
name: pricewatch
description: Context, conventions and troubleshooting for PriceWatch CA (parabyte-ca/PriceWatch), Alan's self-hosted Canadian price tracker on TrueNAS. It compares every Canadian store's price for a product (Google Shopping via SerpApi, Claude web search, polite store-page fetches), tracks history, tells real deals from fake "was" prices, and sends buy alerts. Use whenever the user mentions PriceWatch, price tracking, deals, Black Friday or Boxing Day planning, RedFlagDeals, SerpApi, price protection or price matching, the receipt photo, gift lists or claims, update.sh or setup.sh for PriceWatch, or wants a feature or fix in the PriceWatch repo, even if they don't name the app.
---

# PriceWatch CA

Self-hosted price tracker for one Canadian household. Repo `parabyte-ca/PriceWatch`, deployed on TrueNAS at
`/mnt/shared_vol/websites/pricewatch`, port 8086 behind Nginx Proxy Manager. Follow the `dev-sop` skill for
versioning, README, Docker and script standards; this file adds what is specific to PriceWatch.

## Stack
- Backend: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, SQLite (WAL) in `/data`, APScheduler (`pricewatch/scheduler.py`).
- Frontend: React + Vite + Tailwind PWA (`frontend/src`), four tabs: Home, Add, Lists, Me. Built into the image.
- Alerts: Apprise (ntfy), Web Push, weekly report. Ask PriceWatch and all AI features use the Anthropic SDK.
- One container (`pricewatch`); `docker-compose.yml` keeps a scale-0 `browser` placeholder so old `update.sh` copies do not fail.

## How prices work (the product model)
- A watched item has one confirmed `SourceLink` per known Canadian store (`services/retailers.py` SEED, about 40 stores with aliases).
- `discovery.compare` runs one Google Shopping search (SerpApi, `gl=ca`) plus the immersive store list; `save_offers` / `_sync_store` turn merchants into stores and record each price as an `Observation` (method `search`).
- Fetch modes per store: `auto` (polite page fetch), `search` (prices from searches only), `manual`. Verify on a search-only store asks Claude to read the page (`claude_price`, `force=True`).
- `services/classify.py` (Claude Haiku) labels listings same / bundle / accessory / refurbished / different / marketplace, cached in `LlmMatchCache`. `matching.generation_conflict` stops "Switch" matching "Switch 2".
- `services/summary.py` builds every item's verdict (BUY, BUY_AND_PROTECT, WAIT...), landed price with provincial tax, fake-sale check, price-match cards.
- Refresh: `discovery.refresh_stale` daily per item (twice daily in sale mode), urgent items first, paced by `_within_budget` to the monthly SerpApi limit. On live sale days (`plan.live_day`: Black Friday, Cyber Monday, Boxing Day) `live_watch` refreshes items from 07:00 to 23:00 at the interval `plan.search_budget` says the month's limit allows (hourly when it fits), against the hard monthly limit only (`_under_limit`). The plan page shows that budget and has a Practice run (`POST /api/plan/practice`).
- Category searches (`deals.search_category`): next of the category's own words, Google Shopping on sale (SafeSearch off when `adult`), plain search fallback when nothing new, then `claude_deals.find` (web search) when thin and `claude_search` is on, at most daily. Provider wrappers must pass the words, not run_search's cache key.
- Deals: `services/deals.py` (today's drops, RFD threads, deal categories with Google Shopping "on sale" searches, deal score, sightings history, category forecasts, live-day hourly digest). Black Friday plan: `services/plan.py`, page `/plan`, setting `bf_plan` per user.

## Hard constraints (never break)
- No secrets in code or commits; keys come from `.env` or the Household admin page (Claude key, spend cap).
- Polite fetching: robots.txt, per-domain rate limits, honest User-Agent, back off on 403/429/503 (domain pauses after 3).
- Never bypass logins, CAPTCHAs, bot protection or paywalls.
- Never scrape Google result pages, CamelCamelCamel, Keepa web pages or Rakuten. Google data comes only through SerpApi.
- Claude spend is capped monthly (`claude.record_spend`, `budget_left`); SerpApi use is paced (`serp_monthly_limit`).
- The user's email and personal details stay private.

## Conventions
- Version lives in 6 places: `VERSION`, `backend/pyproject.toml`, `frontend/package.json`, `frontend/package-lock.json` (2 spots), README badge, `.env.example`. Add a CHANGELOG entry (Keep a Changelog, plain language) and update README Features.
- Schema changes need an Alembic migration (`backend/alembic/versions/00NN_*.py`, batch mode for SQLite) and a test in `test_migrations.py` still passing.
- New per-user setting: add to `settings_store.DEFAULTS` and `USER_KEYS`; write with `settings_store.update(db, {key: value}, user_id)` (there is no `set_value`).
- Alerts: `alerts.raise_alert(db, item=..., rule=..., key=..., title=..., body=..., url=..., user_id=...)`; the key dedupes.
- Claude calls: `messages.parse` with a Pydantic `output_format`, `claude.PRICE_MODEL`, then `record_spend(cost_usd(...))`.
- Work on a feature branch, draft PRs, never force-push. Canadian English, no em dashes in UI copy.

## Checks before a PR
```bash
cd backend && .venv/bin/pytest -q && .venv/bin/ruff check pricewatch tests
cd frontend && npx tsc --noEmit -p . && npm run build
```
Then a headless phone-size check of changed pages (Playwright, demo server with `PRICEWATCH_DATA_DIR` set).

## Deploy and update
- In-app: System, Updates (upgrade agent on the host, `scripts/upgrade-agent.sh --install`).
- By hand: `sudo ./update.sh` (latest tag), `--version X.Y.Z`, `--ref main`, `--rollback`, `--deploy-current`. Backs up the DB, waits for `/healthz`, rolls back on failure. Log `logs/update.log`.

## Troubleshooting
| Symptom | Cause and fix |
|---|---|
| `no such service: browser` on update | Old `update.sh` against a newer compose file; deploy with the target release's own `update.sh` (`--deploy-current`). |
| "List not found" on Home | Stale list id in localStorage; the app resets it when the list is gone. |
| A store shows 403 / blocked | Expected for bot-protected stores; set it to search results only. Do not add evasion. |
| Wrong generation matched | Check `matching.generation_conflict` / `UNIT_AFTER`; the next refresh drops wrong-generation stores. |
| No prices at all | `SERPAPI_KEY` missing or monthly limit reached (System, Health check). |
| AI features say a key is needed | Add the Claude key in Household admin; check the monthly cap. |
| Logs | `sudo docker logs --tail 100 pricewatch` |
