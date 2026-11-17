import { useState } from "react";
import { Link } from "react-router-dom";
import { ago, api, money } from "../api";

export interface CatDeal { id: number; title: string; url: string; store: string | null; price_cents: number | null; was_cents: number | null;
  discount_pct: number | null; source: string; seen_at: string; image?: string | null; score?: number | null }
interface DealHistory { low_cents: number | null; high_cents: number | null; typical_cents: number | null; count: number; verdict: string | null }
export type DealView = "list" | "tiles";

export const SOURCE: Record<string, string> = { rfd: "RedFlagDeals", google_shopping: "Google Shopping" };

export function useDealView(): [DealView, (v: DealView) => void] {
  const [view, setView] = useState<DealView>(() => {
    try { return localStorage.getItem("pw-deal-view") === "tiles" ? "tiles" : "list"; } catch { return "list"; }
  });
  return [view, (v) => { setView(v); try { localStorage.setItem("pw-deal-view", v); } catch { /* private window */ } }];
}

export function DealViewToggle({ view, onPick }: { view: DealView; onPick: (v: DealView) => void }) {
  return (
    <div className="inline-flex overflow-hidden rounded-lg border border-slate-300 text-xs dark:border-slate-700" role="group" aria-label="Deal view">
      {(["list", "tiles"] as const).map((v) => (
        <button key={v} onClick={() => onPick(v)} aria-pressed={view === v}
          className={`px-2 py-1 ${view === v ? "bg-red-700 text-white" : "hover:bg-slate-100 dark:hover:bg-slate-800"}`}>
          {v === "list" ? "☰ List" : "▦ Tiles"}
        </button>
      ))}
    </div>
  );
}

/** A category's deals as tiles or rows, with Watch, History and Hide. Used on Home and on a category's own page. */
export default function DealList({ deals, view, onChange, empty }: { deals: CatDeal[]; view: DealView; onChange: () => void; empty?: React.ReactNode }) {
  const [hist, setHist] = useState<Record<number, DealHistory | "loading">>({});
  const showHistory = (id: number) => {
    if (hist[id]) { const h = { ...hist }; delete h[id]; setHist(h); return; }
    setHist({ ...hist, [id]: "loading" });
    api<DealHistory>(`/api/category-deals/${id}/history`).then((h) => setHist((x) => ({ ...x, [id]: h }))).catch(() => {});
  };
  if (!deals.length) return empty ? <div className="card py-1">{empty}</div> : null;
  if (view === "tiles")
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {deals.map((x) => (
          <div key={x.id} className="card flex flex-col gap-2 p-3">
            <a href={x.url} target="_blank" rel="noreferrer" className="relative block">
              {x.image ? <img src={x.image} alt="" loading="lazy" className="aspect-square w-full rounded bg-white object-contain" />
                : <div className="flex aspect-square w-full items-center justify-center rounded bg-slate-100 text-4xl dark:bg-slate-800" aria-hidden>🏷️</div>}
              {x.score != null && <span className={`absolute left-1 top-1 rounded px-1 text-xs font-semibold ${x.score >= 70 ? "bg-green-600 text-white" : x.score >= 45 ? "bg-amber-500 text-white" : "bg-slate-300 text-slate-800"}`} title="Deal score">{x.score}</span>}
              {x.discount_pct != null && <span className="absolute right-1 top-1 rounded bg-red-700 px-1 text-xs font-semibold text-white">−{x.discount_pct}%</span>}
            </a>
            <a href={x.url} target="_blank" rel="noreferrer" className="line-clamp-2 text-sm hover:underline">{x.title}</a>
            <div className="mt-auto">
              {x.price_cents != null && <div className="font-semibold">{money(x.price_cents)} {x.was_cents != null && <span className="text-xs font-normal text-slate-500 line-through">{money(x.was_cents)}</span>}</div>}
              <div className="truncate text-xs text-slate-500">{[x.store, SOURCE[x.source] ?? x.source].filter(Boolean).join(" · ")}</div>
            </div>
            <div className="flex items-center justify-between gap-1 text-xs">
              <Link to={`/add?q=${encodeURIComponent(x.title.replace(/^\s*\[[^\]]*\]\s*/, ""))}`} className="btn-ghost px-2 py-0.5 text-xs">Watch</Link>
              <button className="text-slate-500 hover:underline" onClick={() => showHistory(x.id)}>History</button>
              <button className="text-slate-400 hover:text-red-600" onClick={() => api(`/api/category-deals/${x.id}/dismiss`, { method: "POST" }).then(onChange)}>Hide</button>
            </div>
            {hist[x.id] && (
              <div className="rounded bg-slate-50 p-1 text-xs dark:bg-slate-800/60">
                {hist[x.id] === "loading" ? "Loading…" : ((hist[x.id] as DealHistory).verdict ?? "No price history yet")}
              </div>
            )}
          </div>
        ))}
      </div>
    );
  return (
    <div className="card py-1">
            {deals.map((x) => (
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
                  <button className="text-xs text-slate-400 hover:text-red-600" onClick={() => api(`/api/category-deals/${x.id}/dismiss`, { method: "POST" }).then(onChange)}>Hide</button>
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
  );
}
