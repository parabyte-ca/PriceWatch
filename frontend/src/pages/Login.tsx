import { FormEvent, useState } from "react";
import { api } from "../api";

export default function Login({ configured, onDone }: { configured: boolean; onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/api/auth/login", { method: "POST", json: { password } });
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto mt-24 max-w-sm px-4">
      <form onSubmit={submit} className="card space-y-4">
        <h1 className="flex items-center gap-2 text-xl font-bold">
          <img src="/icon.svg" alt="" className="h-7 w-7" /> PriceWatch CA
        </h1>
        {!configured && (
          <p className="text-sm text-amber-700">No admin password is set. Run setup.sh or set PRICEWATCH_ADMIN_PASSWORD in .env.</p>
        )}
        <div>
          <label className="label" htmlFor="pw">Password</label>
          <input id="pw" type="password" className="input" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus />
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button className="btn-primary w-full" disabled={busy || !password}>Sign in</button>
      </form>
    </div>
  );
}
