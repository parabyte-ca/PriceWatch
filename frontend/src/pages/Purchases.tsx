import { useEffect, useState } from "react";
import { api } from "../api";
import OrderEmails from "../components/OrderEmails";
import { PurchaseCard, PurchaseInfo } from "../components/Purchase";

export default function Purchases() {
  const [rows, setRows] = useState<PurchaseInfo[] | null>(null);
  const load = () => api<PurchaseInfo[]>("/api/purchases").then(setRows).catch(() => setRows([]));
  useEffect(() => { load(); }, []);
  if (!rows) return <div className="text-slate-500">Loading...</div>;
  const open = rows.filter((p) => p.status === "watching" || p.status === "claimable");
  const rest = rows.filter((p) => !open.includes(p));
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-500">
        After you buy, PriceWatch keeps checking that store until the price-protection window closes and alerts you when you can
        claim money back. A proof package (page snapshot, timestamps, parsed price) is saved with each drop.
      </p>
      {!rows.length && <div className="card">No purchases yet. Use "Bought" on an item page.</div>}
      {open.map((p) => <PurchaseCard key={p.id} p={p} onChange={load} />)}
      {rest.length > 0 && <h2 className="pt-2 text-sm font-semibold text-slate-500">Closed</h2>}
      {rest.map((p) => <PurchaseCard key={p.id} p={p} onChange={load} />)}
      <OrderEmails onChange={load} />
    </div>
  );
}
