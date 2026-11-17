import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, Item, money, toCents, toDollars } from "../api";

interface Row {
  item_id: number; name: string; image_url: string | null; when: string; advice: string; store: string | null;
  url: string | null; price_cents: number | null; landed_cents: number | null; expected_cents: number | null;
  target_cents: number | null; decision: string | null;
}
interface PlanOut {
  budget_cents: number | null; items: Row[]; total_now_cents: number; total_expected_cents: number;
  left_cents: number | null; events: { name: string; date: string }[];
}

const WHEN_STYLE: Record<string, string> = {
  now: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  anytime: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  unknown: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
};

/** Black Friday plan: what you mean to buy, a budget, and when and where to buy each item. */
export default function Plan() {
  const [plan, setPlan] = useState<PlanOut | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [budget, setBudget] = useState("");
  const [picking, setPicking] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    try {
      const [p, its] = await Promise.all([api<PlanOut>("/api/plan"), api<Item[]>("/api/items")]);
      setPlan(p); setItems(its); setBudget(toDollars(p.budget_cents));
      if (!p.items.length) setPicking(true);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  useEffect(() => { void load(); }, []);

  const save = async (ids: number[], budgetText = budget) => {
    try {
      const p = await api<PlanOut>("/api/plan", { method: "PUT", json: { budget_cents: toCents(budgetText), item_ids: ids } });
      setPlan(p); setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (!plan) return <div className="card text-sm">{error || "Loading…"}</div>;
  const ids = plan.items.map((r) => r.item_id);
  const over = plan.left_cents != null && plan.left_cents < 0;

  return (
    <div className="space-y-3">
      <div className="card space-y-2">
        <h1 className="text-lg font-semibold">🛍️ Black Friday plan</h1>
        <p className="text-sm text-slate-500">
          {plan.events.map((e) => `${e.name} ${new Date(e.date + "T12:00").toLocaleDateString("en-CA", { month: "short", day: "numeric" })}`).join(" · ")}.
          On each of those mornings you get this plan as a checklist, and an hourly note of what dropped.
        </p>
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-sm">
            Budget
            <input className="input mt-1 w-32" inputMode="decimal" placeholder="$" value={budget}
              onChange={(e) => setBudget(e.target.value)} onBlur={() => void save(ids)} />
          </label>
          <button className="btn-ghost" onClick={() => setPicking(!picking)}>{picking ? "Done picking" : "Pick items"}</button>
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
      </div>

      {picking && (
        <div className="card space-y-1 text-sm">
          <div className="font-medium">Items in the plan</div>
          {!items.length && <p className="text-slate-500">No items yet. <Link className="underline" to="/add">Add one</Link>.</p>}
          {items.map((it) => (
            <label key={it.id} className="flex items-center gap-2 py-1">
              <input type="checkbox" checked={ids.includes(it.id)}
                onChange={(e) => void save(e.target.checked ? [...ids, it.id] : ids.filter((x) => x !== it.id))} />
              <span className="truncate">{it.name}</span>
            </label>
          ))}
        </div>
      )}

      {plan.items.length > 0 && (
        <div className="card grid grid-cols-3 gap-2 text-center text-sm">
          <div><div className="text-slate-500">Today</div><div className="font-semibold">{money(plan.total_now_cents)}</div></div>
          <div><div className="text-slate-500">If you wait</div><div className="font-semibold">{money(plan.total_expected_cents)}</div></div>
          <div>
            <div className="text-slate-500">{over ? "Over budget" : "Left"}</div>
            <div className={`font-semibold ${over ? "text-red-600" : ""}`}>{plan.left_cents == null ? "No budget" : money(Math.abs(plan.left_cents))}</div>
          </div>
          <p className="col-span-3 text-xs text-slate-500">With tax and shipping, at the cheapest store for each item.</p>
        </div>
      )}

      {plan.items.map((r) => (
        <div key={r.item_id} className="card flex gap-3 text-sm">
          {r.image_url
            ? <img src={r.image_url} alt="" className="h-16 w-16 shrink-0 rounded object-contain bg-white" loading="lazy" />
            : <div className="h-16 w-16 shrink-0 rounded bg-slate-100 dark:bg-slate-800" />}
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex items-start justify-between gap-2">
              <Link to={`/items/${r.item_id}`} className="font-medium hover:underline">{r.name}</Link>
              <span className={`shrink-0 rounded px-2 py-0.5 text-xs ${WHEN_STYLE[r.when] ?? "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"}`}>
                {r.when === "now" ? "Buy now" : r.when === "anytime" ? "Any time" : r.when === "unknown" ? "No price yet" : `Wait: ${r.when}`}
              </span>
            </div>
            <p className="text-slate-600 dark:text-slate-300">{r.advice}</p>
            <div className="flex flex-wrap gap-x-3 text-xs text-slate-500">
              {r.landed_cents != null && <span>{money(r.landed_cents)} with tax{r.store ? ` at ${r.store}` : ""}</span>}
              {r.target_cents != null && <span>target {money(r.target_cents)}</span>}
              {r.url && <a className="underline" href={r.url} target="_blank" rel="noreferrer">Open store</a>}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
