import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, Item, money } from "../api";
import Badge from "../components/Badge";
import { useSession } from "../session";

const isBuy = (i: Item) => i.summary.decision === "BUY" || i.summary.decision === "BUY_AND_PROTECT";
const hasPrice = (i: Item) => i.summary.best_landed_cents != null;
const online = (i: Item) => i.summary.market?.best ?? null;

/** One plain sentence for a card: what to do and why. */
function verdict(i: Item): string {
  const s = i.summary;
  if (isBuy(i)) return s.decision === "BUY_AND_PROTECT" ? "Good price, and the store will refund a later drop." : "Good time to buy.";
  const m = online(i);
  if (!hasPrice(i) && m) return `Best online: ${money(m.price_cents)} at ${m.merchant} (${i.summary.market!.stores} store${i.summary.market!.stores === 1 ? "" : "s"} compared).`;
  if (!hasPrice(i)) return "Looking for prices at Canadian stores.";
  if (s.distance_to_low_pct != null && s.distance_to_low_pct > 0) return `${s.distance_to_low_pct}% above the lowest price this season.`;
  return "Waiting for a better price.";
}

function BuyCard({ i, list }: { i: Item; list?: string }) {
  const s = i.summary;
  return (
    <Link to={`/items/${i.id}`} className="card block border-l-4 border-l-green-600 transition hover:shadow-md">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs text-slate-500">{[list, s.best?.retailer].filter(Boolean).join(" · ")}</div>
          <div className="break-words font-semibold leading-tight">{i.name}</div>
        </div>
        <Badge value={s.badge} />
      </div>
      <div className="mt-2 flex flex-wrap items-baseline gap-x-3">
        <span className="text-2xl font-bold">{money(s.best_landed_cents)}</span>
        <span className="text-xs text-slate-500">with tax</span>
        {s.best?.after_perks_cents != null && <span className="text-xs text-blue-700 dark:text-blue-300">{money(s.best.after_perks_cents)} after perks</span>}
      </div>
      <div className="mt-1 text-sm text-slate-600 dark:text-slate-300">{verdict(i)}</div>
    </Link>
  );
}

function Row({ i, list }: { i: Item; list?: string }) {
  const s = i.summary;
  return (
    <Link to={`/items/${i.id}`} className="flex items-center justify-between gap-3 border-t border-slate-100 px-1 py-3 first:border-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/40">
      <div className="min-w-0">
        <div className="truncate font-medium">{i.name}</div>
        <div className="truncate text-xs text-slate-500">
          {list && `${list} · `}{verdict(i)}{s.stale && s.source_count > 0 ? " Price may be out of date." : ""}
        </div>
      </div>
      <div className="shrink-0 text-right">
        <div className="font-semibold">{hasPrice(i) ? money(s.best_landed_cents) : online(i) ? money(online(i)!.price_cents) : "—"}</div>
        {!hasPrice(i) && online(i) && <div className="text-xs text-slate-500">online, before tax</div>}
        {i.target_price_cents != null && <div className="text-xs text-slate-500">target {money(i.target_price_cents)}</div>}
      </div>
    </Link>
  );
}

/** Home: what to buy now, what to wait on, and what is still being set up. Replaces Wishlist and Board. */
export default function Home() {
  const { lists } = useSession();
  const [items, setItems] = useState<Item[] | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<string | null>(null);
  const [listId, setListId] = useState<string>(() => {
    try { return localStorage.getItem("pw-list") || ""; } catch { return ""; }
  });
  const listName = (id: number | null) => (lists.length > 1 && !listId ? lists.find((l) => l.id === id)?.name : undefined);

  useEffect(() => { api<{ active: string | null }>("/api/sale-mode").then((m) => setMode(m.active)).catch(() => {}); }, []);
  useEffect(() => {
    const load = () => api<Item[]>(`/api/items${listId ? `?list_id=${listId}` : ""}`).then(setItems).catch((e) => setError(e.message));
    load();
    try { localStorage.setItem("pw-list", listId); } catch { /* storage unavailable */ }
    const t = setInterval(load, 60_000);
    return () => clearInterval(t);
  }, [listId]);

  const groups = useMemo(() => {
    const rows = (items || []).filter((i) => i.name.toLowerCase().includes(query.toLowerCase()));
    const byLow = (a: Item, b: Item) => (a.summary.distance_to_low_pct ?? 999) - (b.summary.distance_to_low_pct ?? 999) || a.priority - b.priority;
    return {
      buy: rows.filter(isBuy).sort(byLow),
      wait: rows.filter((i) => !isBuy(i) && hasPrice(i)).sort(byLow),
      setup: rows.filter((i) => !isBuy(i) && !hasPrice(i)).sort((a, b) => a.name.localeCompare(b.name)),
    };
  }, [items, query]);

  if (error) return <div className="card text-red-600">{error}</div>;
  if (!items) return <div className="text-slate-500">Loading...</div>;
  if (!items.length)
    return (
      <div className="card space-y-3 py-10 text-center">
        <div className="text-4xl">🎁</div>
        <p className="text-lg font-semibold">Nothing on your list yet</p>
        <p className="text-sm text-slate-500">Paste a product link, scan a barcode or type a name. PriceWatch watches the price and tells you when to buy.</p>
        <Link to="/add" className="btn-primary">Add your first item</Link>
      </div>
    );

  return (
    <div className="space-y-4">
      {mode && <div className="rounded-lg bg-red-700 p-2 text-sm font-semibold text-white">{mode} is on: your top items are checked every 30 minutes.</div>}

      <div className="flex flex-wrap items-center gap-2">
        {lists.length > 1 && (
          <select className="input w-auto max-w-full" value={listId} onChange={(e) => setListId(e.target.value)} aria-label="List">
            <option value="">All my lists</option>
            {lists.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        )}
        <input className="input w-40 flex-1 sm:max-w-xs" placeholder="Search" value={query} onChange={(e) => setQuery(e.target.value)} />
        <Link to="/add" className="btn-primary">+ Add</Link>
      </div>

      <section className="space-y-2">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="text-lg font-semibold">Buy now <span className="text-sm font-normal text-slate-500">{groups.buy.length}</span></h2>
          {groups.buy.length > 1 && <Link to="/basket" className="text-sm text-red-700 hover:underline dark:text-red-400">Cheapest way to buy these →</Link>}
        </div>
        {groups.buy.length ? (
          <div className="grid gap-3 md:grid-cols-2">{groups.buy.map((i) => <BuyCard key={i.id} i={i} list={listName(i.list_id)} />)}</div>
        ) : (
          <p className="card text-sm text-slate-500">Nothing is at a good price right now. PriceWatch will tell you when something is.</p>
        )}
      </section>

      {groups.wait.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Waiting for a better price <span className="text-sm font-normal text-slate-500">{groups.wait.length}</span></h2>
          <div className="card py-1">{groups.wait.map((i) => <Row key={i.id} i={i} list={listName(i.list_id)} />)}</div>
        </section>
      )}

      {groups.setup.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Getting set up <span className="text-sm font-normal text-slate-500">{groups.setup.length}</span></h2>
          <div className="card py-1">{groups.setup.map((i) => <Row key={i.id} i={i} list={listName(i.list_id)} />)}</div>
        </section>
      )}
    </div>
  );
}
