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
  fetch_mode: string | null;
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
}

export interface Summary {
  best: { source_id: number; url: string; retailer: string | null; landed: Landed; was_price_cents: number | null } | null;
  best_price_cents: number | null;
  best_landed_cents: number | null;
  compare_cents: number | null;
  low_30_cents: number | null;
  low_60_cents: number | null;
  low_90_cents: number | null;
  all_time_low_cents: number | null;
  at_all_time_low: boolean;
  median_30_cents: number | null;
  real_discount_pct: number | null;
  fake_sale: boolean;
  fake_sale_reasons: string[];
  badge: string;
  last_checked_at: string | null;
  source_count: number;
  suggested_count: number;
}

export interface Item {
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
  summary: Summary;
  sources: Source[] | null;
}
