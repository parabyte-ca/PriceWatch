export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, ...rest } = init;
  const res = await fetch(path, {
    credentials: "same-origin",
    ...rest,
    headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...(rest.headers || {}) },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (res.status === 401 && !path.startsWith("/api/auth/")) {
    window.dispatchEvent(new Event("pricewatch:unauthorized"));
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, msg);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const money = (cents: number | null | undefined) =>
  cents === null || cents === undefined
    ? "n/a"
    : (cents / 100).toLocaleString("en-CA", { style: "currency", currency: "CAD" });

export const toCents = (dollars: string): number | null => {
  const clean = dollars.replace(/[^0-9.]/g, "");
  if (!clean) return null;
  const n = Number(clean);
  return Number.isFinite(n) ? Math.round(n * 100) : null;
};

export const toDollars = (cents: number | null | undefined) => (cents == null ? "" : (cents / 100).toFixed(2));

export function ago(iso: string | null | undefined): string {
  if (!iso) return "never";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  const s = Math.abs(diff);
  let text: string;
  if (s < 90) return "just now";
  if (s < 3600) text = `${Math.round(s / 60)} min`;
  else if (s < 86400 * 2) text = `${Math.round(s / 3600)} h`;
  else text = `${Math.round(s / 86400)} days`;
  return diff >= 0 ? `${text} ago` : `in ${text}`;
}

export const localTime = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString("en-CA", { dateStyle: "medium", timeStyle: "short" }) : "n/a";

export interface Landed {
  price_cents: number;
  shipping_cents: number | null;
  shipping_known: boolean;
  tax_cents: number;
  landed_cents: number;
}

export interface Source {
  id: number;
  item_id: number;
  url: string;
  title: string | null;
  status: string;
  match_confidence: number | null;
  match_method: string | null;
  match_reasons: { reasons?: string[]; exclusions?: string[]; serp_price_cents?: number | null; merchant?: string | null } | null;
  discovered_via: string | null;
  fetch_mode: string | null;
  channel: string;
  external_id: string | null;
  last_condition: string | null;
  last_seller_type: string | null;
  retailer_name: string | null;
  price_match: boolean;
  last_price_cents: number | null;
  last_was_price_cents: number | null;
  last_shipping_cents: number | null;
  last_in_stock: boolean | null;
  last_checked_at: string | null;
  last_error: string | null;
  consecutive_failures: number;
  next_check_at: string | null;
  landed: Landed | null;
  last_method?: string | null;
}

export interface PriceMatch {
  at: string;
  at_source_id: number;
  match_to: string;
  match_url: string;
  price_cents: number;
  saving_cents: number;
  caveats: string[];
  policy_notes: string | null;
}

export interface MarketBest { merchant: string; price_cents: number; shipping_cents: number | null; url: string; store_link: boolean; title: string }
export interface Offer { merchant: string; title: string; price_cents: number; shipping_cents: number | null; url: string;
  store_link: boolean; provider: string; confidence: number | null; seen_at: string; tracked: string | null;
  kind: string; domain: string | null; local?: string | null; image?: string | null }

export interface Summary {
  market?: { best: MarketBest | null; stores: number; seen_at: string } | null;
  best: { source_id: number; url: string; retailer: string | null; domain: string | null; landed: Landed;
    was_price_cents: number | null; channel: string;
    after_perks_cents?: number; perks_saving_cents?: number; perks?: { label: string; percent: number | null; kind: string }[] } | null;
  seasonal_low_cents: number | null;
  distance_to_low_pct: number | null;
  history_confidence: "LOW" | "MEDIUM" | "HIGH";
  history_days: number;
  median_60_cents: number | null;
  decision: "BUY" | "BUY_AND_PROTECT" | "WAIT" | "NO_DATA";
  decision_reason: string;
  protection: string | null;
  price_match: PriceMatch[];
  stale: boolean;
  snoozed: boolean;
  best_price_cents: number | null;
  best_landed_cents: number | null;
  compare_cents: number | null;
  low_30_cents: number | null;
  low_60_cents: number | null;
  low_90_cents: number | null;
  all_time_low_cents: number | null;
  at_all_time_low: boolean;
  real_discount_pct: number | null;
  fake_sale: boolean;
  fake_sale_reasons: string[];
  badge: string;
  last_checked_at: string | null;
  source_count: number;
  suggested_count: number;
}

export interface Item {
  claimed_by?: string | null;
  claimed_by_me?: boolean;
  can_claim?: boolean;
  id: number;
  name: string;
  brand: string | null;
  model: string | null;
  gtin: string | null;
  category: string | null;
  image_url: string | null;
  target_price_cents: number | null;
  max_price_cents: number | null;
  notes: string | null;
  priority: number;
  deadline: string | null;
  hot: boolean;
  active: boolean;
  amazon_history_note: string | null;
  search_query: string | null;
  search_terms?: string | null;
  list_id: number | null;
  added_by: number | null;
  exclude_refurbished: boolean;
  exclude_open_box: boolean;
  exclude_used: boolean;
  exclude_marketplace: boolean;
  exclude_bundles: boolean;
  exclude_variants: boolean;
  summary: Summary;
  sources: Source[] | null;
}

export interface DiscoveryCandidate {
  title: string;
  url: string;
  merchant: string | null;
  price_cents: number | null;
  confidence: number;
  method: string;
  accepted: boolean;
  reasons: string[];
  exclusions: string[];
  status: string;
}

export interface DiscoveryResult {
  provider: string;
  query: string;
  cached: boolean;
  added: number;
  usage: number;
  limit: number;
  candidates: DiscoveryCandidate[];
  notes?: string[];
}

export const EXCLUSIONS = [
  ["exclude_refurbished", "Refurbished"],
  ["exclude_open_box", "Open box"],
  ["exclude_used", "Used"],
  ["exclude_marketplace", "Marketplace sellers"],
  ["exclude_bundles", "Bundles"],
  ["exclude_variants", "Other colours, sizes, storage"],
] as const;
