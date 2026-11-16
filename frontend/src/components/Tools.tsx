import { useEffect, useState } from "react";
import { api } from "../api";

interface Perk { id: number; retailer_domain: string; kind: string; label: string; percent: number | null; notes: string | null;
  url: string | null; valid_until: string | null; active: boolean }

export function Perks({ admin }: { admin: boolean }) {
  const [rows, setRows] = useState<Perk[]>([]);
  const [form, setForm] = useState({ retailer_domain: "", kind: "cashback", label: "", percent: "", valid_until: "" });
  const [error, setError] = useState("");
  const load = () => api<Perk[]>("/api/perks").then(setRows).catch(() => {});
  useEffect(() => { load(); }, []);
  const run = (fn: () => Promise<unknown>) => { setError(""); fn().then(load).catch((e) => setError((e as Error).message)); };
  return (
    <div className="card space-y-2 text-sm">
      <h2 className="font-semibold">Cash back, gift card and card perks</h2>
      <p className="text-xs text-slate-500">
        Enter the percentages you actually get (cash-back portal, discounted gift cards, card category bonus). Item pages then show
        an "after perks" price for the best offer. PriceWatch does not read any cash-back site; you keep these up to date.
      </p>
      {rows.map((p) => (
        <div key={p.id} className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-2 dark:border-slate-800">
          <span className="font-medium">{p.retailer_domain}</span>
          <span>{p.label}{p.percent != null ? ` (${p.percent}%)` : ""}</span>
          <span className="text-xs text-slate-500">{p.kind}{p.valid_until ? ` · until ${p.valid_until}` : ""}{p.active ? "" : " · off"}</span>
          {admin && (
            <span className="ml-auto flex gap-2">
              <button className="text-xs hover:underline" onClick={() => run(() => api(`/api/perks/${p.id}`, { method: "PATCH", json: { ...p, active: !p.active } }))}>
                {p.active ? "turn off" : "turn on"}
              </button>
              <button className="text-xs text-red-600 hover:underline" onClick={() => run(() => api(`/api/perks/${p.id}`, { method: "DELETE" }))}>delete</button>
            </span>
          )}
        </div>
      ))}
      {admin && (
        <form className="grid items-end gap-2 border-t border-slate-100 pt-2 sm:grid-cols-6 dark:border-slate-800" onSubmit={(e) => {
          e.preventDefault();
          run(async () => {
            await api("/api/perks", { method: "POST", json: { retailer_domain: form.retailer_domain.trim().toLowerCase().replace(/^www\./, ""),
              kind: form.kind, label: form.label, percent: form.percent ? Number(form.percent) : null, valid_until: form.valid_until || null } });
            setForm({ ...form, label: "", percent: "" });
          });
        }}>
          <div className="min-w-0"><label className="label">Store domain</label><input className="input" required placeholder="bestbuy.ca" value={form.retailer_domain} onChange={(e) => setForm({ ...form, retailer_domain: e.target.value })} /></div>
          <div className="min-w-0"><label className="label">Kind</label>
            <select className="input" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
              <option value="cashback">cash back</option><option value="giftcard">gift card</option><option value="card">credit card</option><option value="other">other</option>
            </select>
          </div>
          <div className="min-w-0 sm:col-span-2"><label className="label">Label</label><input className="input" required placeholder="Portal 3%" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} /></div>
          <div className="min-w-0"><label className="label">Percent</label><input className="input" inputMode="decimal" value={form.percent} onChange={(e) => setForm({ ...form, percent: e.target.value })} /></div>
          <div className="min-w-0"><label className="label">Until</label><input className="input" type="date" value={form.valid_until} onChange={(e) => setForm({ ...form, valid_until: e.target.value })} /></div>
          <button className="btn-ghost sm:col-span-6 sm:justify-self-start">Add perk</button>
        </form>
      )}
      {error && <p className="text-red-600">{error}</p>}
    </div>
  );
}
