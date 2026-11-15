import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ago, api, Item, localTime, money, toCents, toDollars } from "../api";
import Badge from "../components/Badge";

interface Series {
  source_id: number;
  name: string;
  points: { t: string; price_cents: number | null; in_stock: boolean | null }[];
}

const COLOURS = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#65a30d"];

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div>
      <div className="label">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
      {note && <div className="text-xs text-slate-500">{note}</div>}
    </div>
  );
}

export default function ItemDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [item, setItem] = useState<Item | null>(null);
  const [series, setSeries] = useState<Series[]>([]);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [form, setForm] = useState({ target: "", max: "", hot: false, priority: 3, notes: "", amazon: "" });
  const [newUrl, setNewUrl] = useState("");
  const [manual, setManual] = useState({ store: "", price: "", shipping: "" });

  const load = useCallback(async () => {
    try {
      const [it, h] = await Promise.all([
        api<Item>(`/api/items/${id}`),
        api<{ series: Series[] }>(`/api/items/${id}/history?days=120`),
      ]);
      setItem(it);
      setSeries(h.series);
      setForm({
        target: toDollars(it.target_price_cents), max: toDollars(it.max_price_cents), hot: it.hot,
        priority: it.priority, notes: it.notes || "", amazon: it.amazon_history_note || "",
      });
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const chartData = useMemo(() => {
    const rows = new Map<number, Record<string, number | null>>();
    for (const s of series)
      for (const p of s.points) {
        const t = new Date(p.t).getTime();
        const row = rows.get(t) || { t };
        row[s.name] = p.price_cents == null ? null : p.price_cents / 100;
        rows.set(t, row);
      }
    return [...rows.values()].sort((a, b) => (a.t as number) - (b.t as number));
  }, [series]);

  const flash = (m: string) => {
    setMsg(m);
    setTimeout(() => setMsg(""), 4000);
  };

  const run = async (fn: () => Promise<unknown>, okMsg?: string) => {
    setError("");
    try {
      await fn();
      if (okMsg) flash(okMsg);
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const saveEdits = (e: FormEvent) => {
    e.preventDefault();
    run(() => api(`/api/items/${id}`, { method: "PATCH", json: {
      target_price_cents: toCents(form.target), max_price_cents: toCents(form.max), hot: form.hot,
      priority: form.priority, notes: form.notes || null, amazon_history_note: form.amazon || null,
    } }), "Saved");
  };

  if (error && !item) return <div className="card text-red-600">{error}</div>;
  if (!item) return <div className="text-slate-500">Loading...</div>;
  const s = item.summary;
  const amazon = item.sources?.find((x) => x.url.includes("amazon.ca"));
  const asin = amazon?.url.match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})/)?.[1];

  return (
    <div className="space-y-4">
      <Link to="/" className="text-sm text-slate-500 hover:underline">← Wishlist</Link>
      <div className="card flex flex-col gap-4 md:flex-row">
        {item.image_url && <img src={item.image_url} alt="" className="h-32 w-32 self-center rounded object-contain" />}
        <div className="flex-1 space-y-3">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h1 className="text-xl font-bold">{item.name}</h1>
              <div className="text-sm text-slate-500">{[item.brand, item.model, item.gtin].filter(Boolean).join(" · ")}</div>
            </div>
            <Badge value={s.badge} />
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Best landed" value={money(s.best_landed_cents)}
              note={s.best ? `${money(s.best.landed.price_cents)} + ${s.best.landed.shipping_known ? money(s.best.landed.shipping_cents) + " ship" : "shipping unknown"} + ${money(s.best.landed.tax_cents)} tax, ${s.best.retailer}` : undefined} />
            <Stat label="Target" value={money(item.target_price_cents)} />
            <Stat label="30 / 60 / 90-day low" value={money(s.low_30_cents)} note={`${money(s.low_60_cents)} / ${money(s.low_90_cents)}`} />
            <Stat label="All-time low (ours)" value={money(s.all_time_low_cents)}
              note={s.real_discount_pct != null ? `Real discount vs 30-day median: ${s.real_discount_pct}%` : "Building history"} />
          </div>
          {s.fake_sale && (
            <div className="rounded-lg bg-amber-100 p-2 text-sm text-amber-900">
              Fake sale warning: {s.fake_sale_reasons.join("; ")}.
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <button className="btn-ghost" onClick={() => run(() => api(`/api/items/${id}/check`, { method: "POST" }), "Checks queued; refresh in a minute")}>
              Check all now
            </button>
            {asin && (
              <>
                <a className="btn-ghost" href={`https://keepa.com/#!product/6-${asin}`} target="_blank" rel="noreferrer">Keepa</a>
                <a className="btn-ghost" href={`https://ca.camelcamelcamel.com/product/${asin}`} target="_blank" rel="noreferrer">CamelCamelCamel</a>
              </>
            )}
            <button className="btn-ghost ml-auto text-red-600"
              onClick={() => confirm(`Delete "${item.name}" and all its price history?`) &&
                api(`/api/items/${id}`, { method: "DELETE" }).then(() => nav("/"))}>
              Delete item
            </button>
          </div>
          {msg && <p className="text-sm text-green-700">{msg}</p>}
          {error && <p className="text-sm text-red-600">{error}</p>}
        </div>
      </div>

      <div className="card">
        <h2 className="mb-2 font-semibold">Price history (before tax)</h2>
        {chartData.length ? (
          <div className="h-72">
            <ResponsiveContainer>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]}
                  tickFormatter={(t) => new Date(t).toLocaleDateString("en-CA", { month: "short", day: "numeric" })} />
                <YAxis tickFormatter={(v) => `$${v}`} width={60} domain={["auto", "auto"]} />
                <Tooltip labelFormatter={(t) => new Date(t as number).toLocaleString("en-CA")}
                  formatter={(v: number) => `$${v.toFixed(2)}`} />
                <Legend />
                {item.target_price_cents != null && (
                  <ReferenceLine y={item.target_price_cents / 100} stroke="#16a34a" strokeDasharray="6 4" label="Target" />
                )}
                {series.map((sr, idx) => (
                  <Line key={sr.source_id} dataKey={sr.name} type="stepAfter" connectNulls dot={false}
                    stroke={COLOURS[idx % COLOURS.length]} strokeWidth={2} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="text-sm text-slate-500">No observations yet.</p>
        )}
      </div>

      <div className="card overflow-x-auto">
        <h2 className="mb-2 font-semibold">Sources</h2>
        <table className="w-full">
          <thead>
            <tr>
              <th className="th">Retailer</th>
              <th className="th text-right">Price</th>
              <th className="th text-right">Landed</th>
              <th className="th">Stock</th>
              <th className="th">Checked</th>
              <th className="th">Status</th>
              <th className="th"></th>
            </tr>
          </thead>
          <tbody>
            {item.sources?.map((src) => (
              <tr key={src.id} className="border-t border-slate-100 dark:border-slate-800">
                <td className="td">
                  {src.url.startsWith("manual://") ? (
                    <span>{src.title} <span className="text-xs text-slate-500">(manual)</span></span>
                  ) : (
                    <a href={src.url} target="_blank" rel="noreferrer" className="hover:underline">{src.retailer_name || src.url}</a>
                  )}
                  {src.price_match && <span className="ml-1 text-xs text-blue-600" title="Retailer has a price-match policy">PM</span>}
                  {src.last_error && <div className="text-xs text-red-600">{src.last_error}</div>}
                </td>
                <td className="td text-right">
                  {money(src.last_price_cents)}
                  {src.last_was_price_cents && <div className="text-xs text-slate-500 line-through">{money(src.last_was_price_cents)}</div>}
                </td>
                <td className="td text-right">{money(src.landed?.landed_cents)}</td>
                <td className="td">{src.last_in_stock == null ? "?" : src.last_in_stock ? "In stock" : "Out"}</td>
                <td className="td whitespace-nowrap text-xs text-slate-500" title={`Next: ${localTime(src.next_check_at)}`}>
                  {ago(src.last_checked_at)}
                </td>
                <td className="td text-xs">{src.status}</td>
                <td className="td whitespace-nowrap text-right">
                  {!src.url.startsWith("manual://") && (
                    <button className="btn-ghost px-2 py-1 text-xs"
                      onClick={() => run(async () => {
                        const r = await api<{ outcome: string }>(`/api/sources/${src.id}/check`, { method: "POST" });
                        flash(`Check result: ${r.outcome}`);
                      })}>
                      Check
                    </button>
                  )}
                  <button className="btn-ghost ml-1 px-2 py-1 text-xs text-red-600"
                    onClick={() => confirm("Remove this source and its history?") &&
                      run(() => api(`/api/sources/${src.id}`, { method: "DELETE" }), "Source removed")}>
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <form className="flex gap-2" onSubmit={(e) => {
            e.preventDefault();
            run(() => api(`/api/items/${id}/sources`, { method: "POST", json: { url: newUrl.trim() } }), "Source added; first check within a minute")
              .then(() => setNewUrl(""));
          }}>
            <input className="input" type="url" required placeholder="Add another retailer URL" value={newUrl} onChange={(e) => setNewUrl(e.target.value)} />
            <button className="btn-ghost">Add</button>
          </form>
          <form className="flex gap-2" onSubmit={(e) => {
            e.preventDefault();
            run(() => api(`/api/items/${id}/manual`, { method: "POST", json: {
              store: manual.store, price_cents: toCents(manual.price), shipping_cents: toCents(manual.shipping),
            } }), "Manual price recorded").then(() => setManual({ store: "", price: "", shipping: "" }));
          }}>
            <input className="input" required placeholder="Store" value={manual.store} onChange={(e) => setManual({ ...manual, store: e.target.value })} />
            <input className="input w-28" required inputMode="decimal" placeholder="Price" value={manual.price} onChange={(e) => setManual({ ...manual, price: e.target.value })} />
            <input className="input w-24" inputMode="decimal" placeholder="Ship" value={manual.shipping} onChange={(e) => setManual({ ...manual, shipping: e.target.value })} />
            <button className="btn-ghost">Log</button>
          </form>
        </div>
      </div>

      <form className="card grid gap-3 md:grid-cols-3" onSubmit={saveEdits}>
        <h2 className="font-semibold md:col-span-3">Settings for this item</h2>
        <div>
          <label className="label">Target price (before tax)</label>
          <input className="input" inputMode="decimal" value={form.target} onChange={(e) => setForm({ ...form, target: e.target.value })} />
        </div>
        <div>
          <label className="label">Maximum acceptable</label>
          <input className="input" inputMode="decimal" value={form.max} onChange={(e) => setForm({ ...form, max: e.target.value })} />
        </div>
        <div className="flex items-end gap-4">
          <div>
            <label className="label">Priority</label>
            <select className="input" value={form.priority} onChange={(e) => setForm({ ...form, priority: Number(e.target.value) })}>
              {[1, 2, 3, 4, 5].map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <label className="mb-2 flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.hot} onChange={(e) => setForm({ ...form, hot: e.target.checked })} /> Hot (check hourly)
          </label>
        </div>
        <div className="md:col-span-2">
          <label className="label">Notes</label>
          <textarea className="input" rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
        </div>
        <div>
          <label className="label">Amazon 365-day price history note</label>
          <textarea className="input" rows={2} placeholder="Copied from Amazon's Price History panel" value={form.amazon}
            onChange={(e) => setForm({ ...form, amazon: e.target.value })} />
        </div>
        <div className="md:col-span-3">
          <button className="btn-primary">Save</button>
        </div>
      </form>
    </div>
  );
}
