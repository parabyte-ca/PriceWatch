import { useEffect, useState } from "react";
import { api } from "../api";
import Account from "../components/Account";
import PushToggle from "../components/PushToggle";

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
  match_threshold: number;
  auto_confirm_gtin: boolean;
  serp_monthly_limit: number;
  discover_on_add: boolean;
  buy_within_pct: number;
  protect_within_pct: number;
  season_start: string;
  blackfriday_mode: boolean;
  blackfriday_start: string;
  blackfriday_end: string;
  boxingweek_mode: boolean;
  boxingweek_start: string;
  boxingweek_end: string;
  llm_match_enabled: boolean;
  llm_available?: boolean;
  digest_enabled: boolean;
  digest_time: string;
  digest_time_blackfriday: string;
  my_best_buy_member: boolean;
  alert_domain_blocked: boolean;
  is_admin: boolean;
  alert_deal_feed: boolean;
  deal_feed_enabled: boolean;
  flyers_enabled: boolean;
  postal_code: string;
  alert_flyer: boolean;
  weekly_report_enabled: boolean;
  email_import_enabled: boolean;
  email_import_llm: boolean;
  order_email_from: string;
  min_claim_cents: number;
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
      const { provinces: _p, env_notify_urls: _e, timezone: _t, is_admin: _a, user_keys: _u, llm_available: _l, ...rest } = s as SettingsData & { user_keys?: string[] };
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
        <h2 className="font-semibold">Your prices</h2>
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
        {s.is_admin && <Toggle k="browser_fallback" label="Use the browser sidecar when a page has no price (household)" />}
      </div>

      <div className="card space-y-3">
        <h2 className="font-semibold">Buy rule, Black Friday mode and digest</h2>
        {s.is_admin ? <><div className="grid grid-cols-2 items-end gap-3">
          <div>
            <label className="label">BUY within % of seasonal low</label>
            <input className="input" type="number" step="0.5" value={s.buy_within_pct} onChange={(e) => set("buy_within_pct", Number(e.target.value))} />
          </div>
          <div>
            <label className="label">BUY + PROTECT within %</label>
            <input className="input" type="number" step="0.5" value={s.protect_within_pct} onChange={(e) => set("protect_within_pct", Number(e.target.value))} />
          </div>
          <div>
            <label className="label">Season starts</label>
            <input className="input" type="date" value={s.season_start} onChange={(e) => set("season_start", e.target.value)} />
          </div>
        </div>
        <Toggle k="blackfriday_mode" label="Black Friday mode: hot items every 30 minutes (top 25), twice-daily digest" />
        <div className="flex gap-2">
          <input className="input" type="datetime-local" value={s.blackfriday_start} onChange={(e) => set("blackfriday_start", e.target.value)} />
          <input className="input" type="datetime-local" value={s.blackfriday_end} onChange={(e) => set("blackfriday_end", e.target.value)} />
        </div>
        <Toggle k="boxingweek_mode" label="Boxing Week mode: the same faster schedule after Christmas" />
        <div className="flex gap-2">
          <input className="input" type="datetime-local" value={s.boxingweek_start} onChange={(e) => set("boxingweek_start", e.target.value)} />
          <input className="input" type="datetime-local" value={s.boxingweek_end} onChange={(e) => set("boxingweek_end", e.target.value)} />
        </div></> : <p className="text-xs text-slate-500">The buy rule and Black Friday dates are set by the household admin.</p>}
        <Toggle k="my_best_buy_member" label="I am a My Best Buy member (60-day window)" />
        <Toggle k="digest_enabled" label="Daily digest" />
        <div className="flex gap-2">
          <input className="input" type="time" value={s.digest_time} onChange={(e) => set("digest_time", e.target.value)} title="Daily" />
          <input className="input" type="time" value={s.digest_time_blackfriday} onChange={(e) => set("digest_time_blackfriday", e.target.value)} title="Second digest in Black Friday mode" />
        </div>
        <button className="btn-ghost" onClick={async () => {
          const d = await api<{ title: string; body: string }>("/api/digest/preview");
          alert(`${d.title}\n\n${d.body}`);
        }}>Preview digest</button>
      </div>

      {s.is_admin && <div className="card space-y-3">
        <h2 className="font-semibold">Discovery and matching (household)</h2>
        <div className="grid grid-cols-2 items-end gap-3">
          <div>
            <label className="label">Title match threshold (%)</label>
            <input className="input" type="number" min={50} max={100} value={s.match_threshold}
              onChange={(e) => set("match_threshold", Number(e.target.value))} />
          </div>
          <div>
            <label className="label">Searches per month (0 = no limit)</label>
            <input className="input" type="number" min={0} value={s.serp_monthly_limit}
              onChange={(e) => set("serp_monthly_limit", Number(e.target.value))} />
          </div>
        </div>
        <Toggle k="discover_on_add" label="Search automatically when adding an item by name" />
        <Toggle k="deal_feed_enabled" label="Watch the RedFlagDeals Hot Deals feed (every 15 minutes)" />
        <Toggle k="email_import_enabled" label="Import forwarded order emails (needs the PRICEWATCH_IMAP_* mailbox)" />
        {s.email_import_enabled && (
          <>
            <Toggle k="email_import_llm" label="Let Claude Haiku read order emails (sends the email text to Anthropic)" />
            <p className="text-xs text-slate-500">Off: PriceWatch looks for your tracked items line by line and records only those. On: Claude also reads the store, order number and every line, so less needs linking by hand.</p>
          </>
        )}
        <Toggle k="flyers_enabled" label="Match weekly flyers (Flipp search, once a day; off by default)" />
        {s.flyers_enabled && (
          <div>
            <label className="label">Postal code for flyers</label>
            <input className="input w-32 uppercase" maxLength={7} placeholder="K1A 0B1" value={s.postal_code || ""}
              onChange={(e) => set("postal_code", e.target.value.toUpperCase())} />
            <p className="mt-1 text-xs text-slate-500">Flyer prices are hints (often in-store or regional) and never count as price history. Uses an unofficial endpoint that may stop working.</p>
          </div>
        )}
        <div>
          <label className="label">Smallest price drop worth a protection claim ($)</label>
          <input className="input w-28" type="number" step="0.5" value={(s.min_claim_cents || 0) / 100}
            onChange={(e) => set("min_claim_cents", Math.round(Number(e.target.value) * 100))} />
        </div>
        <Toggle k="auto_confirm_gtin" label="Auto-confirm listings whose GTIN/UPC matches exactly" />
        <Toggle k="llm_match_enabled" label="Ask Claude Haiku about uncertain matches (scores 80 to 94)" />
        {s.llm_match_enabled && !s.llm_available && (
          <p className="text-xs text-amber-700">Set ANTHROPIC_API_KEY in .env to use this.</p>
        )}
        <p className="text-xs text-slate-500">
          Sends only the item name, brand and model and the listing title to Anthropic. Answers are cached, so each pair is asked
          once. Claude can reject a lookalike but never confirms a listing for you.
        </p>
        <p className="text-xs text-slate-500">
          Providers are enabled by SERPAPI_KEY or BRIGHTDATA_API_KEY in .env. Results are cached for 7 days per query.
          SerpApi's free plan allows 250 searches a month.
        </p>
      </div>}

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
        <div className="grid gap-2 sm:grid-cols-2">
          <Toggle k="alert_target" label="BUY / BUY + PROTECT (instant)" />
          <Toggle k="alert_back_in_stock" label="Back in stock (instant)" />
          <Toggle k="alert_deal_feed" label="RedFlagDeals thread for my items (instant; else digest)" />
          <Toggle k="alert_flyer" label="Flyer match (instant at or under target; else digest)" />
          <Toggle k="weekly_report_enabled" label="Weekly report (Sunday 18:00)" />
          <div className="sm:col-span-2">
            <label className="label">My order emails come from (the address you forward from; comma separated)</label>
            <input className="input" placeholder="you@example.com" value={s.order_email_from || ""} onChange={(e) => set("order_email_from", e.target.value)} />
          </div>
          {s.is_admin && <Toggle k="alert_domain_blocked" label="Retailer blocking checks (instant)" />}
          <Toggle k="alert_all_time_low" label="New low (instant; else digest)" />
          <Toggle k="alert_source_failing" label="Source failing 24 h (instant; else digest)" />
          <Toggle k="alert_drop" label="Drop of at least (instant; else digest)" />
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
        <PushToggle />
      </div>

      <Account />

      <div className="md:col-span-2 flex items-center gap-3">
        <button className="btn-primary" onClick={save}>Save settings</button>
        {msg && <span className="text-sm text-green-700">{msg}</span>}
        {error && <span className="text-sm text-red-600">{error}</span>}
      </div>
    </div>
  );
}
