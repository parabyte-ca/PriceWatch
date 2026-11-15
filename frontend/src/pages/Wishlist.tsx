import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ago, api, Item, money } from "../api";
import Badge from "../components/Badge";

type SortKey = "closest" | "priority" | "name" | "discount";

const closeness = (i: Item) =>
  i.target_price_cents && i.summary.compare_cents ? i.summary.compare_cents / i.target_price_cents : Number.POSITIVE_INFINITY;

export default function Wishlist() {
  const [items, setItems] = useState<Item[] | null>(null);
  const [error, setError] = useState("");
  const [sort, setSort] = useState<SortKey>(() => (localStorage.getItem("pw-sort") as SortKey) || "closest");
  const [query, setQuery] = useState("");

  const load = () => api<Item[]>("/api/items").then(setItems).catch((e) => setError(e.message));
  useEffect(() => {
    load();
    const t = setInterval(load, 60_000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    try {
      localStorage.setItem("pw-sort", sort);
    } catch {
      /* storage unavailable */
    }
  }, [sort]);

  const rows = useMemo(() => {
    const list = (items || []).filter((i) => i.name.toLowerCase().includes(query.toLowerCase()));
    const cmp: Record<SortKey, (a: Item, b: Item) => number> = {
      closest: (a, b) => closeness(a) - closeness(b) || a.priority - b.priority,
      priority: (a, b) => a.priority - b.priority || a.name.localeCompare(b.name),
      name: (a, b) => a.name.localeCompare(b.name),
      discount: (a, b) => (b.summary.real_discount_pct ?? -999) - (a.summary.real_discount_pct ?? -999),
    };
    return [...list].sort(cmp[sort]);
  }, [items, sort, query]);

  if (error) return <div className="card text-red-600">{error}</div>;
  if (!items) return <div className="text-slate-500">Loading...</div>;
  if (!items.length)
    return (
      <div className="card text-center">
        <p className="mb-3">Your wishlist is empty.</p>
        <Link to="/add" className="btn-primary">Add your first item</Link>
      </div>
    );

  const buyNow = items.filter((i) => i.summary.badge === "BUY NOW").length;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <input className="input max-w-xs" placeholder="Search" value={query} onChange={(e) => setQuery(e.target.value)} />
        <select className="input w-auto" value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
          <option value="closest">Closest to buying</option>
          <option value="priority">Priority</option>
          <option value="discount">Real discount</option>
          <option value="name">Name</option>
        </select>
        <span className="ml-auto text-sm text-slate-500">
          {items.length} items{buyNow ? `, ${buyNow} at target` : ""}
        </span>
      </div>

      {/* desktop table */}
      <div className="card hidden overflow-x-auto p-0 md:block">
        <table className="w-full">
          <thead className="border-b border-slate-200 dark:border-slate-800">
            <tr>
              <th className="th">Item</th>
              <th className="th text-right">Best landed</th>
              <th className="th text-right">Target</th>
              <th className="th text-right">30-day low</th>
              <th className="th">Status</th>
              <th className="th">Checked</th>
              <th className="th text-right">Sources</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((i) => (
              <tr key={i.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50">
                <td className="td">
                  <Link to={`/items/${i.id}`} className="font-medium hover:underline">
                    {i.hot && <span title="Hot: checked hourly">🔥 </span>}
                    {i.name}
                  </Link>
                  <div className="text-xs text-slate-500">
                    {i.summary.best?.retailer || ""}
                    {i.summary.at_all_time_low && <span className="ml-1 font-semibold text-green-700">lowest seen</span>}
                  </div>
                </td>
                <td className="td text-right font-semibold">
                  {money(i.summary.best_landed_cents)}
                  <div className="text-xs font-normal text-slate-500">{money(i.summary.best_price_cents)} before tax</div>
                </td>
                <td className="td text-right">{money(i.target_price_cents)}</td>
                <td className="td text-right">{money(i.summary.low_30_cents)}</td>
                <td className="td"><Badge value={i.summary.badge} /></td>
                <td className="td whitespace-nowrap text-slate-500">{ago(i.summary.last_checked_at)}</td>
                <td className="td text-right">{i.summary.source_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* mobile cards */}
      <div className="space-y-2 md:hidden">
        {rows.map((i) => (
          <Link key={i.id} to={`/items/${i.id}`} className="card block">
            <div className="flex items-start justify-between gap-2">
              <div className="font-medium">{i.hot && "🔥 "}{i.name}</div>
              <Badge value={i.summary.badge} />
            </div>
            <div className="mt-2 grid grid-cols-3 gap-2 text-sm">
              <div><div className="label">Best</div>{money(i.summary.best_landed_cents)}</div>
              <div><div className="label">Target</div>{money(i.target_price_cents)}</div>
              <div><div className="label">30-day low</div>{money(i.summary.low_30_cents)}</div>
            </div>
            <div className="mt-1 text-xs text-slate-500">
              {i.summary.best?.retailer || "No price yet"} · checked {ago(i.summary.last_checked_at)} · {i.summary.source_count} sources
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
