import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ago, api } from "../api";
import DealList, { CatDeal, DealViewToggle, useDealView } from "../components/DealList";

interface Page {
  id: number; name: string; total: number; min_discount_pct: number; last_search_at: string | null;
  forecast?: { text: string } | null; sort: string; deals: CatDeal[];
}

const SORTS: [string, string][] = [["score", "Best deal"], ["discount", "Biggest discount"], ["price", "Lowest price"], ["newest", "Newest"]];
const PAGE = 30;

/** All of one category's deals ("More" on Home), sorted your way, 30 at a time. */
export default function CategoryDeals() {
  const { id } = useParams();
  const [view, pickView] = useDealView();
  const [sort, setSort] = useState(() => {
    try { return localStorage.getItem("pw-deal-sort") || "score"; } catch { return "score"; }
  });
  const [page, setPage] = useState<Page | null>(null);
  const [deals, setDeals] = useState<CatDeal[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (count = PAGE) => {
    setBusy(true);
    try {
      const p = await api<Page>(`/api/deal-categories/${id}/deals?sort=${sort}&offset=0&limit=${Math.min(count, 100)}`);
      setPage(p); setDeals(p.deals); setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [id, sort]);
  useEffect(() => { void load(); }, [load]);

  const more = async () => {
    setBusy(true);
    try {
      const p = await api<Page>(`/api/deal-categories/${id}/deals?sort=${sort}&offset=${deals.length}&limit=${PAGE}`);
      setPage(p); setDeals([...deals, ...p.deals.filter((d) => !deals.some((x) => x.id === d.id))]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const pickSort = (s: string) => { setSort(s); try { localStorage.setItem("pw-deal-sort", s); } catch { /* private window */ } };

  if (error) return <div className="card text-red-600">{error} <Link to="/" className="underline">Back to Home</Link></div>;
  if (!page) return <div className="text-slate-500">Loading...</div>;

  return (
    <div className="space-y-3">
      <Link to="/" className="text-sm text-slate-500 hover:underline">← Home</Link>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-lg font-semibold">{page.name} <span className="text-sm font-normal text-slate-500">{page.total} deal{page.total === 1 ? "" : "s"}</span></h1>
        <DealViewToggle view={view} onPick={pickView} />
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label htmlFor="deal-sort" className="text-slate-500">Sort</label>
        <select id="deal-sort" className="input w-auto py-1" value={sort} onChange={(e) => pickSort(e.target.value)}>
          {SORTS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
        </select>
        <span className="text-xs text-slate-500">
          Last 10 days, at least {page.min_discount_pct}% off{page.last_search_at ? ` · searched ${ago(page.last_search_at)}` : ""}
        </span>
      </div>
      {page.forecast && <p className="text-xs text-slate-500">📈 {page.forecast.text}</p>}
      <DealList deals={deals} view={view} onChange={() => load(Math.max(deals.length, PAGE))}
        empty={<p className="py-2 text-sm text-slate-500">No deals for {page.name} right now.</p>} />
      {deals.length < page.total && (
        <button className="btn-ghost w-full" disabled={busy} onClick={more}>
          {busy ? "Loading…" : `Show more (${page.total - deals.length} left)`}
        </button>
      )}
    </div>
  );
}
