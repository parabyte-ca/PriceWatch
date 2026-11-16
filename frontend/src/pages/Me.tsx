import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, money } from "../api";
import { useSession } from "../session";

interface Bucket { purchases: number; spent_cents: number; saved_vs_median_cents: number; claimed_cents: number; claimable_cents: number }

function Tile({ to, icon, title, line }: { to: string; icon: string; title: string; line?: string }) {
  return (
    <Link to={to} className="card flex items-center gap-3 transition hover:shadow-md">
      <span className="text-2xl" aria-hidden>{icon}</span>
      <span className="min-w-0">
        <span className="block font-semibold">{title}</span>
        {line && <span className="block truncate text-sm text-slate-500">{line}</span>}
      </span>
    </Link>
  );
}

/** Me: everything about you and the household that is not the shopping list itself. */
export default function Me({ onSignOut, passwordMode }: { onSignOut: () => void; passwordMode: boolean }) {
  const { user } = useSession();
  const [total, setTotal] = useState<Bucket | null>(null);
  useEffect(() => { api<{ total: Bucket }>("/api/savings").then((s) => setTotal(s.total)).catch(() => {}); }, []);
  const saved = total ? total.saved_vs_median_cents + total.claimed_cents : 0;

  return (
    <div className="space-y-4">
      <div className="card flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-lg font-semibold">{user?.display_name}</div>
          <div className="text-sm text-slate-500">{user?.role === "admin" ? "Household admin" : "Household member"}</div>
        </div>
        {passwordMode && <button className="btn-ghost" onClick={onSignOut}>Sign out</button>}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Tile to="/purchases" icon="🧾" title="Bought"
          line={total ? (total.claimable_cents ? `${money(total.claimable_cents)} to claim back` : (total.purchases ? `${total.purchases} purchase${total.purchases === 1 ? "" : "s"}, prices still watched` : "Nothing bought yet")) : undefined} />
        <Tile to="/savings" icon="💰" title="Savings" line={total ? `${money(saved)} saved so far` : undefined} />
        <Tile to="/basket" icon="🛒" title="Plan a basket" line="Cheapest split across stores" />
        <Tile to="/settings" icon="⚙️" title="Settings" line="Alerts, province, how eager to buy" />
        {user?.role === "admin" && <Tile to="/system" icon="🛠️" title="Household admin" line="Updates, stores, perks, readiness" />}
      </div>
    </div>
  );
}
