import { useState } from "react";
import { api, money, toCents, toDollars } from "../api";
import { ListInfo } from "../session";

function GiftDetails({ l, onSave }: { l: ListInfo; onSave: (body: object) => void }) {
  const [open, setOpen] = useState(false);
  const [occasion, setOccasion] = useState(l.occasion || "");
  const [recipient, setRecipient] = useState(l.recipient || "");
  const [eventDate, setEventDate] = useState(l.event_date || "");
  const [budget, setBudget] = useState(toDollars(l.budget_cents));
  const days = l.event_date ? Math.ceil((new Date(l.event_date + "T00:00").getTime() - Date.now()) / 86400000) : null;
  const pct = l.budget_cents ? Math.min(100, Math.round((l.spent_cents / l.budget_cents) * 100)) : 0;
  const over = l.remaining_cents !== null && l.remaining_cents < 0;
  return (
    <div className="space-y-2">
      {(l.occasion || l.recipient || l.event_date) && (
        <div className="text-sm text-slate-600 dark:text-slate-300">
          {[l.occasion, l.recipient && `for ${l.recipient}`].filter(Boolean).join(" ")}
          {l.event_date && <> · {new Date(l.event_date + "T00:00").toLocaleDateString("en-CA", { dateStyle: "medium" })}{days !== null && days >= 0 && ` (${days} days)`}</>}
        </div>
      )}
      {l.budget_cents !== null ? (
        <div className="space-y-1">
          <div className="flex flex-wrap justify-between gap-2 text-sm">
            <span>Spent {money(l.spent_cents)} of {money(l.budget_cents)}</span>
            <span className={over ? "font-semibold text-red-600" : "text-green-700 dark:text-green-400"}>
              {over ? `${money(-(l.remaining_cents || 0))} over` : `${money(l.remaining_cents)} left`}
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded bg-slate-200 dark:bg-slate-800">
            <div className={`h-2 ${over ? "bg-red-600" : "bg-green-600"}`} style={{ width: `${pct}%` }} />
          </div>
        </div>
      ) : l.spent_cents > 0 ? <div className="text-sm">Spent {money(l.spent_cents)}</div> : null}
      {l.role === "owner" && (
        <button className="text-xs text-slate-500 hover:underline" onClick={() => setOpen(!open)}>
          {open ? "Close" : "Gift details and budget"}
        </button>
      )}
      {open && (
        <form className="grid items-end gap-2 sm:grid-cols-5" onSubmit={(e) => {
          e.preventDefault();
          onSave({ occasion: occasion || null, recipient: recipient || null, event_date: eventDate || null, budget_cents: toCents(budget) });
          setOpen(false);
        }}>
          <div className="min-w-0"><label className="label">Occasion</label><input className="input" placeholder="Christmas" value={occasion} onChange={(e) => setOccasion(e.target.value)} /></div>
          <div className="min-w-0"><label className="label">For</label><input className="input" placeholder="Name" value={recipient} onChange={(e) => setRecipient(e.target.value)} /></div>
          <div className="min-w-0"><label className="label">Date</label><input className="input" type="date" value={eventDate} onChange={(e) => setEventDate(e.target.value)} /></div>
          <div className="min-w-0"><label className="label">Budget ($)</label><input className="input" inputMode="decimal" value={budget} onChange={(e) => setBudget(e.target.value)} /></div>
          <button className="btn-ghost">Save</button>
        </form>
      )}
    </div>
  );
}
import { useSession } from "../session";

