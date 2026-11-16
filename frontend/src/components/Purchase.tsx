import { useEffect, useState } from "react";
import { api, Item, money, toCents, toDollars } from "../api";

export interface PurchaseInfo {
  id: number;
  item_id: number;
  item_name: string | null;
  retailer_name: string;
  channel: string;
  price_cents: number;
  purchased_on: string;
  protection_basis: string | null;
  protection_until: string | null;
  days_left: number | null;
  badged: boolean;
  order_ref: string | null;
  status: string;
  lowest_seen_cents: number | null;
  claimable_cents: number | null;
  claimed_cents: number | null;
  proof_count: number;
  screenshots?: number;
  reference_cents?: number | null;
  saved_vs_median_cents?: number | null;
}

const today = () => new Date().toLocaleDateString("en-CA");

export function BoughtForm({ item, onDone, onCancel }: { item: Item; onDone: () => void; onCancel: () => void }) {
  const sources = (item.sources || []).filter((s) => s.status === "confirmed");
  const best = item.summary.best;
  const [sourceId, setSourceId] = useState<string>(best ? String(best.source_id) : sources[0] ? String(sources[0].id) : "");
  const src = sources.find((s) => String(s.id) === sourceId);
  const [price, setPrice] = useState(toDollars(src?.last_price_cents ?? best?.landed.price_cents));
  const [date, setDate] = useState(today());
  const [badged, setBadged] = useState(false);
  const [orderRef, setOrderRef] = useState("");
  const [days, setDays] = useState("");
  const [stop, setStop] = useState(true);
  const [terms, setTerms] = useState<{ days: number; until: string | null; basis: string | null } | null>(null);
  const [error, setError] = useState("");
  const isBestBuy = src?.retailer_name?.toLowerCase().includes("best buy");

  useEffect(() => {
    setPrice(toDollars(src?.last_price_cents ?? null) || price);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceId]);
  useEffect(() => {
    const q = new URLSearchParams({ purchased_on: date, badged: String(badged) });
    if (sourceId) q.set("source_id", sourceId);
    api<typeof terms>(`/api/items/${item.id}/protection-terms?${q}`).then(setTerms).catch(() => setTerms(null));
  }, [item.id, sourceId, date, badged]);

  const save = async () => {
    setError("");
    try {
      await api(`/api/items/${item.id}/purchases`, { method: "POST", json: {
        source_id: sourceId ? Number(sourceId) : null, price_cents: toCents(price), purchased_on: date, badged,
        order_ref: orderRef || null, protection_days: days ? Number(days) : null, stop_tracking: stop,
      } });
      onDone();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="space-y-2 rounded-lg bg-green-50 p-3 text-sm text-green-950 dark:bg-green-950 dark:text-green-50">
      <div className="font-semibold">Record your purchase</div>
      <div className="grid gap-2 sm:grid-cols-3">
        <select className="input" value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
          {sources.map((s) => <option key={s.id} value={s.id}>{s.retailer_name || s.title || s.url}</option>)}
        </select>
        <input className="input" inputMode="decimal" placeholder="Price paid (before tax)" value={price} onChange={(e) => setPrice(e.target.value)} />
        <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        <input className="input" placeholder="Order number (optional)" value={orderRef} onChange={(e) => setOrderRef(e.target.value)} />
        <input className="input" type="number" min={0} placeholder="Protection days (override)" value={days} onChange={(e) => setDays(e.target.value)} />
        {isBestBuy && (
          <label className="flex items-center gap-2"><input type="checkbox" checked={badged} onChange={(e) => setBadged(e.target.checked)} />
            Had the Black Friday Price Guarantee badge</label>
        )}
      </div>
      <div className="text-xs">
        {days ? `Protected for ${days} days (your entry).` : terms?.until
          ? `Protected until ${terms.until} (${terms.basis}). PriceWatch keeps checking and alerts you if the price drops.`
          : "No automatic price protection at this store. Enter days above if your receipt says otherwise."}
      </div>
      <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={stop} onChange={(e) => setStop(e.target.checked)} />
        Stop deal alerts for this item (protection checks continue)</label>
      <div className="flex gap-2">
        <button className="btn-primary px-3 py-1" onClick={save} disabled={!toCents(price) || !sourceId}>Save purchase</button>
        <button className="btn-ghost px-3 py-1" onClick={onCancel}>Cancel</button>
      </div>
      {!sources.length && <div className="text-xs">Add the store as a source (or log a manual price) first.</div>}
      {error && <div className="text-red-700">{error}</div>}
    </div>
  );
}

export function PurchaseCard({ p, onChange }: { p: PurchaseInfo; onChange: () => void }) {
  const colour = p.status === "claimable" ? "border-green-500" : p.status === "watching" ? "border-blue-400" : "";
  return (
    <div className={`card space-y-1 text-sm ${colour}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="font-semibold">{p.item_name}</div>
        <span className="text-xs uppercase tracking-wide text-slate-500">{p.status}</span>
      </div>
      <div>{p.retailer_name}{p.channel !== "online" ? ` (${p.channel})` : ""}: paid {money(p.price_cents)} on {p.purchased_on}
        {p.order_ref ? `, order ${p.order_ref}` : ""}</div>
      {p.saved_vs_median_cents ? (
        <div className="text-xs text-green-700 dark:text-green-400">Saved {money(p.saved_vs_median_cents)} against the 60-day typical price of {money(p.reference_cents)}</div>
      ) : null}
      {p.protection_until ? (
        <div className="text-xs text-slate-600 dark:text-slate-300">{p.protection_basis}; until {p.protection_until}
          {p.days_left != null && p.days_left >= 0 ? ` (${p.days_left} days left)` : ""}</div>
      ) : <div className="text-xs text-slate-500">No price protection recorded</div>}
      {p.claimable_cents != null && p.claimable_cents > 0 && p.status !== "claimed" && (
        <div className="font-semibold text-green-700">Lowest since: {money(p.lowest_seen_cents)}. Claim {money(p.claimable_cents)}.</div>
      )}
      {p.status === "claimed" && <div className="text-green-700">Claimed {money(p.claimed_cents)}</div>}
      <div className="flex flex-wrap gap-2 pt-1">
        {p.proof_count > 0 && <a className="btn-ghost px-2 py-1 text-xs" href={`/api/purchases/${p.id}/proof`}>Proof package ({p.proof_count}{p.screenshots ? `, ${p.screenshots} screenshot${p.screenshots > 1 ? "s" : ""}` : ""})</a>}
        {p.status === "claimable" && (
          <button className="btn-primary px-2 py-1 text-xs" onClick={() =>
            api(`/api/purchases/${p.id}`, { method: "PATCH", json: { status: "claimed", claimed_cents: p.claimable_cents } }).then(onChange)}>
            Mark claimed
          </button>
        )}
        <button className="btn-ghost px-2 py-1 text-xs text-red-600" onClick={() => confirm("Delete this purchase record?") &&
          api(`/api/purchases/${p.id}`, { method: "DELETE" }).then(onChange)}>Delete</button>
      </div>
    </div>
  );
}

interface ThreadSummary {
  posts: number;
  signals: Record<string, number>;
  lowest_quoted_cents: number | null;
  coupons: string[];
  verdict: string;
  vs_history?: string | null;
}

const SIGNAL_LABELS: Record<string, string> = {
  all_time_low: "say all-time low",
  wait: "say wait",
  price_match_ok: "price-matched OK",
  price_match_refused: "price match refused",
  out_of_stock: "out of stock",
  expired: "say it's over",
};

export function DealThreads({ itemId }: { itemId: number }) {
  const [deals, setDeals] = useState<{ title: string; url: string; price_cents: number | null; tracked_source_id: number | null; published_at: string | null; summary: ThreadSummary | null }[]>([]);
  useEffect(() => { api<typeof deals>(`/api/items/${itemId}/deals`).then(setDeals).catch(() => {}); }, [itemId]);
  if (!deals.length) return null;
  return (
    <div className="card space-y-2 text-sm">
      <h2 className="font-semibold">Community deals (RedFlagDeals)</h2>
      <p className="text-xs text-slate-500">Forum threads are hints; PriceWatch confirms prices on its own checks. Comment signals are counted by keyword, so treat them as a rough read of the room.</p>
      {deals.map((d) => (
        <div key={d.url} className="space-y-1 border-t border-slate-100 pt-2 first:border-0 first:pt-0 dark:border-slate-800">
          <a className="break-words hover:underline" href={d.url} target="_blank" rel="noreferrer">{d.title}</a>
          <span className="ml-2 text-xs text-slate-500">
            {d.published_at ? new Date(d.published_at).toLocaleDateString("en-CA") : ""}{d.tracked_source_id ? " · store already tracked" : ""}
          </span>
          {d.summary && d.summary.posts > 0 && (
            <div className="text-xs">
              <span className={`mr-2 rounded px-1.5 py-0.5 font-semibold ${d.summary.verdict === "crowd says good price" ? "bg-green-100 text-green-900" : d.summary.verdict === "crowd says wait" ? "bg-amber-100 text-amber-900" : d.summary.verdict === "likely over" ? "bg-slate-200 text-slate-700" : "bg-slate-100 text-slate-700"}`}>
                {d.summary.verdict}
              </span>
              <span className="text-slate-600 dark:text-slate-300">
                {d.summary.posts} posts
                {Object.entries(d.summary.signals).filter(([, n]) => n > 0).map(([k, n]) => ` · ${n} ${SIGNAL_LABELS[k] || k}`).join("")}
                {d.summary.lowest_quoted_cents ? ` · lowest quoted ${money(d.summary.lowest_quoted_cents)}` : ""}
                {d.summary.coupons.length ? ` · codes: ${d.summary.coupons.join(", ")}` : ""}
              </span>
              {d.summary.vs_history && <div className="mt-1 text-amber-700 dark:text-amber-400">{d.summary.vs_history}</div>}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export function FlyerMatches({ itemId }: { itemId: number }) {
  const [rows, setRows] = useState<{ id: number; merchant: string; title: string; price_cents: number | null; valid_to: string | null; url: string | null; current: boolean }[]>([]);
  useEffect(() => { api<typeof rows>(`/api/items/${itemId}/flyers`).then(setRows).catch(() => {}); }, [itemId]);
  const current = rows.filter((r) => r.current);
  if (!current.length) return null;
  return (
    <div className="card space-y-1 text-sm">
      <h2 className="font-semibold">In this week's flyers</h2>
      <p className="text-xs text-slate-500">Flyer prices are often in-store or regional. They are hints and do not count as price history.</p>
      {current.map((r) => (
        <div key={r.id} className="flex flex-wrap items-baseline justify-between gap-x-3">
          <span className="min-w-0">
            <span className="font-medium">{r.merchant}</span>: {r.url ? <a className="hover:underline" href={r.url} target="_blank" rel="noreferrer">{r.title}</a> : r.title}
          </span>
          <span>{money(r.price_cents)}{r.valid_to ? <span className="text-xs text-slate-500"> until {new Date(r.valid_to).toLocaleDateString("en-CA", { month: "short", day: "numeric" })}</span> : null}</span>
        </div>
      ))}
    </div>
  );
}

export function Forecast({ itemId }: { itemId: number }) {
  const [f, setF] = useState<{ chance: "low" | "medium" | "high" | null; likely_low_cents: number | null; reasons: string[]; note: string } | null>(null);
  useEffect(() => { api<typeof f>(`/api/items/${itemId}/forecast`).then(setF).catch(() => {}); }, [itemId]);
  if (!f) return null;
  const tone = f.chance === "high" ? "text-amber-700 dark:text-amber-400" : f.chance === "low" ? "text-green-700 dark:text-green-400" : "";
  return (
    <div className="card space-y-1 text-sm">
      <h2 className="font-semibold">Will it get cheaper?</h2>
      {f.chance ? (
        <div className={`font-medium ${tone}`}>
          Chance of a lower price soon: {f.chance}{f.likely_low_cents ? `, likely around ${money(f.likely_low_cents)} before tax` : ""}
        </div>
      ) : null}
      <ul className="list-disc pl-5 text-slate-600 dark:text-slate-300">{f.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
      <p className="text-xs text-slate-500">{f.note}</p>
    </div>
  );
}
