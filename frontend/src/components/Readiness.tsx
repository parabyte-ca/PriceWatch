import { useState } from "react";
import { api } from "../api";

interface Check { key: string; status: "ok" | "warn" | "fail"; title: string; detail: string }
interface Load { domain: string; requests_per_hour: number; capacity_per_hour: number; load_pct: number }
interface Result { overall: string; checks: Check[]; load: Load[]; generated_at: string }

const ICON = { ok: "✓", warn: "!", fail: "✗" };
const TONE = { ok: "text-green-700 dark:text-green-400", warn: "text-amber-600", fail: "text-red-600" };

export default function Readiness() {
  const [r, setR] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = () => {
    setBusy(true); setError("");
    api<Result>("/api/admin/readiness").then(setR).catch((e) => setError(e.message)).finally(() => setBusy(false));
  };
  return (
    <div className="card space-y-2 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">Sale-mode readiness</h2>
        <button className="btn-ghost" disabled={busy} onClick={run}>{busy ? "Checking..." : r ? "Check again" : "Run checks"}</button>
      </div>
      <p className="text-xs text-slate-500">
        Before Black Friday or Boxing Week: store health, stale prices, alert delivery, backups, and a dry run of the faster
        schedule against each store's polite limit.
      </p>
      {error && <p className="text-red-600">{error}</p>}
      {r && (
        <>
          {r.checks.map((c) => (
            <div key={c.key} className="flex gap-2 border-t border-slate-100 pt-2 dark:border-slate-800">
              <span className={`w-4 shrink-0 font-bold ${TONE[c.status]}`}>{ICON[c.status]}</span>
              <div className="min-w-0">
                <div className="font-medium">{c.title}</div>
                {c.detail && <div className="break-words text-xs text-slate-500">{c.detail}</div>}
              </div>
            </div>
          ))}
          {r.load.length > 0 && (
            <details className="pt-1">
              <summary className="cursor-pointer text-xs text-slate-500">Sale-mode load by store</summary>
              <div className="mt-1 space-y-1">
                {r.load.map((l) => (
                  <div key={l.domain} className="text-xs">
                    <div className="flex justify-between gap-2"><span className="truncate">{l.domain}</span><span>{l.requests_per_hour}/h of {l.capacity_per_hour}/h</span></div>
                    <div className="h-1.5 overflow-hidden rounded bg-slate-200 dark:bg-slate-800">
                      <div className={`h-1.5 ${l.load_pct > 100 ? "bg-red-600" : l.load_pct > 70 ? "bg-amber-500" : "bg-green-600"}`} style={{ width: `${Math.min(100, l.load_pct)}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </details>
          )}
        </>
      )}
    </div>
  );
}
