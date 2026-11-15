# Backlog

Items not yet scheduled into a phase. Newest first.

## v0.4.0 (target Nov 22 to 25, from the 2026-11-15 delta review)

1. Purchases and price-protection tracker: per purchase store retailer, price, date, channel; keep watching and
   alert when a claimable drop occurs (Costco 30 days; Best Buy event guarantee on badged items; Staples 30/14 days
   excluding event pricing). Highest value; ship by Nov 22 so early buys are protected.
2. Proof package: full-page screenshot, URL, UTC and local timestamps, parsed price, seller, page hash, zipped.
3. RedFlagDeals Hot Deals feed (see below; the review asks for the feed matcher by Nov 20).
4. Gift lists per person and occasion with budget caps and spent vs remaining.
5. Cash-back and gift card stacking notes per retailer (manual table; do not scrape Rakuten).
6. Retailer JSON adapters (Best Buy province pricing, Canadian Tire / Sport Chek store pricing) once fixtures are
   captured on TrueNAS; Costco and Walmart browser adapters with channel labels.

## Phase 4 (after Cyber Monday)

LLM match confirmation (Claude, Haiku-class, fuzzy 80 to 94 only, cached, user confirms), barcode scan,
email-forward ingestion, Home Assistant sensors, weekly report with a Claude summary, Boxing Week mode
(Dec 26 to 31), basket optimiser for free-shipping thresholds. Re-read Visualping's 2026 results (published
Nov 27) and adjust the buy thresholds.

## RedFlagDeals intelligence (requested 2026-11-15, target: Phase 3, v0.3.0)

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
