import { useEffect, useState } from "react";
import { api } from "../api";

interface SettingsData {
  province: string;
  target_basis: string;
  quiet_hours_enabled: boolean;
  quiet_hours_start: string;
  quiet_hours_end: string;
  target_bypasses_quiet_hours: boolean;
  notify_urls: string[];
  env_notify_urls: string[];
  alert_target: boolean;
  alert_drop: boolean;
  alert_drop_pct: number;
  alert_all_time_low: boolean;
  alert_back_in_stock: boolean;
  alert_source_failing: boolean;
  fake_sale_pct: number;
  good_within_pct: number;
  browser_fallback: boolean;
  provinces: Record<string, { name: string; rate: number }>;
  timezone: string;
}

export default function SettingsPage() {
  const [s, setS] = useState<SettingsData | null>(null);
  const [urls, setUrls] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const load = () =>
    api<SettingsData>("/api/settings").then((d) => {
      setS(d);
      setUrls(d.notify_urls.join("\n"));
    });
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, []);

  if (!s) return <div className="text-slate-500">{error || "Loading..."}</div>;
  const set = <K extends keyof SettingsData>(k: K, v: SettingsData[K]) => setS({ ...s, [k]: v });

  const save = async () => {
    setError("");
    try {
      const { provinces: _p, env_notify_urls: _e, timezone: _t, ...rest } = s;
      await api("/api/settings", { method: "PATCH", json: { ...rest, notify_urls: urls.split("\n").map((u) => u.trim()).filter(Boolean) } });
      await load();
      setMsg("Saved");
      setTimeout(() => setMsg(""), 3000);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const test = async () => {
    setError("");
    try {
      const a = await api<{ status: string; error: string | null }>("/api/settings/test-alert", { method: "POST" });
      setMsg(a.status === "sent" ? "Test alert sent" : `Test alert ${a.status}: ${a.error || ""}`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const Toggle = ({ k, label }: { k: keyof SettingsData; label: string }) => (
    <label className="flex items-center gap-2 text-sm">
      <input type="checkbox" checked={Boolean(s[k])} onChange={(e) => set(k, e.target.checked as never)} /> {label}
    </label>
  );

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="card space-y-3">
        <h2 className="font-semibold">Prices</h2>
        <div>
          <label className="label">Province (sales tax)</label>
          <select className="input" value={s.province} onChange={(e) => set("province", e.target.value)}>
            {Object.entries(s.provinces).map(([code, p]) => (
              <option key={code} value={code}>{p.name} ({p.rate}%)</option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Compare targets against</label>
          <select className="input" value={s.target_basis} onChange={(e) => set("target_basis", e.target.value)}>
            <option value="price">Price before tax</option>
            <option value="landed">Landed price (tax and shipping)</option>
          </select>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label">Fake sale if less than % below median</label>
            <input className="input" type="number" step="0.5" value={s.fake_sale_pct} onChange={(e) => set("fake_sale_pct", Number(e.target.value))} />
          </div>
          <div>
            <label className="label">"Good" within % of low</label>
            <input className="input" type="number" step="0.5" value={s.good_within_pct} onChange={(e) => set("good_within_pct", Number(e.target.value))} />
          </div>
        </div>
        <Toggle k="browser_fallback" label="Use the browser sidecar when a page has no price (if enabled in .env)" />
      </div>

      <div className="card space-y-3">
        <h2 className="font-semibold">Notifications</h2>
        <div>
          <label className="label">Apprise URLs, one per line</label>
          <textarea className="input font-mono" rows={3} placeholder="ntfys://ntfy.sh/your-private-topic" value={urls}
            onChange={(e) => setUrls(e.target.value)} />
          <p className="mt-1 text-xs text-slate-500">
            Saved URLs are shown masked; leave a masked line unchanged to keep it. ntfy, Gotify, Pushover, email, Telegram,
            Discord and Home Assistant all work.
            {s.env_notify_urls.length > 0 && ` Also from .env: ${s.env_notify_urls.join(", ")}.`}
          </p>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Toggle k="alert_target" label="At or below target" />
          <Toggle k="alert_all_time_low" label="New all-time low" />
          <Toggle k="alert_back_in_stock" label="Back in stock" />
          <Toggle k="alert_source_failing" label="Source failing 24 h" />
          <Toggle k="alert_drop" label="Drop of at least" />
          <input className="input w-24" type="number" value={s.alert_drop_pct} onChange={(e) => set("alert_drop_pct", Number(e.target.value))} />
        </div>
        <div className="space-y-2 border-t border-slate-200 pt-3 dark:border-slate-800">
          <Toggle k="quiet_hours_enabled" label={`Quiet hours (${s.timezone})`} />
          <div className="flex gap-2">
            <input className="input" type="time" value={s.quiet_hours_start} onChange={(e) => set("quiet_hours_start", e.target.value)} />
            <input className="input" type="time" value={s.quiet_hours_end} onChange={(e) => set("quiet_hours_end", e.target.value)} />
          </div>
          <Toggle k="target_bypasses_quiet_hours" label="Target hits still alert during quiet hours" />
        </div>
        <button className="btn-ghost" onClick={test}>Send test alert</button>
      </div>

      <div className="md:col-span-2 flex items-center gap-3">
        <button className="btn-primary" onClick={save}>Save settings</button>
        {msg && <span className="text-sm text-green-700">{msg}</span>}
        {error && <span className="text-sm text-red-600">{error}</span>}
      </div>
    </div>
  );
}
