import { useEffect, useState } from "react";
import { api, money } from "../api";

interface Bucket { purchases: number; spent_cents: number; saved_vs_median_cents: number; claimed_cents: number; claimable_cents: number }
interface SavingsData {
  total: Bucket;
  by_person: (Bucket & { user_id: number; name: string | null })[];
  by_list: (Bucket & { list_id: number; name: string; budget_cents: number | null })[];
  recent: { item: string; retailer: string; date: string; price_cents: number; reference_cents: number | null; saved_cents: number; claimed_cents: number | null; person: string | null }[];
}

function Tile({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="card min-w-0">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`truncate text-2xl font-bold ${tone || ""}`}>{value}</div>
    </div>
  );
}

function Rows({ title, rows }: { title: string; rows: (Bucket & { name: string | null; budget_cents?: number | null })[] }) {
  if (!rows.length) return null;
  return (
    <div className="card space-y-2">
      <h2 className="font-semibold">{title}</h2>
      {rows.map((r, i) => (
        <div key={i} className="flex flex-wrap items-baseline justify-between gap-x-3 border-t border-slate-100 pt-2 text-sm first:border-0 first:pt-0 dark:border-slate-800">
          <span className="min-w-0 truncate font-medium">{r.name || "Someone"}</span>
          <span className="text-slate-600 dark:text-slate-300">
            {money(r.spent_cents)}{r.budget_cents ? ` of ${money(r.budget_cents)}` : ""} · saved {money(r.saved_vs_median_cents + r.claimed_cents)}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function Savings() {
  const [d, setD] = useState<SavingsData | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api<SavingsData>("/api/savings").then(setD).catch((e) => setError(e.message)); }, []);
  if (!d) return <div className="text-slate-500">{error || "Loading..."}</div>;
  const t = d.total;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile label="Spent" value={money(t.spent_cents)} />
        <Tile label="Saved vs typical" value={money(t.saved_vs_median_cents)} tone="text-green-700 dark:text-green-400" />
        <Tile label="Claimed back" value={money(t.claimed_cents)} tone="text-green-700 dark:text-green-400" />
        <Tile label="Still to claim" value={money(t.claimable_cents)} tone={t.claimable_cents ? "text-amber-600" : ""} />
      </div>
      <p className="text-xs text-slate-500">
        "Typical" is the 60-day median first-party price before tax when you bought (needs at least 3 checks). It is an honest
        yardstick, not the retailer's "was" price.
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        <Rows title="By person" rows={d.by_person} />
        <Rows title="By list" rows={d.by_list} />
      </div>
      <div className="card space-y-2">
        <h2 className="font-semibold">Recent purchases</h2>
        {!d.recent.length && <p className="text-sm text-slate-500">Nothing bought yet.</p>}
        {d.recent.map((r, i) => (
          <div key={i} className="flex flex-wrap items-baseline justify-between gap-x-3 border-t border-slate-100 pt-2 text-sm first:border-0 first:pt-0 dark:border-slate-800">
            <span className="min-w-0">
              <span className="font-medium">{r.item}</span>
              <span className="text-slate-500"> · {r.retailer} · {r.date}{r.person ? ` · ${r.person}` : ""}</span>
            </span>
            <span>
              {money(r.price_cents)}
              {r.saved_cents > 0 && <span className="text-green-700 dark:text-green-400"> (saved {money(r.saved_cents)})</span>}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
