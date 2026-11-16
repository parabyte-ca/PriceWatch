import { useEffect, useRef, useState } from "react";
import { api, localTime } from "../api";
import { isActive, parseTs, readPending, RECENT_MS, writePending, type UpdateProgressInfo } from "../lib/updateProgress";
import { UpdateProgress } from "./UpdateProgress";

interface UpdateState {
  current: string;
  latest: string | null;
  update_available: boolean;
  versions: string[];
  checked_at: string | null;
  agent_installed: boolean;
  agent_online: boolean;
  agent_last_run: string | null;
  status: { state?: string; action?: string; version?: string; message?: string; started_at?: string;
    finished_at?: string; exit_code?: string; requested_by?: string } | null;
  pending: boolean;
  log: string[];
  progress: UpdateProgressInfo;
  history: { action?: string; version?: string; state?: string; from_version?: string; to_version?: string; started_at?: string;
    finished_at?: string; requested_by?: string; rolled_back?: string }[];
}

const took = (a?: string, b?: string) => {
  const x = parseTs(a), y = parseTs(b);
  if (x == null || y == null) return "";
  const s = Math.round((y - x) / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

export default function Updates() {
  const [s, setS] = useState<UpdateState | null>(null);
  const [error, setError] = useState("");
  const [offline, setOffline] = useState(false);
  const [choice, setChoice] = useState("");
  const logRef = useRef<HTMLPreElement>(null);

  const load = () => api<UpdateState>("/api/admin/updates").then((d) => {
    setS(d); setError(""); setOffline(false);
    if (!isActive(d.progress.state) && d.progress.state !== "idle") writePending(null);
  }).catch((e) => {
    // PriceWatch restarts during an update: not answering then is expected
    if (readPending()) setOffline(true); else setError((e as Error).message);
  });
  const busy = s?.pending || s?.status?.state === "running" || isActive(s?.progress.state) || (offline && !!readPending());
  useEffect(() => { load(); }, []);
  useEffect(() => {
    // poll quickly while an update runs; the app restarts during an update, so errors are expected briefly
    const t = setInterval(load, busy ? 2000 : 30000);
    return () => clearInterval(t);
  }, [busy]);
  useEffect(() => { logRef.current?.scrollTo(0, logRef.current.scrollHeight); }, [s?.log.length]);

  const send = (json: { action: string; version?: string }) => api("/api/admin/updates", { method: "POST", json })
    .then(() => {
      if (json.action !== "check") writePending({ to: json.version ?? null, from: s?.current ?? "", action: json.action as "update" | "rollback", at: Date.now() });
      return load();
    }).catch((e) => setError((e as Error).message));
  const p = s?.progress;
  const finishedAt = parseTs(p?.status?.finished_at);
  const showProgress = !!p && (isActive(p.state) || (offline && !!readPending()) ||
    ((p.state === "succeeded" || p.state === "failed") && finishedAt != null && Date.now() - finishedAt < RECENT_MS));

  if (!s) return <div className="card text-sm text-slate-500">{error || "Loading updates..."}</div>;
  return (
    <div className="card space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-semibold">Updates</h2>
        <span className="text-sm">Running v{s.current}</span>
        {s.update_available && <span className="rounded-full bg-green-600 px-2 py-0.5 text-xs font-bold text-white">v{s.latest} available</span>}
        <span className={`ml-auto text-xs ${s.agent_online ? "text-green-700" : "text-amber-700"}`}>
          {s.agent_installed ? (s.agent_online ? "Host agent online" : `Host agent last seen ${localTime(s.agent_last_run)}`) : "Host agent not installed"}
        </span>
      </div>
      {!s.agent_installed && (
        <p className="text-sm text-amber-800">
          Install the agent once on TrueNAS: <code>cd /mnt/shared_vol/websites/pricewatch && sudo scripts/upgrade-agent.sh --install</code>
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <select className="input w-auto" value={choice} onChange={(e) => setChoice(e.target.value)} disabled={busy || !s.versions.length}>
          <option value="">{s.versions.length ? "Choose a release" : "No releases listed yet"}</option>
          {s.versions.map((v) => <option key={v} value={v}>v{v}{v === s.current ? " (current)" : v === s.latest ? " (latest)" : ""}</option>)}
        </select>
        <button className="btn-primary" disabled={busy || !choice || !s.agent_online || choice === s.current}
          onClick={() => confirm(`Update PriceWatch to v${choice}? The database is backed up first and the update rolls back automatically if the health check fails. The app restarts for about a minute.`) &&
            send({ action: "update", version: choice })}>Update</button>
        <button className="btn-ghost" disabled={busy || !s.agent_online} onClick={() => send({ action: "check" })}>Check for updates</button>
        <button className="btn-ghost text-red-600" disabled={busy || !s.agent_online}
          onClick={() => confirm("Roll back to the previous version and restore the database from before the last update?") && send({ action: "rollback" })}>
          Roll back
        </button>
        {s.checked_at && <span className="text-xs text-slate-500">Checked {localTime(s.checked_at)}</span>}
      </div>
      {showProgress && p && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-950/60">
          <UpdateProgress progress={p} current={s.current} offline={offline} />
        </div>
      )}
      {s.history.length > 0 && (
        <details>
          <summary className="cursor-pointer text-sm text-slate-500">Update history</summary>
          <ul className="mt-2 space-y-1 text-xs">
            {s.history.map((h, i) => (
              <li key={i} className="flex flex-wrap justify-between gap-x-3">
                <span>
                  <span className={h.state === "succeeded" ? "text-green-700 dark:text-green-400" : "text-red-600"}>{h.state === "succeeded" ? "✓" : "✗"}</span>{" "}
                  {h.action === "rollback" ? "Rolled back" : "Updated"} v{h.from_version} → v{h.to_version || h.version}
                  {h.rolled_back === "yes" && " (rolled back automatically)"}
                </span>
                <span className="text-slate-500">{localTime(h.finished_at)} · {took(h.started_at, h.finished_at)}{h.requested_by ? ` · ${h.requested_by}` : ""}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
      {s.log.length > 0 && (
        <details>
          <summary className="cursor-pointer text-sm text-slate-500">Full log</summary>
          <pre ref={logRef} className="mt-2 max-h-72 overflow-auto rounded bg-slate-900 p-2 text-xs text-slate-100">{s.log.join("\n")}</pre>
        </details>
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}
