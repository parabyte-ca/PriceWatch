import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import { useSession } from "../session";

interface Person { id: number; username?: string; display_name: string; role?: string; active?: boolean }

export default function Account() {
  const { user } = useSession();
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [token, setToken] = useState("");
  const [pw, setPw] = useState({ current: "", next: "" });
  const [people, setPeople] = useState<Person[]>([]);
  const [newUser, setNewUser] = useState({ username: "", display_name: "", password: "" });
  const isAdmin = user?.role === "admin";
  const loadPeople = () => api<Person[]>("/api/users").then(setPeople).catch(() => {});
  useEffect(() => { loadPeople(); }, []);

  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    setError("");
    setMsg("");
    try {
      await fn();
      if (ok) setMsg(ok);
      loadPeople();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const changePw = (e: FormEvent) => {
    e.preventDefault();
    run(() => api("/api/me/password", { method: "POST", json: { current: pw.current, new: pw.next } }), "Password changed")
      .then(() => setPw({ current: "", next: "" }));
  };

  return (
    <div className="card space-y-4 md:col-span-2">
      <h2 className="font-semibold">Your account{user ? `: ${user.display_name} (${user.username})` : ""}</h2>
      <div className="grid gap-4 md:grid-cols-2">
        <form className="space-y-2" onSubmit={changePw}>
          <div className="label">Change password</div>
          <input className="input" type="password" autoComplete="current-password" placeholder="Current password" required
            value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} />
          <input className="input" type="password" autoComplete="new-password" placeholder="New password (8+ characters)" minLength={8} required
            value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} />
          <button className="btn-ghost">Change password</button>
        </form>
        <div className="space-y-2">
          <div className="label">Personal API token (iPhone Shortcut, scripts)</div>
          <p className="text-xs text-slate-500">Send <code>Authorization: Bearer &lt;token&gt;</code>. Items you add with it go to your default list.
            The token is shown once; creating a new one replaces the old one.</p>
          {token && <code className="block select-all break-all rounded bg-slate-100 p-2 text-xs dark:bg-slate-800">{token}</code>}
          <div className="flex gap-2">
            <button className="btn-ghost" onClick={() => confirm("Create a new token? The old one stops working.") &&
              run(async () => setToken((await api<{ token: string }>("/api/me/token", { method: "POST" })).token))}>
              {user?.has_token ? "Replace token" : "Create token"}
            </button>
            {user?.has_token && <button className="btn-ghost" onClick={() => run(() => api("/api/me/token", { method: "DELETE" }), "Token revoked")}>Revoke</button>}
          </div>
        </div>
      </div>

      {isAdmin && (
        <div className="space-y-2 border-t border-slate-200 pt-3 dark:border-slate-800">
          <div className="label">People in this household</div>
          <ul className="space-y-1 text-sm">
            {people.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-2">
                <span className={p.active === false ? "text-slate-400 line-through" : ""}>{p.display_name} ({p.username}, {p.role})</span>
                {p.id !== user?.id && (
                  <>
                    <button className="btn-ghost px-2 py-0.5 text-xs" onClick={() => {
                      const np = prompt(`New password for ${p.display_name} (8+ characters)`);
                      if (np) run(() => api(`/api/users/${p.id}`, { method: "PATCH", json: { password: np } }), "Password reset");
                    }}>Reset password</button>
                    <button className="btn-ghost px-2 py-0.5 text-xs" onClick={() => run(() => api(`/api/users/${p.id}`, { method: "PATCH", json: { active: p.active === false } }))}>
                      {p.active === false ? "Enable" : "Disable"}
                    </button>
                  </>
                )}
              </li>
            ))}
          </ul>
          <form className="flex flex-wrap gap-2" onSubmit={(e) => {
            e.preventDefault();
            run(() => api("/api/users", { method: "POST", json: newUser }), `${newUser.display_name} can now sign in`)
              .then(() => setNewUser({ username: "", display_name: "", password: "" }));
          }}>
            <input className="input w-36" required placeholder="username" pattern="[a-z0-9._-]{2,40}" value={newUser.username}
              onChange={(e) => setNewUser({ ...newUser, username: e.target.value.toLowerCase() })} />
            <input className="input w-40" required placeholder="Display name" value={newUser.display_name}
              onChange={(e) => setNewUser({ ...newUser, display_name: e.target.value })} />
            <input className="input w-48" required type="password" minLength={8} placeholder="Temporary password" value={newUser.password}
              onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} />
            <button className="btn-ghost">Add person</button>
          </form>
          <p className="text-xs text-slate-500">Each person gets their own list, alerts and settings. Share a list from the Lists page with a friend code.</p>
        </div>
      )}
      {msg && <p className="text-sm text-green-700">{msg}</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}
