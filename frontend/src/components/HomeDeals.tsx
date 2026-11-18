import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ago, api, money } from "../api";
import DealList, { CatDeal, DealViewToggle, useDealView } from "./DealList";

interface Drop { image?: string | null; score?: number; item_id: number; item: string; store: string | null; url: string; price_cents: number; was_cents: number; drop_pct: number; seen_at: string }
interface Thread { item_id: number; item: string; title: string; url: string; price_cents: number | null; seen_at: string }
interface Category { forecast?: { text: string } | null; id: number; name: string; min_discount_pct: number; deals: CatDeal[]; last_search_at: string | null; total: number }
interface HomeDealsData { drops: Drop[]; threads: Thread[]; categories: Category[]; presets: string[] }

/** Home: today's biggest drops on your items, forum threads about them, and deals in categories you follow. */
export default function HomeDeals() {
  const [d, setD] = useState<HomeDealsData | null>(null);
  const [name, setName] = useState("");
  const [cat, setCat] = useState<number | null>(null);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState("");
  const [view, pickView] = useDealView();
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
          <div className="flex items-center gap-3">
            {d.categories.length > 0 && <DealViewToggle view={view} onPick={pickView} />}
            {d.categories.length > 0 && <button className="text-sm text-slate-500 hover:underline" onClick={() => setEditing(!editing)}>{editing ? "Done" : "Edit"}</button>}
          </div>
        </div>
        {d.categories.length > 0 && (
          <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
            {d.categories.map((c) => (
              <span key={c.id} className="inline-flex shrink-0 items-center">
                <button onClick={() => setCat(c.id)}
                  className={`rounded-full px-3 py-1 text-sm ${c.id === cat ? "bg-red-700 text-white" : "bg-slate-200 dark:bg-slate-800"}`}>
                  {c.name}{c.total ? ` (${c.total})` : ""}
                </button>
                {editing && <Link to={`/deals/${c.id}?settings=1`} className="ml-1 px-1 text-slate-400 hover:text-slate-700" aria-label={`Settings for ${c.name}`}>⚙</Link>}
                {editing && <button className="ml-1 px-1 text-slate-400 hover:text-red-600" aria-label={`Stop following ${c.name}`}
                  onClick={() => api(`/api/deal-categories/${c.id}`, { method: "DELETE" }).then(load)}>✕</button>}
              </span>
            ))}
          </div>
        )}
        {shown?.forecast && <p className="px-1 text-xs text-slate-500">📈 {shown.forecast.text}</p>}
        {shown && (
          <DealList deals={shown.deals} view={view} onChange={load} empty={
            <p className="py-2 text-sm text-slate-500">
              No deals for {shown.name} yet. New RedFlagDeals threads are sorted in as they appear, and Google Shopping sales are
              checked {shown.last_search_at ? `(last ${ago(shown.last_search_at)})` : "soon"}: daily in Black Friday week and Boxing Week.{" "}
              <Link to={`/deals/${shown.id}?settings=1`} className="text-red-700 underline dark:text-red-400">Widen the search</Link>
            </p>} />
        )}
        {shown && shown.total > shown.deals.length && (
          <Link to={`/deals/${shown.id}`} className="block text-center text-sm text-red-700 hover:underline dark:text-red-400">
            More {shown.name} deals ({shown.total}) →
          </Link>
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
