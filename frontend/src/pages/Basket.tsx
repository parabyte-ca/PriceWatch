import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, Item, money } from "../api";
import Badge from "../components/Badge";
import { useSession } from "../session";

interface StorePlan {
  retailer: string;
  domain: string | null;
  items: { item_id: number; name: string; price_cents: number; url: string }[];
  subtotal_cents: number;
  shipping_cents: number;
  shipping_known: boolean;
  tax_cents: number;
  total_cents: number;
  after_perks_cents: number;
  perks: { label: string }[];
  free_shipping_threshold_cents: number | null;
  free_shipping_gap_cents: number;
}
interface Plan {
  stores: StorePlan[];
  total_cents: number;
  separately_cents: number;
  saving_cents: number;
  missing: { item_id: number; name: string }[];
  tips: string[];
  method: string;
  use_perks: boolean;
  unknown_shipping: boolean;
}

export default function Basket() {
  const { lists } = useSession();
  const [items, setItems] = useState<Item[]>([]);
  const [listId, setListId] = useState<string>("");
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [perks, setPerks] = useState(true);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Item[]>("/api/items").then((rows) => {
      setItems(rows);
      // start with what the buy rule says to buy now
      setPicked(new Set(rows.filter((i) => i.summary.decision === "BUY" || i.summary.decision === "BUY_AND_PROTECT").map((i) => i.id)));
    }).catch((e) => setError(e.message));
  }, []);

  const shown = items.filter((i) => !listId || String(i.list_id) === listId);
  const toggle = (id: number) => {
    const next = new Set(picked);
    if (next.has(id)) next.delete(id); else next.add(id);
    setPicked(next);
  };
  const run = () => {
    setError("");
    const ids = shown.filter((i) => picked.has(i.id)).map((i) => i.id);
    if (!ids.length) return setError("Pick at least one item");
    api<Plan>("/api/basket", { method: "POST", json: { item_ids: ids, use_perks: perks } }).then(setPlan).catch((e) => setError(e.message));
  };

  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <p className="text-sm text-slate-500">
          Pick what you plan to buy. PriceWatch finds the cheapest way to split it across stores, counting free-shipping
          thresholds, tax{perks ? " and your perks" : ""}. Items marked BUY are picked to start.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          {lists.length > 1 && (
            <select className="input w-auto" value={listId} onChange={(e) => setListId(e.target.value)}>
              <option value="">All lists</option>
              {lists.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
            </select>
          )}
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={perks} onChange={(e) => setPerks(e.target.checked)} /> count perks</label>
          <button className="btn-ghost text-sm" onClick={() => setPicked(new Set(shown.map((i) => i.id)))}>All</button>
          <button className="btn-ghost text-sm" onClick={() => setPicked(new Set())}>None</button>
        </div>
        <div className="grid gap-1 sm:grid-cols-2">
          {shown.map((i) => (
            <label key={i.id} className="flex min-w-0 items-center gap-2 text-sm">
              <input type="checkbox" checked={picked.has(i.id)} onChange={() => toggle(i.id)} />
              <span className="min-w-0 truncate">{i.name}</span>
              <Badge value={i.summary.badge} />
            </label>
          ))}
        </div>
        <button className="btn-primary" onClick={run}>Plan my basket</button>
        {error && <p className="text-sm text-red-600">{error}</p>}
      </div>

      {plan && (
        <div className="space-y-3">
          <div className="card grid grid-cols-2 gap-3 sm:grid-cols-3">
            <div className="min-w-0"><div className="text-xs uppercase text-slate-500">Basket total</div><div className="truncate text-2xl font-bold">{money(plan.total_cents)}</div></div>
            <div className="min-w-0"><div className="text-xs uppercase text-slate-500">Bought one by one</div><div className="truncate text-lg">{money(plan.separately_cents)}</div></div>
            <div className="min-w-0"><div className="text-xs uppercase text-slate-500">You save</div><div className="truncate text-lg font-semibold text-green-700 dark:text-green-400">{money(plan.saving_cents)}</div></div>
          </div>
          {plan.tips.map((t) => <div key={t} className="rounded-lg bg-blue-50 p-2 text-sm text-blue-900 dark:bg-blue-950 dark:text-blue-100">{t}</div>)}
          {plan.stores.map((s) => (
            <div key={s.retailer} className="card space-y-1 text-sm">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="font-semibold">{s.retailer}</h2>
                <span className="font-semibold">{money(plan.use_perks ? s.after_perks_cents : s.total_cents)}</span>
              </div>
              {s.items.map((it) => (
                <div key={it.item_id} className="flex justify-between gap-2">
                  <a className="min-w-0 truncate hover:underline" href={it.url} target="_blank" rel="noreferrer">{it.name}</a>
                  <span>{money(it.price_cents)}</span>
                </div>
              ))}
              <div className="text-xs text-slate-500">
                Subtotal {money(s.subtotal_cents)} · shipping {s.shipping_cents ? money(s.shipping_cents) : "free"}{!s.shipping_known && " (unknown for some items)"} · tax {money(s.tax_cents)}
                {s.perks.length > 0 && plan.use_perks && ` · after ${s.perks.map((p) => p.label).join(" + ")}`}
              </div>
            </div>
          ))}
          {plan.missing.length > 0 && (
            <div className="card text-sm">
              No online price in stock for: {plan.missing.map((m, n) => <span key={m.item_id}>{n > 0 && ", "}<Link className="hover:underline" to={`/items/${m.item_id}`}>{m.name}</Link></span>)}
            </div>
          )}
          <p className="text-xs text-slate-500">
            Uses each store's last checked price, online orders only. Shipping comes from the store's free-shipping threshold and
            flat rate (set them on the System page) or the listing itself. {plan.method === "local search" && "Large basket: best split found by search, not every combination."}
          </p>
        </div>
      )}
    </div>
  );
}
