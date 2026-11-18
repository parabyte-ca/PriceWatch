import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ago, api, toCents, toDollars } from "../api";
import DealList, { CatDeal, DealViewToggle, useDealView } from "../components/DealList";

interface Page {
  id: number; name: string; total: number; min_discount_pct: number; last_search_at: string | null;
  forecast?: { text: string } | null; sort: string; deals: CatDeal[]; max_price_cents: number | null;
  adult: boolean; search_words: string | null; claude_search: boolean; last_claude_at: string | null; claude_ready: boolean;
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
  const [params] = useSearchParams();
  const [editing, setEditing] = useState(params.get("settings") === "1");

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
      <button className="text-sm text-red-700 hover:underline dark:text-red-400" onClick={() => setEditing(!editing)}>
        {editing ? "Hide category settings" : "⚙ Category settings: search words, discount, adult, Claude"}
      </button>
      {editing && <Settings page={page} onSaved={() => { setEditing(false); void load(); }} />}
      {page.forecast && <p className="text-xs text-slate-500">📈 {page.forecast.text}</p>}
      <DealList deals={deals} view={view} onChange={() => load(Math.max(deals.length, PAGE))}
        empty={<p className="py-2 text-sm text-slate-500">
          No deals for {page.name} right now. Try your own search words, a lower minimum discount
          {page.claude_ready ? ", or Claude web search" : ""} in Category settings.
        </p>} />
      {deals.length < page.total && (
        <button className="btn-ghost w-full" disabled={busy} onClick={more}>
          {busy ? "Loading…" : `Show more (${page.total - deals.length} left)`}
        </button>
      )}
    </div>
  );
}

/** One category's search settings: words searched in turn, discount and price rules, adult, Claude web search. */
function Settings({ page, onSaved }: { page: Page; onSaved: () => void }) {
  const [f, setF] = useState({
    name: page.name, words: page.search_words || "", min: String(page.min_discount_pct), max: toDollars(page.max_price_cents),
    adult: page.adult, claude: page.claude_search,
  });
  const [msg, setMsg] = useState("");
  const save = async (searchNow: boolean) => {
    setMsg("");
    try {
      await api(`/api/deal-categories/${page.id}`, { method: "PATCH", json: {
        name: f.name.trim(), search_words: f.words.trim() || null, min_discount_pct: Number(f.min) || 0,
        max_price_cents: toCents(f.max), adult: f.adult, claude_search: f.claude,
      } });
      if (searchNow) await api(`/api/deal-categories/${page.id}/search`, { method: "POST" });
      setMsg(searchNow ? "Saved. Searching now: new deals appear in a minute or two." : "Saved.");
      setTimeout(onSaved, searchNow ? 2500 : 600);
    } catch (e) { setMsg((e as Error).message); }
  };
  const words = f.words.split(",").map((w) => w.trim()).filter(Boolean);
  return (
    <div className="card space-y-3 text-sm">
      <label className="block">Name
        <input className="input mt-1" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
      </label>
      <label className="block">Search words, separated by commas
        <input className="input mt-1" placeholder={`e.g. ${page.name}, a brand, a product type`} value={f.words}
          onChange={(e) => setF({ ...f, words: e.target.value })} />
        <span className="text-xs text-slate-500">
          {words.length > 1 ? `One word per search, in turn (${words.length} words: each is searched about every ${words.length} searches).`
            : "Empty: the category name is searched."} Each search uses one of the month's searches.
        </span>
      </label>
      <div className="flex flex-wrap gap-3">
        <label>Minimum discount
          <span className="mt-1 flex items-center gap-1"><input className="input w-20" inputMode="numeric" value={f.min}
            onChange={(e) => setF({ ...f, min: e.target.value.replace(/\D/g, "") })} />%</span>
        </label>
        <label>Highest price
          <input className="input mt-1 block w-28" inputMode="decimal" placeholder="Any" value={f.max} onChange={(e) => setF({ ...f, max: e.target.value })} />
        </label>
      </div>
      <label className="flex items-start gap-2">
        <input type="checkbox" className="mt-1" checked={f.adult} onChange={(e) => setF({ ...f, adult: e.target.checked })} />
        <span>Adult products<span className="block text-xs text-slate-500">Searches this category with Google SafeSearch off, which otherwise hides adult products. Other searches stay filtered.</span></span>
      </label>
      <label className={`flex items-start gap-2 ${page.claude_ready ? "" : "opacity-60"}`}>
        <input type="checkbox" className="mt-1" disabled={!page.claude_ready} checked={f.claude} onChange={(e) => setF({ ...f, claude: e.target.checked })} />
        <span>Also ask Claude to search the web
          <span className="block text-xs text-slate-500">
            {page.claude_ready
              ? `When Google Shopping finds fewer than 3 new deals, Claude searches online stores selling to Canada, at most once a day (every 6 hours on Black Friday, Cyber Monday and Boxing Day). About 6 cents each, counted in the monthly Claude cap.${page.last_claude_at ? ` Last ${ago(page.last_claude_at)}.` : ""}`
              : "Needs a Claude key (Household admin)."}
          </span>
        </span>
      </label>
      <div className="flex flex-wrap gap-2">
        <button className="btn-primary" onClick={() => save(true)} disabled={f.name.trim().length < 2}>Save and search now</button>
        <button className="btn-ghost" onClick={() => save(false)} disabled={f.name.trim().length < 2}>Save</button>
      </div>
      {msg && <p className={msg.startsWith("Saved") ? "text-green-700 dark:text-green-400" : "text-red-600"}>{msg}</p>}
    </div>
  );
}
