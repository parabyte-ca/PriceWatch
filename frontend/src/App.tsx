import { useCallback, useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api } from "./api";
import AddItem from "./pages/AddItem";
import Board from "./pages/Board";
import Lists from "./pages/Lists";
import Purchases from "./pages/Purchases";
import Savings from "./pages/Savings";
import { CurrentUser, ListInfo, SessionContext } from "./session";
import ItemDetail from "./pages/ItemDetail";
import Login from "./pages/Login";
import SettingsPage from "./pages/Settings";
import SystemPage from "./pages/System";
import Wishlist from "./pages/Wishlist";

interface Me {
  authenticated: boolean;
  mode: string;
  configured?: boolean;
  user?: CurrentUser;
}

const nav = [
  ["/", "Wishlist"],
  ["/board", "Board"],
  ["/add", "Add"],
  ["/lists", "Lists"],
  ["/purchases", "Bought"],
  ["/savings", "Savings"],
  ["/settings", "Settings"],
  ["/system", "System"],
];

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [version, setVersion] = useState("");
  const [lists, setLists] = useState<ListInfo[]>([]);
  const reloadLists = useCallback(() => {
    api<ListInfo[]>("/api/lists").then(setLists).catch(() => setLists([]));
  }, []);
  useEffect(() => {
    if (me?.authenticated) reloadLists();
  }, [me?.authenticated, reloadLists]);

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
    <SessionContext.Provider value={{ user: me.user || null, lists, reloadLists }}>
    <div className="mx-auto max-w-6xl px-4 pb-16">
      <header className="pt-4">
        <div className="flex items-center justify-between gap-2">
          <NavLink to="/" className="flex min-w-0 items-center gap-2 text-lg font-bold">
            <img src="/icon.svg" alt="" className="h-7 w-7 shrink-0" /> <span className="truncate">PriceWatch<span className="hidden sm:inline"> CA</span></span>
          </NavLink>
          <div className="flex shrink-0 items-center gap-2 text-sm">
            {me.user && <span className="max-w-[8rem] truncate text-slate-500">{me.user.display_name}</span>}
            {me.mode === "password" && (
              <button
                className="whitespace-nowrap rounded-lg px-2 py-1 text-slate-600 hover:bg-slate-200 dark:text-slate-300 dark:hover:bg-slate-800"
                onClick={() => api("/api/auth/logout", { method: "POST" }).then(refresh)}
              >
                Sign out
              </button>
            )}
          </div>
        </div>
        {/* one row that scrolls sideways on small screens instead of wrapping */}
        <nav className="-mx-4 mt-3 flex items-center gap-1 overflow-x-auto px-4 pb-2 text-sm [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {nav.map(([to, label]) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                `shrink-0 whitespace-nowrap rounded-lg px-3 py-1.5 ${isActive ? "bg-red-700 text-white" : "hover:bg-slate-200 dark:hover:bg-slate-800"}`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
      </header>
      <div className="h-3" />
      <Routes>
        <Route path="/" element={<Wishlist />} />
        <Route path="/add" element={<AddItem />} />
        <Route path="/share" element={<AddItem />} />
        <Route path="/board" element={<Board />} />
        <Route path="/lists" element={<Lists />} />
        <Route path="/purchases" element={<Purchases />} />
        <Route path="/savings" element={<Savings />} />
        <Route path="/items/:id" element={<ItemDetail />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/system" element={<SystemPage />} />
        <Route path="*" element={<div className="card">Page not found.</div>} />
      </Routes>
      <footer className="mt-10 text-center text-xs text-slate-400">PriceWatch CA v{version}</footer>
    </div>
    </SessionContext.Provider>
  );
}
