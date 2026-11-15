import { useState } from "react";
import { api } from "../api";
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
