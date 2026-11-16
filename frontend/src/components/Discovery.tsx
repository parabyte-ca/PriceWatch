import { useEffect, useState } from "react";
import { api, DiscoveryResult, Item, money } from "../api";

const pct = (n: number | null) => (n == null ? "" : `${Math.round(n * 100)}%`);

export function Suggestions({ item, onChange }: { item: Item; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<DiscoveryResult | null>(null);
  const [error, setError] = useState("");
  const [showRejected, setShowRejected] = useState(false);
  const [status, setStatusInfo] = useState<{ searching: boolean; provider: string | null } | null>(null);
  // a search starts by itself when an item is added; show it and refresh when it finishes
  useEffect(() => {
    let stop = false;
    let was = false;
    const poll = () => api<{ searching: boolean; provider: string | null }>(`/api/items/${item.id}/discover`).then((st) => {
      if (stop) return;
      setStatusInfo(st);
      if (was && !st.searching) onChange();
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

      {result && (
        <details className="text-sm" open={result.added === 0}>
          <summary className="cursor-pointer text-slate-500">
            {result.candidates.length} results for "{result.query}" via {result.provider}
            {result.cached ? " (cached, no search used)" : ""}, {result.added} new suggestions.
            {result.limit ? ` ${result.usage}/${result.limit} searches used this month.` : ""}
          </summary>
          <ul className="mt-2 space-y-1">
            {result.candidates.map((c) => (
              <li key={c.url} className="flex gap-2 text-xs">
                <span className={`w-28 shrink-0 font-medium ${c.accepted ? "text-green-700" : "text-slate-500"}`}>{c.status}</span>
                <span className="w-16 shrink-0 text-right">{money(c.price_cents)}</span>
                <span className="min-w-0 flex-1 truncate" title={c.title}>
                  {c.merchant ? `${c.merchant}: ` : ""}{c.title}
                  <span className="text-slate-400"> · {[...c.reasons, ...c.exclusions].join("; ")}</span>
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}

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
