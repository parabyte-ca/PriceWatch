import { useEffect, useState } from "react";
import { ago, api, localTime, money, toCents, toDollars } from "../api";
import ClaudeSetup from "../components/ClaudeSetup";
import Readiness from "../components/Readiness";
import { Diagnose, Perks } from "../components/Tools";
import Updates from "../components/Updates";
import { useSession } from "../session";

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
  search_providers: { name: string; used_this_month: number; limit: number }[];
  domains: { domain: string; day: Health | null; week: Health | null; backoff_until: string | null }[];
  recent_runs: { id: number; domain: string; started_at: string; duration_ms: number | null; status: string;
    http_status: number | null; method: string | null; error: string | null }[];
}
interface Retailer { id: number; domain: string; name: string; fetch_mode: string; respect_robots: boolean;
  price_match: boolean; free_shipping_threshold_cents: number | null; default_shipping_cents: number | null; backoff_until: string | null; selectors: Record<string, string> | null }

const rateClass = (r: number | null | undefined) =>
  r == null ? "" : r >= 90 ? "text-green-700" : r >= 50 ? "text-amber-600" : "text-red-600";

interface Policy { id: number; domain: string; competitor_match: boolean; own_price_adjustment: boolean;
  window_days: number | null; excluded_events: string[] | null; verified: boolean; enabled: boolean; notes: string | null;
  event_guarantee: string | null }

export default function SystemPage() {
  const { user } = useSession();
  const [policies, setPolicies] = useState<Policy[]>([]);
  const loadPolicies = () => api<Policy[]>("/api/policies").then(setPolicies).catch(() => {});
  useEffect(() => { loadPolicies(); }, []);
  const patchPolicy = (id: number, json: object) => api(`/api/policies/${id}`, { method: "PATCH", json }).then(loadPolicies);
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
      {user?.role === "admin" && <Readiness />}
      {user?.role === "admin" && <ClaudeSetup />}
      {user?.role === "admin" && <Updates />}
      {user?.role === "admin" && <Diagnose />}
      <Perks admin={user?.role === "admin"} />
      <div className="card grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div><div className="label">Version</div>{data.version}</div>
        <div><div className="label">Items / sources</div>{data.items} / {data.sources}</div>
        <div><div className="label">Due now</div>{data.due_now}</div>
        <div><div className="label">Scheduler / browser</div>{data.scheduler_enabled ? "on" : "off"} / {data.browser_enabled ? "on" : "off"}</div>
        <div className="col-span-2 sm:col-span-4">
          <div className="label">Search providers</div>
          {data.search_providers.length
            ? data.search_providers.map((p) => (
                <span key={p.name} className="mr-4">{p.name}: {p.used_this_month}{p.limit ? `/${p.limit}` : ""} searches this month</span>
              ))
            : "None configured (set SERPAPI_KEY or BRIGHTDATA_API_KEY)"}
        </div>
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
            <th className="th">Free shipping from</th><th className="th">Shipping</th><th className="th"></th>
          </tr></thead>
          <tbody>
            {used.map((r) => (
              <tr key={r.id} className="border-t border-slate-100 dark:border-slate-800">
                <td className="td">{r.name}<div className="text-xs text-slate-500">{r.domain}</div></td>
                <td className="td">
                  <select className="input w-auto py-1" value={r.fetch_mode} onChange={(e) => patch(r.id, { fetch_mode: e.target.value })}>
                    <option value="auto">auto</option><option value="http">http only</option><option value="browser">browser</option>
                    {r.domain === "bestbuy.ca" && <option value="bestbuy_api">product JSON (beta)</option>}
                    <option value="keepa">keepa</option><option value="manual">manual only</option>
                  </select>
                </td>
                <td className="td">
                  <input type="checkbox" checked={r.respect_robots} onChange={(e) => patch(r.id, { respect_robots: e.target.checked })} /> respect
                </td>
                <td className="td">
                  <input className="input w-24 py-1" inputMode="decimal" placeholder="n/a" defaultValue={toDollars(r.free_shipping_threshold_cents)}
                    title={`Current: ${money(r.free_shipping_threshold_cents)}`}
                    onBlur={(e) => toCents(e.target.value) !== r.free_shipping_threshold_cents &&
                      patch(r.id, { free_shipping_threshold_cents: toCents(e.target.value) })} />
                </td>
                <td className="td">
                  <input className="input w-20 py-1" inputMode="decimal" placeholder="?" defaultValue={toDollars(r.default_shipping_cents)}
                    onBlur={(e) => toCents(e.target.value) !== r.default_shipping_cents &&
                      patch(r.id, { default_shipping_cents: toCents(e.target.value) })} />
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
        <h2 className="mb-2 font-semibold">Price match and protection policies</h2>
        <p className="mb-2 text-xs text-slate-500">Policies change; confirm with the retailer before relying on one. Unverified policies stay off until you enable them.</p>
        <table className="w-full text-sm">
          <thead><tr><th className="th">Retailer</th><th className="th">Matches competitors</th><th className="th">Own price adjustment</th>
            <th className="th">Excludes</th><th className="th">Verified</th><th className="th">On</th></tr></thead>
          <tbody>
            {policies.map((p) => (
              <tr key={p.id} className="border-t border-slate-100 align-top dark:border-slate-800">
                <td className="td">{p.domain}<div className="max-w-md text-xs text-slate-500">{p.notes}</div>
                  {p.event_guarantee && <div className="max-w-md text-xs text-teal-700">{p.event_guarantee}</div>}</td>
                <td className="td">{p.competitor_match ? "yes" : "no"}</td>
                <td className="td">{p.own_price_adjustment ? `${p.window_days} days` : "no"}</td>
                <td className="td text-xs">{(p.excluded_events || []).join(", ").replace(/_/g, " ")}</td>
                <td className="td"><input type="checkbox" checked={p.verified} onChange={(e) => patchPolicy(p.id, { verified: e.target.checked })} /></td>
                <td className="td"><input type="checkbox" checked={p.enabled} onChange={(e) => patchPolicy(p.id, { enabled: e.target.checked })} /></td>
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
