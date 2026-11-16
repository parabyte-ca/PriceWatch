import { useEffect, useState } from "react";
import { api } from "../api";

interface Health { ok: boolean; issues: string[]; stores: { domain: string; checks: number; success_pct: number | null; paused: boolean }[];
  searches: { provider: string; used: number; limit: number | null; pace: number | null }[];
  claude: { key: boolean; spent_usd: number; cap_usd: number | null } }

/** System: what is failing and how much of the search and Claude budgets is used. */
export default function HealthCheck() {
  const [h, setH] = useState<Health | null>(null);
  const load = () => api<Health>("/api/admin/health").then(setH).catch(() => {});
  useEffect(() => { load(); }, []);
  if (!h) return null;
  return (
    <div className="card space-y-2 text-sm">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-semibold">Health check</h2>
        <button className="btn-ghost px-2 py-1 text-xs" onClick={load}>Run again</button>
      </div>
      {h.ok ? <p className="text-green-700 dark:text-green-400">All good: stores, searches, Claude, the forum feed and backups.</p> : (
        <ul className="list-disc space-y-1 pl-5 text-amber-700 dark:text-amber-400">{h.issues.map((i) => <li key={i}>{i}</li>)}</ul>
      )}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
        {h.searches.map((s) => <span key={s.provider}>{s.provider}: {s.used}{s.limit ? ` of ${s.limit}` : ""} searches{s.pace ? ` (pace ${s.pace})` : ""}</span>)}
        {h.claude.key && <span>Claude: US${h.claude.spent_usd.toFixed(2)}{h.claude.cap_usd ? ` of US$${h.claude.cap_usd}` : ""}</span>}
      </div>
      {h.stores.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-slate-500">Stores this week</summary>
          <ul className="mt-1 space-y-0.5">
            {h.stores.map((s) => (
              <li key={s.domain} className="flex justify-between gap-2">
                <span>{s.domain}{s.paused ? " (paused after blocks)" : ""}</span>
                <span className={s.success_pct != null && s.success_pct < 50 ? "text-red-600" : ""}>{s.success_pct ?? "–"}% of {s.checks}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
