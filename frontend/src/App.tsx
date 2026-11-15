import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api } from "./api";
import AddItem from "./pages/AddItem";
import ItemDetail from "./pages/ItemDetail";
import Login from "./pages/Login";
import SettingsPage from "./pages/Settings";
import SystemPage from "./pages/System";
import Wishlist from "./pages/Wishlist";

interface Me {
  authenticated: boolean;
  mode: string;
  configured?: boolean;
}

const nav = [
  ["/", "Wishlist"],
  ["/add", "Add"],
  ["/settings", "Settings"],
  ["/system", "System"],
];

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [version, setVersion] = useState("");

  const refresh = () => api<Me>("/api/auth/me").then(setMe).catch(() => setMe({ authenticated: false, mode: "password" }));

  useEffect(() => {
    refresh();
    fetch("/healthz").then((r) => r.json()).then((h) => setVersion(h.version)).catch(() => {});
    const onUnauth = () => setMe((m) => (m ? { ...m, authenticated: false } : m));
    window.addEventListener("pricewatch:unauthorized", onUnauth);
    return () => window.removeEventListener("pricewatch:unauthorized", onUnauth);
  }, []);

  if (!me) return <div className="p-6 text-slate-500">Loading...</div>;
  if (!me.authenticated) return <Login configured={me.configured !== false} onDone={refresh} />;

  return (
    <div className="mx-auto max-w-6xl px-4 pb-16">
      <header className="flex flex-wrap items-center justify-between gap-2 py-4">
        <NavLink to="/" className="flex items-center gap-2 text-lg font-bold">
          <img src="/icon.svg" alt="" className="h-7 w-7" /> PriceWatch CA
        </NavLink>
        <nav className="flex gap-1 text-sm">
          {nav.map(([to, label]) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                `rounded-lg px-3 py-1.5 ${isActive ? "bg-red-700 text-white" : "hover:bg-slate-200 dark:hover:bg-slate-800"}`
              }
            >
              {label}
            </NavLink>
          ))}
          {me.mode === "password" && (
            <button
              className="rounded-lg px-3 py-1.5 hover:bg-slate-200 dark:hover:bg-slate-800"
              onClick={() => api("/api/auth/logout", { method: "POST" }).then(refresh)}
            >
              Sign out
            </button>
          )}
        </nav>
      </header>
      <Routes>
        <Route path="/" element={<Wishlist />} />
        <Route path="/add" element={<AddItem />} />
        <Route path="/items/:id" element={<ItemDetail />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/system" element={<SystemPage />} />
        <Route path="*" element={<div className="card">Page not found.</div>} />
      </Routes>
      <footer className="mt-10 text-center text-xs text-slate-400">PriceWatch CA v{version}</footer>
    </div>
  );
}
