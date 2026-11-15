import { useEffect, useState } from "react";
import { ago, api, localTime } from "../api";

interface Health { total: number; ok: number; success_rate: number | null; last: string | null; avg_ms: number }
interface SystemData {
  version: string;
  time: string;
  timezone: string;
  scheduler_enabled: boolean;
  browser_enabled: boolean;
  items: number;
  sources: number;
  due_now: number;
  domains: { domain: string; day: Health | null; week: Health | null; backoff_until: string | null }[];
  recent_runs: { id: number; domain: string; started_at: string; duration_ms: number | null; status: string;
    http_status: number | null; method: string | null; error: string | null }[];
}
interface Retailer { id: number; domain: string; name: string; fetch_mode: string; respect_robots: boolean;
  price_match: boolean; free_shipping_threshold_cents: number | null; backoff_until: string | null; selectors: Record<string, string> | null }

const rateClass = (r: number | null | undefined) =>
  r == null ? "" : r >= 90 ? "text-green-700" : r >= 50 ? "text-amber-600" : "text-red-600";

export default function SystemPage() {
  const [data, setData] = useState<SystemData | null>(null);
  const [retailers, setRetailers] = useState<Retailer[]>([]);
  const [error, setError] = useState("");

  const load = () =>
    Promise.all([api<SystemData>("/api/system"), api<Retailer[]>("/api/retailers")])
      .then(([d, r]) => {
        setData(d);
        setRetailers(r);
      })
      .catch((e) => setError(e.message));
  useEffect(() => {
    load();
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, []);

  const patch = (id: number, json: object) => api(`/api/retailers/${id}`, { method: "PATCH", json }).then(load).catch((e) => setError(e.message));

  if (!data) return <div className="text-slate-500">{error || "Loading..."}</div>;
  const used = retailers.filter((r) => data.domains.some((d) => d.domain === r.domain) || r.backoff_until);

  return (
    <div className="space-y-4">
      <div className="card grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div><div className="label">Version</div>{data.version}</div>
        <div><div className="label">Items / sources</div>{data.items} / {data.sources}</div>
        <div><div className="label">Due now</div>{data.due_now}</div>
        <div><div className="label">Scheduler / browser</div>{data.scheduler_enabled ? "on" : "off"} / {data.browser_enabled ? "on" : "off"}</div>
      </div>

      <div className="card overflow-x-auto">
        <h2 className="mb-2 font-semibold">Source health</h2>
        <table className="w-full">
          <thead><tr>
            <th className="th">Domain</th><th className="th text-right">24 h</th><th className="th text-right">7 days</th>
            <th className="th text-right">Avg</th><th className="th">Last</th><th className="th">Backoff</th>
          </tr></thead>
          <tbody>
            {data.domains.map((d) => (
              <tr key={d.domain} className="border-t border-slate-100 dark:border-slate-800">
                <td className="td">{d.domain}</td>
                <td className={`td text-right ${rateClass(d.day?.success_rate)}`}>{d.day ? `${d.day.success_rate}% (${d.day.total})` : "-"}</td>
                <td className={`td text-right ${rateClass(d.week?.success_rate)}`}>{d.week ? `${d.week.success_rate}% (${d.week.total})` : "-"}</td>
                <td className="td text-right">{d.week ? `${d.week.avg_ms} ms` : "-"}</td>
                <td className="td text-xs">{ago(d.week?.last)}</td>
                <td className="td text-xs text-amber-700">{d.backoff_until ? `until ${localTime(d.backoff_until)}` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card overflow-x-auto">
        <h2 className="mb-2 font-semibold">Retailers in use</h2>
        <table className="w-full">
          <thead><tr>
            <th className="th">Retailer</th><th className="th">Fetch mode</th><th className="th">robots.txt</th>
            <th className="th">Price match</th><th className="th"></th>
          </tr></thead>
          <tbody>
            {used.map((r) => (
              <tr key={r.id} className="border-t border-slate-100 dark:border-slate-800">
                <td className="td">{r.name}<div className="text-xs text-slate-500">{r.domain}</div></td>
                <td className="td">
                  <select className="input w-auto py-1" value={r.fetch_mode} onChange={(e) => patch(r.id, { fetch_mode: e.target.value })}>
                    <option value="auto">auto</option><option value="http">http only</option><option value="browser">browser</option>
                  </select>
                </td>
                <td className="td">
                  <input type="checkbox" checked={r.respect_robots} onChange={(e) => patch(r.id, { respect_robots: e.target.checked })} /> respect
                </td>
                <td className="td">
                  <input type="checkbox" checked={r.price_match} onChange={(e) => patch(r.id, { price_match: e.target.checked })} />
                </td>
                <td className="td text-right">
                  {r.backoff_until && <button className="btn-ghost px-2 py-1 text-xs" onClick={() => patch(r.id, { clear_backoff: true })}>Clear backoff</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card overflow-x-auto">
        <h2 className="mb-2 font-semibold">Recent fetches</h2>
        <table className="w-full text-xs">
          <thead><tr><th className="th">When</th><th className="th">Domain</th><th className="th">Status</th><th className="th">Method</th><th className="th">Error</th></tr></thead>
          <tbody>
            {data.recent_runs.map((r) => (
              <tr key={r.id} className="border-t border-slate-100 dark:border-slate-800">
                <td className="td whitespace-nowrap">{localTime(r.started_at)}</td>
                <td className="td">{r.domain}</td>
                <td className={`td ${r.status === "ok" || r.status === "not_modified" ? "text-green-700" : "text-red-600"}`}>
                  {r.status}{r.http_status ? ` (${r.http_status})` : ""}
                </td>
                <td className="td">{r.method}</td>
                <td className="td">{r.error}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
