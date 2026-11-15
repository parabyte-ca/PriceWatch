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
      {p.protection_until ? (
        <div className="text-xs text-slate-600 dark:text-slate-300">{p.protection_basis}; until {p.protection_until}
          {p.days_left != null && p.days_left >= 0 ? ` (${p.days_left} days left)` : ""}</div>
      ) : <div className="text-xs text-slate-500">No price protection recorded</div>}
      {p.claimable_cents != null && p.claimable_cents > 0 && p.status !== "claimed" && (
        <div className="font-semibold text-green-700">Lowest since: {money(p.lowest_seen_cents)}. Claim {money(p.claimable_cents)}.</div>
      )}
      {p.status === "claimed" && <div className="text-green-700">Claimed {money(p.claimed_cents)}</div>}
      <div className="flex flex-wrap gap-2 pt-1">
        {p.proof_count > 0 && <a className="btn-ghost px-2 py-1 text-xs" href={`/api/purchases/${p.id}/proof`}>Proof package ({p.proof_count})</a>}
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

export function DealThreads({ itemId }: { itemId: number }) {
  const [deals, setDeals] = useState<{ title: string; url: string; price_cents: number | null; tracked_source_id: number | null; published_at: string | null }[]>([]);
  useEffect(() => { api<typeof deals>(`/api/items/${itemId}/deals`).then(setDeals).catch(() => {}); }, [itemId]);
  if (!deals.length) return null;
  return (
    <div className="card space-y-1 text-sm">
      <h2 className="font-semibold">Community deals (RedFlagDeals)</h2>
      <p className="text-xs text-slate-500">Forum threads are hints; PriceWatch confirms prices on its own checks.</p>
      {deals.map((d) => (
        <div key={d.url}>
          <a className="hover:underline" href={d.url} target="_blank" rel="noreferrer">{d.title}</a>
          <span className="ml-2 text-xs text-slate-500">
            {d.published_at ? new Date(d.published_at).toLocaleDateString("en-CA") : ""}{d.tracked_source_id ? " · store already tracked" : ""}
          </span>
        </div>
      ))}
    </div>
  );
}
