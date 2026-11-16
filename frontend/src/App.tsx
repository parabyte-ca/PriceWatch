import { useCallback, useEffect, useState } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { api } from "./api";
import AskPanel from "./components/AskPanel";
import { UpdateBar } from "./components/UpdateBar";
import { isActive, readPending, type UpdateProgressInfo } from "./lib/updateProgress";
import AddItem from "./pages/AddItem";
import Basket from "./pages/Basket";
import Lists from "./pages/Lists";
import Purchases from "./pages/Purchases";
import Savings from "./pages/Savings";
import { CurrentUser, ListInfo, SessionContext } from "./session";
import ItemDetail from "./pages/ItemDetail";
import Login from "./pages/Login";
import SettingsPage from "./pages/Settings";
import SystemPage from "./pages/System";
import Home from "./pages/Home";
import Me from "./pages/Me";
import Shared from "./pages/Shared";

interface MeInfo {
  authenticated: boolean;
  mode: string;
  configured?: boolean;
  user?: CurrentUser;
}

const ME_PATHS = ["/me", "/purchases", "/savings", "/settings", "/system", "/basket"];

const ICONS: Record<string, JSX.Element> = {
  home: <path d="M3 11l9-7 9 7v9a1 1 0 01-1 1h-5v-6H9v6H4a1 1 0 01-1-1z" />,
  add: <path d="M12 5v14M5 12h14" />,
  lists: <path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01" />,
  me: <><circle cx="12" cy="8" r="4" /><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6" /></>,
};

const TABS: { to: string; label: string; icon: string; match: (p: string) => boolean }[] = [
  { to: "/", label: "Home", icon: "home", match: (p) => p === "/" || p === "/board" || p.startsWith("/items/") },
  { to: "/add", label: "Add", icon: "add", match: (p) => p === "/add" || p === "/share" },
  { to: "/lists", label: "Lists", icon: "lists", match: (p) => p === "/lists" },
  { to: "/me", label: "Me", icon: "me", match: (p) => ME_PATHS.includes(p) },
];

function Icon({ name }: { name: string }) {
  return (
    <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {ICONS[name]}
    </svg>
  );
}

export default function App() {
  const [me, setMe] = useState<MeInfo | null>(null);
  const path = useLocation().pathname;
  // admins: a slim bar on every page while an update runs (polled quickly only then)
  const [upd, setUpd] = useState<{ progress: UpdateProgressInfo } | null>(null);
  const [updOffline, setUpdOffline] = useState(false);
  const isAdmin = me?.user?.role === "admin";
  const updBusy = !!upd && isActive(upd.progress.state);
  useEffect(() => {
    if (!isAdmin) return;
    const poll = () => api<{ progress: UpdateProgressInfo }>("/api/admin/updates").then((d) => { setUpd(d); setUpdOffline(false); })
      .catch(() => setUpdOffline(!!readPending()));
    poll();
    const t = setInterval(poll, updBusy || (updOffline && readPending()) ? 3000 : 300000);
    return () => clearInterval(t);
  }, [isAdmin, updBusy, updOffline]);
  const [version, setVersion] = useState("");
  const [lists, setLists] = useState<ListInfo[]>([]);
  const reloadLists = useCallback(() => {
    api<ListInfo[]>("/api/lists").then(setLists).catch(() => setLists([]));
  }, []);
  useEffect(() => {
    if (me?.authenticated) reloadLists();
  }, [me?.authenticated, reloadLists]);

  const refresh = () => api<MeInfo>("/api/auth/me").then(setMe).catch(() => setMe({ authenticated: false, mode: "password" }));

  useEffect(() => {
    refresh();
    fetch("/healthz").then((r) => r.json()).then((h) => setVersion(h.version)).catch(() => {});
    const onUnauth = () => setMe((m) => (m ? { ...m, authenticated: false } : m));
    window.addEventListener("pricewatch:unauthorized", onUnauth);
    return () => window.removeEventListener("pricewatch:unauthorized", onUnauth);
  }, []);

  // a family member opening a shared gift list: no account needed
  if (path.startsWith("/shared/")) return <Shared token={path.slice("/shared/".length)} />;
  if (!me) return <div className="p-6 text-slate-500">Loading...</div>;
  if (!me.authenticated) return <Login configured={me.configured !== false} onDone={refresh} />;

  return (
    <SessionContext.Provider value={{ user: me.user || null, lists, reloadLists }}>
    <div className="mx-auto max-w-6xl px-4 pb-24 md:pb-16">
      {isAdmin && <UpdateBar summary={upd} offline={updOffline} />}
      <header className="flex items-center justify-between gap-2 pt-4">
        <NavLink to="/" className="flex min-w-0 items-center gap-2 text-lg font-bold">
          <img src="/icon.svg" alt="" className="h-7 w-7 shrink-0" /> <span className="truncate">PriceWatch</span>
        </NavLink>
        <nav className="hidden items-center gap-1 text-sm md:flex" aria-label="Main">
          {TABS.map((t) => (
            <NavLink key={t.to} to={t.to}
              className={`rounded-lg px-3 py-1.5 ${t.match(path) ? "bg-red-700 text-white" : "hover:bg-slate-200 dark:hover:bg-slate-800"}`}>
              {t.label}
            </NavLink>
          ))}
        </nav>
      </header>
      {/* phones: a tab bar at the bottom, within thumb reach */}
      <nav className="fixed inset-x-0 bottom-0 z-20 grid grid-cols-4 border-t border-slate-200 bg-white/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden dark:border-slate-800 dark:bg-slate-950/95"
        aria-label="Main">
        {TABS.map((t) => (
          <NavLink key={t.to} to={t.to}
            className={`flex flex-col items-center gap-0.5 py-2 text-xs ${t.match(path) ? "text-red-700 dark:text-red-400" : "text-slate-500"}`}>
            <Icon name={t.icon} />
            {t.label}
          </NavLink>
        ))}
      </nav>
      <div className="h-3" />
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/me" element={<Me passwordMode={me.mode === "password"} onSignOut={() => api("/api/auth/logout", { method: "POST" }).then(refresh)} />} />
        <Route path="/add" element={<AddItem />} />
        <Route path="/share" element={<AddItem />} />
        <Route path="/board" element={<Navigate to="/" replace />} />
        <Route path="/basket" element={<Basket />} />
        <Route path="/lists" element={<Lists />} />
        <Route path="/purchases" element={<Purchases />} />
        <Route path="/savings" element={<Savings />} />
        <Route path="/items/:id" element={<ItemDetail />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/system" element={<SystemPage />} />
        <Route path="*" element={<div className="card">Page not found.</div>} />
      </Routes>
      <AskPanel />
      <footer className="mt-10 text-center text-xs text-slate-400">PriceWatch CA v{version}</footer>
    </div>
    </SessionContext.Provider>
  );
}
