import { useEffect, useState } from "react";
import { ago, api, DiscoveryResult, Item, money, Offer } from "../api";

const pct = (n: number | null) => (n == null ? "" : `${Math.round(n * 100)}%`);

export function Suggestions({ item, onChange }: { item: Item; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<DiscoveryResult | null>(null);
  const [error, setError] = useState("");
  const [showRejected, setShowRejected] = useState(false);
  const [status, setStatusInfo] = useState<{ searching: boolean; provider: string | null } | null>(null);
  const [offers, setOffers] = useState<Offer[] | null>(null);
  const [showAll, setShowAll] = useState(false);
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
  const suggested = (item.sources || []).filter((s) => s.status === "suggested");
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
        <h2 className="font-semibold">Other stores</h2>
        {via && (
          <button className="btn-ghost ml-auto" onClick={() => find(false)} disabled={busy || status?.searching}>
            {busy || status?.searching ? "Searching..." : "Search other stores"}
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
          <div className="label">Prices across {offers.length} store{offers.length === 1 ? "" : "s"}, cheapest first (before tax)</div>
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {(showAll ? offers : offers.slice(0, 8)).map((o, n) => (
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
                {o.tracked ? <span className="w-16 shrink-0 text-center text-xs text-slate-500">{o.tracked === "confirmed" ? "tracked" : o.tracked}</span>
                  : o.store_link ? <button className="btn-ghost w-16 shrink-0 px-2 py-1 text-xs" onClick={() => track(o.url)} title="Check this store's page on a schedule">Track</button>
                  : <span className="w-16 shrink-0 text-center text-[11px] text-slate-400" title="Google Shopping did not give this store's own link">Google</span>}
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
            {offers.length > 8 && <button className="hover:underline" onClick={() => setShowAll(!showAll)}>{showAll ? "Show fewer" : `Show all ${offers.length}`}</button>}
            <span>Seen {ago(offers[0].seen_at)} in search results; refreshed about daily. Prices can include sellers on a store's marketplace.</span>
          </div>
        </div>
      )}
      {status?.searching && <p className="text-sm text-slate-500">Looking for this at other Canadian stores ({via})… Matches with the same model number or barcode start being tracked automatically.</p>}
      {!via && <p className="text-sm text-slate-500">To find this at other stores automatically, the household admin adds a Claude key (Household admin) or a SerpApi key.</p>}

      {suggested.length > 0 && (
        <div>
          <div className="label">Suggested listings: confirm to start tracking</div>
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {suggested.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                <div className="min-w-0 flex-1">
                  <a href={s.url} target="_blank" rel="noreferrer" className="font-medium hover:underline">
                    {s.retailer_name || s.match_reasons?.merchant || s.url}
                  </a>
                  <div className="truncate text-xs text-slate-500">{s.title}</div>
                  <div className="text-xs text-slate-500">
                    {s.match_method} match {pct(s.match_confidence)} · {(s.match_reasons?.reasons || []).join("; ")}
                  </div>
                </div>
                <div className="text-right">
                  {money(s.match_reasons?.serp_price_cents)}
                  <div className="text-xs text-slate-400">search price</div>
                </div>
                <button className="btn-primary px-2 py-1 text-xs" onClick={() => setStatus(s.id, "confirmed")}>Confirm</button>
                <button className="btn-ghost px-2 py-1 text-xs" onClick={() => setStatus(s.id, "rejected")}>Reject</button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {result && (() => {
        const linked = result.candidates.filter((c) => c.status !== "no merchant link");
        const hidden = result.candidates.length - linked.length;
        const row = (c: DiscoveryResult["candidates"][number]) => (
          <li key={c.url} className="flex gap-2 text-xs">
            <span className={`w-24 shrink-0 font-medium ${c.status === "confirmed" || c.status === "suggested" ? "text-green-700" : "text-slate-500"}`}>{c.status}</span>
            <span className="w-16 shrink-0 text-right">{money(c.price_cents)}</span>
            {c.status === "no merchant link" ? (
              <span className="min-w-0 flex-1 truncate" title={c.title}>{c.merchant ? `${c.merchant}: ` : ""}{c.title}</span>
            ) : (
              <a href={c.url} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate hover:underline" title={c.title}>
                {c.merchant ? `${c.merchant}: ` : ""}{c.title}
                <span className="text-slate-400"> · {[...c.reasons, ...c.exclusions].join("; ")}</span>
              </a>
            )}
          </li>
        );
        return (
          <details className="text-sm" open={result.added === 0}>
            <summary className="cursor-pointer text-slate-500">
              {linked.length} store link{linked.length === 1 ? "" : "s"} for "{result.query}" via {result.provider}
              {result.cached ? " (cached, no search used)" : ""}, {result.added} new.
              {result.limit ? ` ${result.usage}/${result.limit} searches used this month.` : ""}
            </summary>
            {(result.notes || []).map((n) => <p key={n} className="mt-1 text-xs text-amber-700">{n}</p>)}
            <ul className="mt-2 space-y-1">{linked.map(row)}</ul>
            {hidden > 0 && (
              <details className="mt-2 text-xs">
                <summary className="cursor-pointer text-slate-500">
                  {hidden} Google Shopping result{hidden === 1 ? "" : "s"} without a store link (prices for reference only)
                </summary>
                <ul className="mt-1 space-y-1">{result.candidates.filter((c) => c.status === "no merchant link").map(row)}</ul>
              </details>
            )}
          </details>
        );
      })()}

      {rejected.length > 0 && (
        <div className="text-xs">
          <button className="text-slate-500 hover:underline" onClick={() => setShowRejected(!showRejected)}>
            {showRejected ? "Hide" : "Show"} {rejected.length} rejected listing{rejected.length > 1 ? "s" : ""}
          </button>
          {showRejected && (
            <ul className="mt-1 space-y-1">
              {rejected.map((s) => (
                <li key={s.id} className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate">{s.retailer_name}: {s.title || s.url}</span>
                  <button className="btn-ghost px-2 py-0.5 text-xs" onClick={() => setStatus(s.id, "suggested")}>Restore</button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
