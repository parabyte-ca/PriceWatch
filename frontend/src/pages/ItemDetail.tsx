import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ago, api, EXCLUSIONS, Item, localTime, money, toCents, toDollars } from "../api";
import Badge, { Confidence } from "../components/Badge";
import { Suggestions } from "../components/Discovery";
import PriceMatchView from "../components/PriceMatch";
import { useSession } from "../session";
import { BoughtForm, DealThreads, FlyerMatches, Forecast, PurchaseCard, PurchaseInfo } from "../components/Purchase";

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
  const [params, setParams] = useSearchParams();
  const urlAction = params.get("action");
  const [item, setItem] = useState<Item | null>(null);
  const [series, setSeries] = useState<Series[]>([]);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const { lists } = useSession();
  const [showMatch, setShowMatch] = useState<number | null>(null);
  const writable = lists.filter((l) => l.role !== "viewer");
  const [form, setForm] = useState({ name: "", brand: "", model: "", gtin: "", list: "", target: "", max: "", hot: false,
    priority: 3, notes: "", amazon: "", query: "" });
  const [rules, setRules] = useState<Record<string, boolean>>({});
  const [cdEnabled, setCdEnabled] = useState(false);
  const [buying, setBuying] = useState(false);
  const [purchases, setPurchases] = useState<PurchaseInfo[]>([]);
  const loadPurchases = useCallback(() => {
    api<PurchaseInfo[]>(`/api/purchases?item_id=${id}`).then(setPurchases).catch(() => {});
  }, [id]);
  useEffect(() => { loadPurchases(); }, [loadPurchases]);
  useEffect(() => {
    fetch("/healthz").then((r) => r.json()).then((h) => setCdEnabled(h.changedetection !== undefined)).catch(() => {});
  }, []);
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
        name: it.name, brand: it.brand || "", model: it.model || "", gtin: it.gtin || "", list: it.list_id ? String(it.list_id) : "",
        target: toDollars(it.target_price_cents), max: toDollars(it.max_price_cents), hot: it.hot,
        priority: it.priority, notes: it.notes || "", amazon: it.amazon_history_note || "", query: it.search_query || "",
      });
      setRules(Object.fromEntries(EXCLUSIONS.map(([k]) => [k, it[k]])));
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
    const gtin = form.gtin.replace(/\D/g, "");
    if (!form.name.trim()) return setError("The item needs a name");
    if (gtin && (gtin.length < 8 || gtin.length > 14)) return setError("A barcode has 8 to 14 digits");
    run(() => api(`/api/items/${id}`, { method: "PATCH", json: {
      name: form.name.trim(), brand: form.brand.trim() || null, model: form.model.trim() || null, gtin: gtin || null,
      ...(form.list && form.list !== String(item?.list_id) ? { list_id: Number(form.list) } : {}),
      target_price_cents: toCents(form.target), max_price_cents: toCents(form.max), hot: form.hot,
      priority: form.priority, notes: form.notes || null, amazon_history_note: form.amazon || null,
      search_query: form.query || null, ...rules,
    } }), "Saved");
  };

  if (error && !item) return <div className="card text-red-600">{error}</div>;
  if (!item) return <div className="text-slate-500">Loading...</div>;
  const s = item.summary;
  const amazon = item.sources?.find((x) => x.url.includes("amazon.ca"));
  const asin = amazon?.url.match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})/)?.[1];

  return (
    <div className="space-y-4">
      <Link to="/" className="text-sm text-slate-500 hover:underline">← Home</Link>
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
          {(urlAction === "bought" || buying) && (
            <BoughtForm item={item} onCancel={() => { setBuying(false); setParams({}); }}
              onDone={() => { setBuying(false); setParams({}); flash("Purchase saved; price protection is on"); load(); loadPurchases(); }} />
          )}
          <div className={`rounded-lg p-2 text-sm ${s.decision === "BUY" ? "bg-green-50 text-green-900" : s.decision === "BUY_AND_PROTECT" ? "bg-teal-50 text-teal-900" : "bg-slate-100 dark:bg-slate-800"}`}>
            <span className="font-semibold">{s.badge}:</span> {s.decision_reason}. <Confidence level={s.history_confidence} days={s.history_days} />
            {s.snoozed && <span className="ml-2 text-amber-700">Alerts snoozed.</span>}
          </div>
          {s.market?.best && (s.best_price_cents == null || s.market.best.price_cents < s.best_price_cents) && (
            <a href={s.market.best.url} target="_blank" rel="noreferrer"
              className="block rounded-lg border border-green-600/40 bg-green-50 p-3 text-sm text-green-900 hover:shadow dark:bg-green-950/40 dark:text-green-100">
              <div className="text-xs uppercase tracking-wide opacity-80">Best price found online</div>
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="text-2xl font-bold">{money(s.market.best.price_cents)}</span>
                <span className="font-medium">at {s.market.best.merchant}</span>
                {s.market.best.shipping_cents === 0 && <span className="text-xs">free shipping</span>}
              </div>
              <div className="text-xs opacity-80">
                Before tax · {s.market.stores} store{s.market.stores === 1 ? "" : "s"} compared · seen {ago(s.market.seen_at)} ·
                {s.market.best.store_link ? " opens the store's page" : " opens Google Shopping"}
              </div>
            </a>
          )}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Best landed" value={money(s.best_landed_cents)}
              note={s.best ? `${money(s.best.landed.price_cents)} + ${s.best.landed.shipping_known ? money(s.best.landed.shipping_cents) + " ship" : "shipping unknown"} + ${money(s.best.landed.tax_cents)} tax, ${s.best.retailer}` : undefined} />
            <Stat label="Target" value={money(item.target_price_cents)} />
            <Stat label="Seasonal low (landed)" value={money(s.seasonal_low_cents)}
              note={s.distance_to_low_pct != null ? `Now ${s.distance_to_low_pct > 0 ? "+" : ""}${s.distance_to_low_pct}% vs the low` : "Since Oct 1 or 90 days"} />
            <Stat label="30 / 60 / 90-day low" value={money(s.low_30_cents)}
              note={`${money(s.low_60_cents)} / ${money(s.low_90_cents)}${s.real_discount_pct != null ? `; ${s.real_discount_pct}% below 60-day median` : ""}`} />
          </div>
          {s.best?.after_perks_cents != null && (
            <div className="rounded-lg bg-blue-50 p-2 text-sm text-blue-900 dark:bg-blue-950 dark:text-blue-100">
              After perks at {s.best.retailer}: <span className="font-semibold">{money(s.best.after_perks_cents)}</span>
              {" "}({s.best.perks?.map((p) => p.label).join(" + ")}; {money(s.best.perks_saving_cents)} back). Perks come back later as cash back or points, so targets still use the till price.
            </div>
          )}
          {s.fake_sale && (
            <div className="rounded-lg bg-amber-100 p-2 text-sm text-amber-900">
              Fake sale warning: {s.fake_sale_reasons.join("; ")}.
            </div>
          )}
          {s.price_match.map((o) => (
            <div key={o.at_source_id} className="rounded-lg bg-blue-50 p-2 text-sm text-blue-900 dark:bg-blue-950 dark:text-blue-100">
              Price match: ask <b>{o.at}</b> to match <a className="underline" href={o.match_url} target="_blank" rel="noreferrer">{o.match_to}</a> at {money(o.price_cents)} (save {money(o.saving_cents)} before tax).
              {o.caveats.map((c) => <div key={c} className="text-xs text-amber-800">{c}</div>)}
              {o.policy_notes && <div className="text-xs opacity-80">{o.policy_notes}</div>}
              <button className="btn-primary mt-2 px-3 py-1.5" onClick={() => setShowMatch(o.at_source_id)}>Show at the till</button>
            </div>
          ))}
          {showMatch != null && s.price_match.find((o) => o.at_source_id === showMatch) && (
            <PriceMatchView item={item} o={s.price_match.find((o) => o.at_source_id === showMatch)!} onClose={() => setShowMatch(null)} />
          )}
          <div className="flex flex-wrap gap-2">
            <button className="btn-ghost" onClick={() => run(() => api(`/api/items/${id}/check`, { method: "POST" }), "Checks queued; refresh in a minute")}>
              Check all now
            </button>
            <button className="btn-ghost" onClick={() => setBuying(true)}>Bought</button>
            {s.snoozed ? (
              <button className="btn-ghost" onClick={() => run(() => api(`/api/items/${id}/snooze`, { method: "DELETE" }), "Alerts back on")}>Unsnooze</button>
            ) : (
              <button className="btn-ghost" onClick={() => run(() => api(`/api/items/${id}/snooze`, { method: "POST", json: { hours: 24 } }), "Snoozed for 24 hours")}>Snooze 24h</button>
            )}
            {asin && (
              <>
                <a className="btn-ghost" href={`https://www.amazon.ca/dp/${asin}`} target="_blank" rel="noreferrer"
                  title="Open the product and use Amazon's Price History panel to check">Check Amazon Price History</a>
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
                  <Line key={sr.source_id} dataKey={sr.name} type="stepAfter" connectNulls dot={sr.points.length < 4}
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
        <table className="w-full table-fixed sm:table-auto">
          <thead>
            <tr>
              <th className="th w-1/2 sm:w-auto">Retailer</th>
              <th className="th text-right">Price</th>
              <th className="th text-right">Landed</th>
              <th className="th hidden sm:table-cell">Stock</th>
              <th className="th hidden sm:table-cell">Checked</th>
              <th className="th hidden sm:table-cell"></th>
            </tr>
          </thead>
          <tbody>
            {item.sources?.filter((x) => x.status === "confirmed").map((src) => (
              <tr key={src.id} className="border-t border-slate-100 dark:border-slate-800">
                <td className="td">
                  {src.url.startsWith("manual://") ? (
                    <span>{src.title} <span className="text-xs text-slate-500">(manual)</span></span>
                  ) : (
                    <a href={src.url} target="_blank" rel="noreferrer" className="hover:underline">{src.retailer_name || src.url}</a>
                  )}
                  {src.price_match && <span className="ml-1 text-xs text-blue-600" title="Retailer has a price-match policy">PM</span>}
                  <div className="text-xs text-slate-500">
                    {[src.channel !== "online" ? src.channel : null,
                      src.last_seller_type?.startsWith("marketplace") ? src.last_seller_type.replace("marketplace:", "sold by ") : null,
                      src.last_condition && src.last_condition !== "new" ? src.last_condition.replace("_", " ") : null,
                      src.last_method === "claude" ? "price read by Claude" : null,
                      src.fetch_mode && src.fetch_mode !== "auto" ? `via ${src.fetch_mode}` : null].filter(Boolean).join(" · ")}
                  </div>
                  {src.last_error && <div className="break-words text-xs text-red-600">{src.last_error}</div>}
                  <div className="mt-1 flex flex-wrap items-center gap-1 text-xs text-slate-500 sm:hidden">
                    <span>{src.last_in_stock == null ? "stock ?" : src.last_in_stock ? "in stock" : "out of stock"} · {ago(src.last_checked_at)}</span>
                    {!src.url.startsWith("manual://") && (
                      <button className="btn-ghost px-2 py-0.5 text-xs" onClick={() => run(async () => {
                        const r = await api<{ outcome: string }>(`/api/sources/${src.id}/check`, { method: "POST" });
                        flash(`Check result: ${r.outcome}`);
                      })}>Check</button>
                    )}
                    <button className="btn-ghost px-2 py-0.5 text-xs text-red-600" onClick={() => confirm("Remove this source and its history?") &&
                      run(() => api(`/api/sources/${src.id}`, { method: "DELETE" }), "Source removed")}>Remove</button>
                  </div>
                </td>
                <td className="td text-right">
                  {money(src.last_price_cents)}
                  {src.last_was_price_cents && <div className="text-xs text-slate-500 line-through">{money(src.last_was_price_cents)}</div>}
                </td>
                <td className="td text-right">{money(src.landed?.landed_cents)}</td>
                <td className="td hidden sm:table-cell">{src.last_in_stock == null ? "?" : src.last_in_stock ? "In stock" : "Out"}</td>
                <td className="td hidden whitespace-nowrap text-xs text-slate-500 sm:table-cell" title={`Next: ${localTime(src.next_check_at)}`}>
                  {ago(src.last_checked_at)}
                </td>
                <td className="td hidden whitespace-nowrap text-right sm:table-cell">
                  {!src.url.startsWith("manual://") && (
                    <button className="btn-ghost px-2 py-1 text-xs"
                      onClick={() => run(async () => {
                        const r = await api<{ outcome: string }>(`/api/sources/${src.id}/check`, { method: "POST" });
                        flash(`Check result: ${r.outcome}`);
                      })}>
                      Check
                    </button>
                  )}
                  {cdEnabled && !src.url.startsWith("manual://") && src.fetch_mode !== "changedetection" && (
                    <button className="btn-ghost ml-1 px-2 py-1 text-xs" title="Let changedetection.io fetch this page instead"
                      onClick={() => run(() => api(`/api/sources/${src.id}/changedetection`, { method: "POST" }), "Handed to changedetection.io")}>
                      CD.io
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
            {!item.sources?.some((x) => x.status === "confirmed") && (
              <tr><td className="td text-slate-500" colSpan={6}>No tracked sources yet. Add a retailer URL, log a price, or confirm a suggestion below.</td></tr>
            )}
          </tbody>
        </table>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <form className="flex min-w-0 gap-2" onSubmit={(e) => {
            e.preventDefault();
            run(() => api(`/api/items/${id}/sources`, { method: "POST", json: { url: newUrl.trim() } }), "Source added; first check within a minute")
              .then(() => setNewUrl(""));
          }}>
            <input className="input" type="url" required placeholder="Add another retailer URL" value={newUrl} onChange={(e) => setNewUrl(e.target.value)} />
            <button className="btn-ghost">Add</button>
          </form>
          <form className="flex min-w-0 flex-wrap gap-2 sm:flex-nowrap" onSubmit={(e) => {
            e.preventDefault();
            run(() => api(`/api/items/${id}/manual`, { method: "POST", json: {
              store: manual.store, price_cents: toCents(manual.price), shipping_cents: toCents(manual.shipping),
            } }), "Manual price recorded").then(() => setManual({ store: "", price: "", shipping: "" }));
          }}>
            <input className="input" required placeholder="Store" value={manual.store} onChange={(e) => setManual({ ...manual, store: e.target.value })} />
            <input className="input w-[calc(50%-0.25rem)] sm:w-28" required inputMode="decimal" placeholder="Price" value={manual.price} onChange={(e) => setManual({ ...manual, price: e.target.value })} />
            <input className="input w-[calc(50%-0.25rem)] sm:w-24" inputMode="decimal" placeholder="Ship" value={manual.shipping} onChange={(e) => setManual({ ...manual, shipping: e.target.value })} />
            <button className="btn-ghost">Log</button>
          </form>
        </div>
      </div>

      {purchases.length > 0 && (
        <div className="space-y-2">
          {purchases.map((p) => <PurchaseCard key={p.id} p={p} onChange={() => { loadPurchases(); load(); }} />)}
        </div>
      )}
      <Forecast itemId={item.id} />
      <DealThreads itemId={item.id} />
      <FlyerMatches itemId={item.id} />
      <Suggestions item={item} onChange={load} />

      <form className="card grid gap-3 md:grid-cols-3" onSubmit={saveEdits}>
        <h2 className="font-semibold md:col-span-3">Edit this item</h2>
        <div className="md:col-span-2">
          <label className="label">Name</label>
          <input className="input" required maxLength={300} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </div>
        <div>
          <label className="label">List</label>
          <select className="input" value={form.list} onChange={(e) => setForm({ ...form, list: e.target.value })}>
            {writable.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        </div>
        <div>
          <label className="label">Brand</label>
          <input className="input" value={form.brand} onChange={(e) => setForm({ ...form, brand: e.target.value })} />
        </div>
        <div>
          <label className="label">Model number</label>
          <input className="input" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} />
        </div>
        <div>
          <label className="label">Barcode (UPC/EAN)</label>
          <input className="input font-mono" inputMode="numeric" value={form.gtin} onChange={(e) => setForm({ ...form, gtin: e.target.value })} />
        </div>
        <div>
          <label className="label">Target price (before tax)</label>
          <input className="input" inputMode="decimal" autoFocus={urlAction === "target"} value={form.target} onChange={(e) => setForm({ ...form, target: e.target.value })} />
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
            <input type="checkbox" checked={form.hot} onChange={(e) => setForm({ ...form, hot: e.target.checked })} /> Hot (every 2 h; 30 min on Black Friday)
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
          <label className="label">Matching rules: exclude</label>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {EXCLUSIONS.map(([k, label]) => (
              <label key={k} className="flex items-center gap-1 text-sm">
                <input type="checkbox" checked={Boolean(rules[k])} onChange={(e) => setRules({ ...rules, [k]: e.target.checked })} /> {label}
              </label>
            ))}
          </div>
        </div>
        <div className="md:col-span-3">
          <label className="label">Search query (optional, overrides brand + name + model)</label>
          <input className="input" value={form.query} onChange={(e) => setForm({ ...form, query: e.target.value })} />
        </div>
        <div className="flex flex-wrap items-center gap-3 md:col-span-3">
          <button className="btn-primary">Save</button>
        </div>
      </form>
    </div>
  );
}
