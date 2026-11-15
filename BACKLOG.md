# Backlog

Items not yet scheduled into a phase. Newest first.

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
