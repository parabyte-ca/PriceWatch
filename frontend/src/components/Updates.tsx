import { useEffect, useRef, useState } from "react";
import { api, localTime } from "../api";

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
}

export default function Updates() {
  const [s, setS] = useState<UpdateState | null>(null);
  const [error, setError] = useState("");
  const [choice, setChoice] = useState("");
  const logRef = useRef<HTMLPreElement>(null);

  const load = () => api<UpdateState>("/api/admin/updates").then((d) => { setS(d); setError(""); })
    .catch((e) => setError((e as Error).message));
  const busy = s?.pending || s?.status?.state === "running";
  useEffect(() => { load(); }, []);
  useEffect(() => {
    // poll quickly while an update runs; the app restarts during an update, so errors are expected briefly
    const t = setInterval(load, busy ? 3000 : 30000);
    return () => clearInterval(t);
  }, [busy]);
  useEffect(() => { logRef.current?.scrollTo(0, logRef.current.scrollHeight); }, [s?.log.length]);

  const send = (json: object) => api("/api/admin/updates", { method: "POST", json }).then(load).catch((e) => setError((e as Error).message));

  if (!s) return <div className="card text-sm text-slate-500">{error || "Loading updates..."}</div>;
  const st = s.status;
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
      {s.pending && <p className="text-sm text-blue-700">Waiting for the host agent (it runs every minute)...</p>}
      {st?.state && (
        <p className={`text-sm ${st.state === "failed" || st.state === "rejected" ? "text-red-700" : st.state === "succeeded" ? "text-green-700" : "text-blue-700"}`}>
          {st.state === "running" ? `Updating${st.version && st.version !== "-" ? ` to v${st.version}` : ""}, started ${localTime(st.started_at)}...` :
            st.state === "succeeded" ? `${st.action === "rollback" ? "Rollback" : `Update to v${st.version}`} finished ${localTime(st.finished_at)}.` :
            st.state === "failed" ? `${st.action} failed (exit ${st.exit_code}); update.sh rolled back automatically if it could. See the log.` :
            st.message || st.state}
        </p>
      )}
      {s.log.length > 0 && (
        <pre ref={logRef} className="max-h-72 overflow-auto rounded bg-slate-900 p-2 text-xs text-slate-100">{s.log.join("\n")}</pre>
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}
