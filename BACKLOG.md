# Backlog

Items not yet scheduled into a phase. Newest first.

## Household accounts and shared lists (requested 2026-11-15) - DONE in v0.4.0

1. **Separate identities.** Each person (you and your wife) gets their own login, wishlist, targets, alert rules,
   notification URLs, quiet hours and snoozes. Replaces the single admin password: `users` table (name, password
   hash with argon2 or bcrypt, per-user API token, role admin/member), `items.owner_id`, per-user settings rows.
   Retailers, price policies, observations and fetching stay shared, so one product is fetched once even if both
   of you track it.
2. **Shared lists by invite.** Lists become first-class (`lists`, `list_members` with role owner/editor/viewer).
   The owner creates a short, single-use "friend code" (e.g. `PW-7K3Q-9XMD`, expires in 7 days, stored hashed);
   the other person enters it under Settings to join. Shared items show who added them; each member keeps their
   own alert preferences for shared items. Leaving or revoking removes access without deleting history.
- Migration: existing data moves to the first admin user and a default "My list"; back up first (update.sh does).
- Fits the gift-lists item in v0.4 (per person, per occasion, budgets): build lists once for both.
- Security: per-user sessions, rate-limited code redemption, codes never logged, admin can reset a member's password.

## v0.4.0 (target Nov 22 to 25, from the 2026-11-15 delta review)

1. DONE in v0.5.0. Purchases and price-protection tracker: per purchase store retailer, price, date, channel; keep watching and
   alert when a claimable drop occurs (Costco 30 days; Best Buy event guarantee on badged items; Staples 30/14 days
   excluding event pricing). Highest value; ship by Nov 22 so early buys are protected.
2. DONE in v0.5.0; screenshot added in v0.7.0. Proof package: full-page screenshot, URL, UTC and local timestamps, parsed price, seller, page hash, zipped.
3. DONE in v0.5.0 (feed matching and de-duplication); comment summary DONE in v0.7.0.
4. DONE in v0.7.0. Gift lists per person and occasion with budget caps and spent vs remaining.
5. DONE in v0.7.0. Cash-back and gift card stacking notes per retailer (manual table; do not scrape Rakuten).
6. PARTLY DONE in v0.7.0 (Best Buy product JSON beta, Canadian Tire browser default, page test tool with fixture capture). Still to do: run the page test on TrueNAS against real pages and add parsers from the fixtures. Retailer JSON adapters (Best Buy province pricing, Canadian Tire / Sport Chek store pricing) once fixtures are
   captured on TrueNAS; Costco and Walmart browser adapters with channel labels.

## Feature ideas (2026-11-16)

Done in v0.7.0: Web Push, spend and savings dashboard, weekly flyer matching. Done in v0.8.0: Black Friday
hardening (readiness, load dry run, pre-event backup, stale flags), basket optimiser, Boxing Week mode, Claude Haiku
match check (discovery only). Done in v0.9.0: Home Assistant sensors, barcode scan
to add, Claude check for the deal feed and flyers. Still open: price-drop forecasting, weekly report with a Claude
summary, email-forward ingestion.

## Phase 4 (after Cyber Monday)

LLM match confirmation DONE in v0.8.0 (discovery). Barcode scan,
email-forward ingestion, Home Assistant sensors, weekly report with a Claude summary. (Boxing Week mode and the
basket optimiser DONE in v0.8.0.) Re-read Visualping's 2026 results (published
Nov 27) and adjust the buy thresholds.

## RedFlagDeals intelligence (requested 2026-11-15) - DONE in v0.5.0 and v0.7.0 (rule-based; optional LLM summary not built)

Read redflagdeals.com Hot Deals threads and use them as hints and crowd context,
never as price truth.

- **Ingest:** Hot Deals forum RSS feed (and per-thread pages, politely rate
  limited, robots.txt respected, no login). Store in `deal_feed_entries` plus a
  new `deal_feed_comments` table (thread id, post id, posted at, votes, text
  hash, extracted signals; no usernames stored).
- **Correlate and de-duplicate:** match a thread to a wishlist item (GTIN/MPN
  in the title or linked URL, then fuzzy title match). Resolve the thread's
  outbound retailer link to an existing `source_link` by normalised URL and
  retailer domain, so a deal already tracked from Best Buy, Amazon or a SERP
  result is shown once, with the RFD thread attached, not as a second listing.
  Several threads about the same deal collapse into one entry.
- **Aggregate comments into a confidence summary** per thread:
  - claims of "all-time low" / "ATL" / "lowest ever" and any price quoted with it;
  - "wait" signals (e.g. "was cheaper last year", "Boxing Day will be lower",
    "price match at X");
  - reported price-match successes and failures, out-of-stock reports, coupon
    codes, expiry;
  - thread votes and reply count as a weight.
  Rule-based extraction first (keyword patterns plus price regex); optional
  Claude API summary behind the existing LLM flag, cached per thread version.
- **Cross-check with our own history:** show the crowd verdict next to our
  observed 30/60/90-day and all-time lows, and highlight disagreement (e.g.
  "RFD says ATL, our data saw $20 lower on Nov 3").
- **UI:** item detail "Community" panel with the summary, top quoted prices,
  thread link; badge hint on the wishlist row; alert on a new matched thread.
- **Tests:** saved RSS and thread fixtures (personal data removed), matching
  positive/negative cases, de-duplication against existing sources, signal
  extraction cases.
