import { useEffect, useState } from "react";
import { ago, api, DiscoveryResult, Item, money, Offer } from "../api";


export function Suggestions({ item, onChange }: { item: Item; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<DiscoveryResult | null>(null);
  const [error, setError] = useState("");
  const [showRejected, setShowRejected] = useState(false);
  const [status, setStatusInfo] = useState<{ searching: boolean; provider: string | null } | null>(null);
  const [offers, setOffers] = useState<Offer[] | null>(null);
  const [showAll, setShowAll] = useState(false);
  const storeOffers = (offers || []).filter((o) => o.kind === "store");
  const otherOffers = (offers || []).filter((o) => o.kind !== "store");
  const loadOffers = () => api<Offer[]>(`/api/items/${item.id}/offers`).then(setOffers).catch(() => setOffers([]));
  useEffect(() => { loadOffers(); }, [item.id, item.sources?.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const track = async (url: string) => {
    setError("");
    try { await api(`/api/items/${item.id}/sources`, { method: "POST", json: { url } }); onChange(); loadOffers(); }
    catch (e) { setError((e as Error).message); }
  };
  // a search starts by itself when an item is added; show it and refresh when it finishes
  useEffect(() => {
    let stop = false;
    let was = false;
    const poll = () => api<{ searching: boolean; provider: string | null }>(`/api/items/${item.id}/discover`).then((st) => {
      if (stop) return;
      setStatusInfo(st);
      if (was && !st.searching) { onChange(); loadOffers(); }
      was = st.searching;
      if (st.searching) setTimeout(poll, 4000);
    }).catch(() => {});
    poll();
    return () => { stop = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id]);
  const via = status?.provider === "claude" ? "Claude web search" : status?.provider ? "Google Shopping" : null;
  const rejected = (item.sources || []).filter((s) => s.status === "rejected");

  const setStatus = async (id: number, status: string) => {
    setError("");
    try {
      await api(`/api/sources/${id}`, { method: "PATCH", json: { status } });
      onChange();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const find = async (force = false) => {
    setBusy(true);
    setError("");
    try {
      const r = await api<DiscoveryResult>(`/api/items/${item.id}/discover`, { method: "POST", json: { force } });
      setResult(r);
      onChange();
      loadOffers();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-semibold">Prices across stores</h2>
        {via && (
          <button className="btn-ghost ml-auto" onClick={() => find(false)} disabled={busy || status?.searching}>
            {busy || status?.searching ? "Searching..." : "Refresh prices"}
          </button>
        )}
        {result?.cached && (
          <button className="btn-ghost" onClick={() => find(true)} disabled={busy} title="Uses one paid search">
            Search again
          </button>
        )}
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {offers && offers.length > 0 && (
        <div>
          <div className="label">{storeOffers.length} store{storeOffers.length === 1 ? "" : "s"}, cheapest first (before tax)</div>
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {(showAll ? storeOffers : storeOffers.slice(0, 8)).map((o, n) => (
              <li key={o.url} className="flex items-center gap-2 py-2 text-sm">
                <div className="min-w-0 flex-1">
                  <a href={o.url} target="_blank" rel="noreferrer" className={`font-medium hover:underline ${n === 0 ? "text-green-700 dark:text-green-400" : ""}`}>
                    {o.merchant}
                  </a>
                  <div className="truncate text-xs text-slate-500" title={o.title}>{o.title}</div>
                </div>
                <div className="shrink-0 text-right">
                  <div className="font-semibold">{money(o.price_cents)}</div>
                  <div className="text-xs text-slate-400">{o.shipping_cents === 0 ? "free ship" : o.shipping_cents ? `+${money(o.shipping_cents)} ship` : ""}</div>
                </div>
                <button className="shrink-0 px-1 text-xs text-slate-400 hover:text-red-600" title="Not this product: stop comparing this listing"
                  onClick={async () => { await api("/api/feedback/not-this-product", { method: "POST", json: { url: o.url, item_id: item.id, merchant: o.merchant } }); onChange(); loadOffers(); }}>Not this</button>
                {o.tracked ? <span className="w-16 shrink-0 text-center text-xs text-slate-500">{o.tracked === "confirmed" ? "watched" : o.tracked === "rejected" ? "hidden" : o.tracked}</span>
                  : o.store_link ? <button className="btn-ghost w-16 shrink-0 px-2 py-1 text-xs" onClick={() => track(o.url)} title="Check this store's page on a schedule">Track</button>
                  : <span className="w-16 shrink-0 text-center text-[11px] text-slate-400" title="Google Shopping did not give this store's own link">Google</span>}
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
            {storeOffers.length > 8 && <button className="hover:underline" onClick={() => setShowAll(!showAll)}>{showAll ? "Show fewer" : `Show all ${storeOffers.length}`}</button>}
            <span>Seen {ago(offers[0].seen_at)} in search results; refreshed about daily.</span>
          </div>
          {otherOffers.length > 0 && (
            <details className="mt-2 text-xs">
              <summary className="cursor-pointer text-slate-500">{otherOffers.length} marketplace or other listing{otherOffers.length === 1 ? "" : "s"} (not counted)</summary>
              <ul className="mt-1 space-y-1">
                {otherOffers.map((o) => (
                  <li key={o.url} className="flex gap-2">
                    <a href={o.url} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate hover:underline" title={o.title}>{o.merchant}: {o.title}</a>
                    <span className="shrink-0">{money(o.price_cents)}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
      {status?.searching && <p className="text-sm text-slate-500">Checking Canadian stores ({via})… every store found is watched automatically.</p>}
      {!via && <p className="text-sm text-slate-500">To find this at other stores automatically, the household admin adds a Claude key (Household admin) or a SerpApi key.</p>}

      {rejected.length > 0 && (
        <div className="text-xs">
          <button className="text-slate-500 hover:underline" onClick={() => setShowRejected(!showRejected)}>
            {showRejected ? "Hide" : "Show"} {rejected.length} hidden store{rejected.length > 1 ? "s" : ""}
          </button>
          {showRejected && (
            <ul className="mt-1 space-y-1">
              {rejected.map((s) => (
                <li key={s.id} className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate">{s.retailer_name}: {s.title || s.url}</span>
                  <button className="btn-ghost px-2 py-0.5 text-xs" onClick={() => setStatus(s.id, "confirmed")}>Watch again</button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
