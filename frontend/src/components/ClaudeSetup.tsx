import { useEffect, useState } from "react";
import { api } from "../api";

interface Status { enabled: boolean; model: string; effort: string; key_saved: boolean; env_key: boolean; models: string[]; efforts: string[];
  price_fallback: boolean; monthly_cap_usd: number; spend: { usd: number; checks: number; searches: number } }

const MODEL_LABEL: Record<string, string> = {
  "claude-opus-5-5": "Claude Opus 5.5 (best answers)", "claude-sonnet-5-5": "Claude Sonnet 5.5 (balanced)", "claude-haiku-5-5": "Claude Haiku 5.5 (cheapest)",
};

/** Household admin: the Claude (Anthropic) key, model and effort, like NetWatch's Admin page. */
export default function ClaudeSetup() {
  const [s, setS] = useState<Status | null>(null);
  const [key, setKey] = useState("");
  const [msg, setMsg] = useState("");
  const load = () => api<Status>("/api/admin/claude").then(setS).catch(() => {});
  useEffect(() => { load(); }, []);
  if (!s) return null;
  const save = () => api<Status>("/api/admin/claude", { method: "PUT", json: { enabled: s.enabled, model: s.model, effort: s.effort, api_key: key || null,
    price_fallback: s.price_fallback, monthly_cap_usd: Number.isFinite(Number(s.monthly_cap_usd)) ? Number(s.monthly_cap_usd) : 15 } })
    .then((r) => { setS(r); setKey(""); setMsg("Saved"); }).catch((e) => setMsg((e as Error).message));
  return (
    <div className="card space-y-3 text-sm">
      <h2 className="font-semibold">Claude (Anthropic)</h2>
      <p className="text-xs text-slate-500">
        One key powers: reading prices from stores that block PriceWatch (Best Buy, Walmart, Canadian Tire and others), finding the same
        product at other Canadian stores, Ask PriceWatch, the uncertain-match check, the weekly summary and reading order emails. The key is
        stored encrypted and never shown again. What Claude reads (item names, prices, stores) goes to Anthropic.
      </p>
      <div className="text-xs">{s.key_saved ? "A key is saved." : s.env_key ? "Using ANTHROPIC_API_KEY from .env." : "No key yet."}</div>
      <input className="input font-mono" type="password" autoComplete="off" placeholder={s.key_saved ? "Enter a new key to replace it" : "sk-ant-..."}
        value={key} onChange={(e) => setKey(e.target.value)} />
      <div className="grid gap-2 sm:grid-cols-2">
        <select className="input" value={s.model} onChange={(e) => setS({ ...s, model: e.target.value })} aria-label="Model">
          {s.models.map((m) => <option key={m} value={m}>{MODEL_LABEL[m] ?? m}</option>)}
        </select>
        <select className="input" value={s.effort} onChange={(e) => setS({ ...s, effort: e.target.value })} aria-label="Effort">
          {s.efforts.map((e) => <option key={e} value={e}>Effort: {e}</option>)}
        </select>
      </div>
      <label className="flex items-center gap-2"><input type="checkbox" checked={s.enabled} onChange={(e) => setS({ ...s, enabled: e.target.checked })} /> Use Claude</label>
      <label className="flex items-center gap-2"><input type="checkbox" checked={s.price_fallback} onChange={(e) => setS({ ...s, price_fallback: e.target.checked })} />
        Read prices with Claude when a store blocks PriceWatch (Claude Haiku, up to twice a day per link)</label>
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="cap">Monthly cap (US$, 0 = no cap)</label>
        <input id="cap" className="input w-24" inputMode="decimal" value={s.monthly_cap_usd} onChange={(e) => setS({ ...s, monthly_cap_usd: e.target.value as unknown as number })} />
        <span className="text-xs text-slate-500">
          This month: about US${s.spend.usd.toFixed(2)} · {s.spend.checks} price check{s.spend.checks === 1 ? "" : "s"} · {s.spend.searches} search{s.spend.searches === 1 ? "" : "es"}
        </span>
      </div>
      <div className="flex flex-wrap gap-2">
        <button className="btn-primary" onClick={save}>Save</button>
        <button className="btn-ghost" onClick={() => api<{ ok: boolean; error?: string; display_name?: string }>("/api/admin/claude/test", { method: "POST", json: { api_key: key || null } })
          .then((r) => setMsg(r.ok ? `Works: ${r.display_name}` : `Not working: ${r.error}`)).catch((e) => setMsg((e as Error).message))}>Test</button>
        {s.key_saved && <button className="btn-ghost text-red-600" onClick={() => confirm("Forget the saved key?") &&
          api<Status>("/api/admin/claude/key", { method: "DELETE" }).then((r) => { setS(r); setMsg("Key forgotten"); })}>Forget key</button>}
      </div>
      {msg && <p className="text-xs text-slate-500">{msg}</p>}
    </div>
  );
}
