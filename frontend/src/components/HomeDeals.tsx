import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ago, api, money } from "../api";

interface Drop { image?: string | null; score?: number; item_id: number; item: string; store: string | null; url: string; price_cents: number; was_cents: number; drop_pct: number; seen_at: string }
interface Thread { item_id: number; item: string; title: string; url: string; price_cents: number | null; seen_at: string }
interface CatDeal { id: number; title: string; url: string; store: string | null; price_cents: number | null; was_cents: number | null;
  discount_pct: number | null; source: string; seen_at: string; image?: string | null; score?: number | null }
interface DealHistory { low_cents: number | null; high_cents: number | null; typical_cents: number | null; count: number; verdict: string | null }
interface Category { id: number; name: string; min_discount_pct: number; deals: CatDeal[]; last_search_at: string | null }
interface HomeDealsData { drops: Drop[]; threads: Thread[]; categories: Category[]; presets: string[] }

const SOURCE: Record<string, string> = { rfd: "RedFlagDeals", google_shopping: "Google Shopping" };

/** Home: today's biggest drops on your items, forum threads about them, and deals in categories you follow. */
export default function HomeDeals() {
  const [d, setD] = useState<HomeDealsData | null>(null);
  const [name, setName] = useState("");
  const [cat, setCat] = useState<number | null>(null);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState("");
  const [hist, setHist] = useState<Record<number, DealHistory | "loading">>({});
  const showHistory = (id: number) => {
    if (hist[id]) { const h = { ...hist }; delete h[id]; setHist(h); return; }
    setHist({ ...hist, [id]: "loading" });
    api<DealHistory>(`/api/category-deals/${id}/history`).then((h) => setHist((x) => ({ ...x, [id]: h }))).catch(() => {});
  };
  const load = () => api<HomeDealsData>("/api/deals/home").then((r) => {
    setD(r);
    setCat((c) => (c && r.categories.some((x) => x.id === c) ? c : r.categories[0]?.id ?? null));
  }).catch(() => {});
  useEffect(() => { load(); const t = setInterval(load, 300_000); return () => clearInterval(t); }, []);
  if (!d) return null;

  const follow = async (n: string) => {
    setError("");
    try { const r = await api<{ id: number }>("/api/deal-categories", { method: "POST", json: { name: n } }); setName(""); setCat(r.id); load(); }
    catch (e) { setError((e as Error).message); }
  };
  const submit = (e: FormEvent) => { e.preventDefault(); if (name.trim()) void follow(name.trim()); };
  const shown = d.categories.find((c) => c.id === cat);
  const unused = d.presets.filter((p) => !d.categories.some((c) => c.name.toLowerCase() === p.toLowerCase()));

  return (
    <div className="space-y-4">
      {d.drops.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Biggest drops on your items</h2>
          <div className="card py-1">
            {d.drops.map((x) => (
              <Link key={x.item_id} to={`/items/${x.item_id}`} className="flex items-center justify-between gap-3 border-t border-slate-100 px-1 py-2 first:border-0 dark:border-slate-800">
                {x.image ? <img src={x.image} alt="" loading="lazy" className="h-10 w-10 shrink-0 rounded bg-white object-contain" /> : null}
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium">{x.item}</div>
                  <div className="text-xs text-slate-500">{x.store} · {ago(x.seen_at)}</div>
                </div>
                <div className="shrink-0 text-right">
                  <div className="font-semibold text-green-700 dark:text-green-400">{money(x.price_cents)} <span className="text-xs">−{x.drop_pct}%</span></div>
                  <div className="text-xs text-slate-500 line-through">{money(x.was_cents)}</div>
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}

      {d.threads.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Forum deals on your items</h2>
          <div className="card space-y-2 text-sm">
            {d.threads.map((t) => (
              <div key={t.url + t.item_id} className="flex items-start justify-between gap-3">
                <a href={t.url} target="_blank" rel="noreferrer" className="min-w-0 hover:underline">
                  <div className="truncate">{t.title}</div>
                  <div className="text-xs text-slate-500">for {t.item} · {ago(t.seen_at)}</div>
                </a>
                {t.price_cents != null && <span className="shrink-0 font-semibold">{money(t.price_cents)}</span>}
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="space-y-2">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="text-lg font-semibold">Deals by category</h2>
          {d.categories.length > 0 && <button className="text-sm text-slate-500 hover:underline" onClick={() => setEditing(!editing)}>{editing ? "Done" : "Edit"}</button>}
        </div>
        {d.categories.length > 0 && (
          <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
            {d.categories.map((c) => (
              <span key={c.id} className="inline-flex shrink-0 items-center">
                <button onClick={() => setCat(c.id)}
                  className={`rounded-full px-3 py-1 text-sm ${c.id === cat ? "bg-red-700 text-white" : "bg-slate-200 dark:bg-slate-800"}`}>
                  {c.name}{c.deals.length ? ` (${c.deals.length})` : ""}
                </button>
                {editing && <button className="ml-1 px-1 text-slate-400 hover:text-red-600" aria-label={`Stop following ${c.name}`}
                  onClick={() => api(`/api/deal-categories/${c.id}`, { method: "DELETE" }).then(load)}>✕</button>}
              </span>
            ))}
          </div>
        )}
        {shown && (
          <div className="card py-1">
            {shown.deals.length === 0 && (
              <p className="py-2 text-sm text-slate-500">
                No deals for {shown.name} yet. New RedFlagDeals threads are sorted in as they appear, and Google Shopping sales are
                checked {shown.last_search_at ? `(last ${ago(shown.last_search_at)})` : "soon"}: daily in Black Friday week and Boxing Week.
              </p>
            )}
            {shown.deals.map((x) => (
              <div key={x.id} className="border-t border-slate-100 px-1 py-2 first:border-0 dark:border-slate-800">
              <div className="flex items-center gap-3">
                {x.image ? <img src={x.image} alt="" loading="lazy" className="h-14 w-14 shrink-0 rounded bg-white object-contain" />
                  : <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded bg-slate-100 text-xl dark:bg-slate-800" aria-hidden>🏷️</div>}
                <a href={x.url} target="_blank" rel="noreferrer" className="min-w-0 flex-1 hover:underline">
                  <div className="line-clamp-2 text-sm">{x.title}</div>
                  <div className="text-xs text-slate-500">
                    {x.score != null && <span className={`mr-1 rounded px-1 font-semibold ${x.score >= 70 ? "bg-green-600 text-white" : x.score >= 45 ? "bg-amber-500 text-white" : "bg-slate-300 text-slate-800"}`} title="Deal score: discount, lowest price seen, store, freshness">{x.score}</span>}
                    {[x.store, SOURCE[x.source] ?? x.source, ago(x.seen_at)].filter(Boolean).join(" · ")}
                  </div>
                </a>
                <div className="shrink-0 text-right">
                  {x.price_cents != null && <div className="font-semibold">{money(x.price_cents)}</div>}
                  {x.discount_pct != null && <div className="text-xs text-green-700 dark:text-green-400">−{x.discount_pct}% <span className="text-slate-500 line-through">{money(x.was_cents)}</span></div>}
                </div>
                <div className="flex shrink-0 flex-col gap-1">
                  <Link to={`/add?q=${encodeURIComponent(x.title.replace(/^\s*\[[^\]]*\]\s*/, ""))}`} className="btn-ghost px-2 py-0.5 text-xs">Watch</Link>
                  <button className="text-xs text-slate-500 hover:underline" onClick={() => showHistory(x.id)}>History</button>
                  <button className="text-xs text-slate-400 hover:text-red-600" onClick={() => api(`/api/category-deals/${x.id}/dismiss`, { method: "POST" }).then(load)}>Hide</button>
                </div>
              </div>
              {hist[x.id] && (
                <div className="mt-1 rounded bg-slate-50 p-2 text-xs dark:bg-slate-800/60">
                  {hist[x.id] === "loading" ? "Loading…" : (() => {
                    const h = hist[x.id] as DealHistory;
                    return <>
                      <div className="font-medium">{h.verdict ?? "No price history yet"}</div>
                      {h.count > 0 && <div className="text-slate-500">Lowest {money(h.low_cents)} · typical {money(h.typical_cents)} · highest {money(h.high_cents)} · seen {h.count} time{h.count === 1 ? "" : "s"}</div>}
                    </>;
                  })()}
                </div>
              )}
              </div>
            ))}
          </div>
        )}
        {(editing || d.categories.length === 0) && (
          <form onSubmit={submit} className="card space-y-2 text-sm">
            <p className="text-slate-500">Follow a kind of product and PriceWatch collects its Black Friday and Boxing Week deals here.</p>
            <div className="flex gap-2">
              <input className="input" placeholder="e.g. TVs, kitchen accessories, 3D printers" value={name} onChange={(e) => setName(e.target.value)} />
              <button className="btn-primary" disabled={!name.trim()}>Follow</button>
            </div>
            <div className="flex flex-wrap gap-1">
              {unused.map((p) => <button type="button" key={p} className="rounded-full bg-slate-100 px-2 py-0.5 text-xs hover:bg-slate-200 dark:bg-slate-800" onClick={() => follow(p)}>+ {p}</button>)}
            </div>
            {error && <p className="text-red-600">{error}</p>}
          </form>
        )}
      </section>
    </div>
  );
}