export default function Lists() {
  const { user, lists, reloadLists } = useSession();
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<Record<number, { code: string; expires_at: string }>>({});
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    setError("");
    try {
      await fn();
      if (ok) setMsg(ok);
      reloadLists();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="space-y-4">
      {lists.map((l) => (
        <div key={l.id} className="card space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold">{l.name}</h2>
            <span className="text-xs text-slate-500">{l.items} items · you are {l.role}</span>
            {l.role === "owner" && (
              <button className="btn-ghost ml-auto px-2 py-1 text-xs" onClick={() => {
                const n = prompt("New name", l.name);
                if (n) run(() => api(`/api/lists/${l.id}`, { method: "PATCH", json: { name: n } }));
              }}>Rename</button>
            )}
          </div>
          <GiftDetails l={l} onSave={(body) => run(() => api(`/api/lists/${l.id}`, { method: "PATCH", json: body }), "Saved")} />
          {l.role === "owner" && (
            <div className="space-y-1 rounded-lg bg-slate-50 p-2 text-sm dark:bg-slate-800/50">
              {l.share_on && l.share_link ? (
                <>
                  <div className="font-medium">Family link (read only, no account needed)</div>
                  <div className="flex flex-wrap items-center gap-2">
                    <code className="min-w-0 flex-1 select-all break-all text-xs">{location.origin + l.share_link}</code>
                    <button className="btn-ghost px-2 py-1 text-xs" onClick={() =>
                      navigator.clipboard?.writeText(location.origin + l.share_link).then(() => setMsg("Link copied")).catch(() => {})}>Copy</button>
                    {"share" in navigator && (
                      <button className="btn-ghost px-2 py-1 text-xs" onClick={() =>
                        navigator.share({ title: l.name, url: location.origin + l.share_link }).catch(() => {})}>Share</button>
                    )}
                  </div>
                  <label className="flex items-center gap-2 text-xs">
                    <input type="checkbox" checked={l.share_show_bought}
                      onChange={(e) => run(() => api(`/api/lists/${l.id}/share`, { method: "POST", json: { show_bought: e.target.checked } }))} />
                    Show what's already bought (so nobody buys it twice)
                  </label>
                  <button className="text-xs text-red-600 hover:underline" onClick={() => confirm("Stop sharing? The link stops working.") &&
                    run(() => api(`/api/lists/${l.id}/share`, { method: "DELETE" }), "Link turned off")}>Stop sharing</button>
                  <p className="text-xs text-slate-500">Anyone with the link sees item names, current prices and store links. Never your budget, prices paid or notes. Only send it to people who are not getting these gifts.</p>
                </>
              ) : (
                <button className="btn-ghost px-2 py-1 text-xs" onClick={() => run(() => api(`/api/lists/${l.id}/share`, { method: "POST", json: {} }), "Family link ready")}>
                  Create a family link (read only)
                </button>
              )}
            </div>
          )}
          <div className="text-sm">
            Members: {l.members.map((m) => (
              <span key={m.user_id} className="mr-3 inline-flex items-center gap-1">
                {m.display_name} <span className="text-xs text-slate-500">({m.role})</span>
                {l.role === "owner" && m.role !== "owner" && (
                  <button className="text-xs text-red-600 hover:underline" onClick={() => confirm(`Remove ${m.display_name} from ${l.name}?`) &&
                    run(() => api(`/api/lists/${l.id}/members/${m.user_id}`, { method: "DELETE" }))}>remove</button>
                )}
              </span>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {l.role === "owner" && (
              <>
                <button className="btn-ghost px-2 py-1 text-xs" onClick={() => run(async () => {
                  const r = await api<{ code: string; expires_at: string }>(`/api/lists/${l.id}/invites`, { method: "POST", json: { role: "editor" } });
                  setCodes({ ...codes, [l.id]: r });
                })}>Invite (can edit)</button>
                <button className="btn-ghost px-2 py-1 text-xs" onClick={() => run(async () => {
                  const r = await api<{ code: string; expires_at: string }>(`/api/lists/${l.id}/invites`, { method: "POST", json: { role: "viewer" } });
                  setCodes({ ...codes, [l.id]: r });
                })}>Invite (view only)</button>
              </>
            )}
            {l.role !== "owner" && user && (
              <button className="btn-ghost px-2 py-1 text-xs text-red-600" onClick={() => confirm(`Leave ${l.name}?`) &&
                run(() => api(`/api/lists/${l.id}/members/${user.id}`, { method: "DELETE" }), "Left the list")}>Leave</button>
            )}
            {l.role === "owner" && l.items === 0 && lists.length > 1 && (
              <button className="btn-ghost px-2 py-1 text-xs text-red-600" onClick={() => confirm(`Delete ${l.name}?`) &&
                run(() => api(`/api/lists/${l.id}`, { method: "DELETE" }), "List deleted")}>Delete</button>
            )}
          </div>
          {codes[l.id] && (
            <div className="rounded-lg bg-blue-50 p-3 text-sm text-blue-900 dark:bg-blue-950 dark:text-blue-100">
              Friend code: <span className="select-all font-mono text-lg font-bold tracking-wider">{codes[l.id].code}</span>
              <div className="text-xs">Works once, until {new Date(codes[l.id].expires_at).toLocaleString("en-CA")}. They enter it on their Lists page.</div>
            </div>
          )}
        </div>
      ))}

      <div className="grid gap-4 md:grid-cols-2">
        <form className="card space-y-2" onSubmit={(e) => {
          e.preventDefault();
          run(() => api("/api/lists", { method: "POST", json: { name } }), "List created").then(() => setName(""));
        }}>
          <h2 className="font-semibold">New list</h2>
          <input className="input" required placeholder="e.g. Gifts for the kids" value={name} onChange={(e) => setName(e.target.value)} />
          <button className="btn-ghost">Create</button>
        </form>
        <form className="card space-y-2" onSubmit={(e) => {
          e.preventDefault();
          run(() => api("/api/lists/join", { method: "POST", json: { code } }), "Joined").then(() => setCode(""));
        }}>
          <h2 className="font-semibold">Join a shared list</h2>
          <input className="input font-mono uppercase" required placeholder="PW-XXXX-XXXX" value={code} onChange={(e) => setCode(e.target.value)} />
          <button className="btn-ghost">Join</button>
        </form>
      </div>
      {msg && <p className="text-sm text-green-700">{msg}</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}
