import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, Item, money } from "../api";
import Badge, { Confidence } from "../components/Badge";

const RANK: Record<string, number> = { BUY: 0, BUY_AND_PROTECT: 1, WAIT: 2, NO_DATA: 3 };

/** Black Friday board: one phone-friendly list, BUY first, then BUY + PROTECT, then WAIT by distance to the low. */
export default function Board() {
  const [items, setItems] = useState<Item[] | null>(null);
  const [mode, setMode] = useState<string | null>(null);
  useEffect(() => { api<{ active: string | null }>("/api/sale-mode").then((m) => setMode(m.active)).catch(() => {}); }, []);
  const load = () => api<Item[]>("/api/items").then(setItems).catch(() => setItems([]));
  useEffect(() => {
    load();
    const t = setInterval(load, 60_000);
    return () => clearInterval(t);
  }, []);
  if (!items) return <div className="text-slate-500">Loading...</div>;
  const rows = [...items].sort((a, b) =>
    RANK[a.summary.decision] - RANK[b.summary.decision] ||
    (a.summary.distance_to_low_pct ?? 999) - (b.summary.distance_to_low_pct ?? 999));

  return (
    <div className="space-y-3">
      {mode && <div className="rounded-lg bg-red-700 p-2 text-sm font-semibold text-white">{mode} mode is on: top hot items are checked every 30 minutes.</div>}
      {rows.some((i) => i.summary.stale) && (
        <div className="rounded-lg bg-amber-100 p-2 text-sm text-amber-900">
          {rows.filter((i) => i.summary.stale).length} item(s) have no good price check in 24 hours; their prices may be out of date.
        </div>
      )}
      <p className="text-sm text-slate-500">
        In 2025 most Canadian discounts arrived before Black Friday week, and a third of Black Friday prices had been lower
        earlier in the season. BUY means at or within 2% of the lowest landed price seen this season, or at your target.
      </p>
      {rows.map((i) => (
        <Link key={i.id} to={`/items/${i.id}`}
          className={`card block min-h-[88px] ${i.summary.decision === "BUY" ? "border-green-500" : i.summary.decision === "BUY_AND_PROTECT" ? "border-teal-500" : ""}`}>
          <div className="flex items-start justify-between gap-3">
            <div className="text-lg font-semibold leading-tight">{i.name}</div>
            <Badge value={i.summary.badge} />
          </div>
          <div className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <span className="text-2xl font-bold">{money(i.summary.best_landed_cents)}</span>
            <span className="text-sm text-slate-500">{i.summary.best?.retailer}</span>
            <span className="text-sm">low {money(i.summary.seasonal_low_cents)}
              {i.summary.distance_to_low_pct != null && ` (${i.summary.distance_to_low_pct > 0 ? "+" : ""}${i.summary.distance_to_low_pct}%)`}</span>
            <Confidence level={i.summary.history_confidence} />
            {i.summary.stale && <span className="text-xs font-semibold text-amber-600">price may be stale</span>}
          </div>
          <div className="mt-1 text-sm text-slate-600 dark:text-slate-300">{i.summary.decision_reason}</div>
        </Link>
      ))}
    </div>
  );
}
