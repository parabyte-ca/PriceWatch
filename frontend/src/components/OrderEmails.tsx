import { useEffect, useState } from "react";
import { api, Item, money } from "../api";
import { useSession } from "../session";

interface Line { name: string; price_cents: number | null; quantity: number; item_id: number | null; purchase_id?: number | null }
interface Imp { id: number; subject: string | null; received_at: string | null; retailer_domain: string | null; order_ref: string | null;
  method: string; status: string; error: string | null; lines: Line[] }
interface Data { configured: boolean; enabled: boolean; address: string | null; imports: Imp[] }

const STATUS: Record<string, string> = { recorded: "recorded", partial: "some lines recorded", unmatched: "needs linking",
  ignored: "not an order", error: "error" };

export default function OrderEmails({ onChange }: { onChange: () => void }) {
  const { user } = useSession();
  const [d, setD] = useState<Data | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [msg, setMsg] = useState("");
  const load = () => api<Data>("/api/email-imports").then(setD).catch(() => {});
  useEffect(() => { load(); api<Item[]>("/api/items?include_inactive=true").then(setItems).catch(() => {}); }, []);
  if (!d) return null;
  if (!d.configured && user?.role !== "admin") return null;

  const link = (imp: Imp, line: number, itemId: string) => {
    if (!itemId) return;
    api(`/api/email-imports/${imp.id}/link`, { method: "POST", json: { line, item_id: Number(itemId) } })
      .then(() => { load(); onChange(); setMsg("Purchase recorded"); })
      .catch((e) => setMsg((e as Error).message));
  };

  return (
    <div className="card space-y-2 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">Order emails</h2>
        {user?.role === "admin" && d.configured && (
          <button className="btn-ghost px-2 py-1 text-xs" onClick={() =>
            api<{ read?: number; recorded?: number; enabled?: boolean }>("/api/email-imports/check", { method: "POST" })
              .then((r) => { setMsg(r.enabled === false ? "Turn on order-email import in Settings first" : `Read ${r.read}, recorded ${r.recorded}`); load(); onChange(); })
              .catch((e) => setMsg((e as Error).message))}>Check mailbox now</button>
        )}
      </div>
      {!d.configured ? (
        <p className="text-xs text-slate-500">
          Set up a mailbox (PRICEWATCH_IMAP_* in .env) and forward order confirmations to it; purchases are recorded with their
          price protection automatically. See the README.
        </p>
      ) : (
        <p className="text-xs text-slate-500">
          Forward order confirmations to <span className="select-all font-mono">{d.address}</span>.
          {!d.enabled && " Import is turned off in Settings."} Set "My order emails come from" in Settings so they land on your list.
        </p>
      )}
      {d.imports.map((imp) => (
        <div key={imp.id} className="space-y-1 border-t border-slate-100 pt-2 dark:border-slate-800">
          <div className="flex flex-wrap justify-between gap-2">
            <span className="min-w-0 break-words font-medium">{imp.subject || "(no subject)"}</span>
            <span className="text-xs text-slate-500">{STATUS[imp.status] || imp.status}</span>
          </div>
          <div className="text-xs text-slate-500">
            {[imp.retailer_domain, imp.order_ref && `order ${imp.order_ref}`, imp.received_at && new Date(imp.received_at + "Z").toLocaleDateString("en-CA"),
              imp.method === "claude" && "read by Claude"].filter(Boolean).join(" · ")}
            {imp.error && ` · ${imp.error}`}
          </div>
          {imp.lines.map((ln, n) => (
            <div key={n} className="flex flex-wrap items-center justify-between gap-2 pl-2">
              <span className="min-w-0 break-words">{ln.name} {ln.price_cents != null && <span className="text-slate-500">{money(ln.price_cents)}</span>}</span>
              {ln.purchase_id ? <span className="text-xs text-green-700">recorded</span> : (
                <select className="input w-auto max-w-full py-1 text-xs" defaultValue="" onChange={(e) => link(imp, n, e.target.value)}>
                  <option value="">Link to item...</option>
                  {items.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
                </select>
              )}
            </div>
          ))}
        </div>
      ))}
      {msg && <p className="text-xs text-slate-500">{msg}</p>}
    </div>
  );
}
