import { useEffect, useState } from "react";
import { money } from "../api";

interface SharedItem { name: string; image_url: string | null; brand: string | null; target_cents: number | null; price_cents: number | null;
  store: string | null; url: string | null; good_price: boolean; bought: boolean }
interface SharedData { name: string; occasion: string | null; recipient: string | null; event_date: string | null; items: SharedItem[] }

/** Read-only gift list for family, opened from a link (no account). */
export default function Shared({ token }: { token: string }) {
  const [d, setD] = useState<SharedData | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    fetch(`/api/shared/${encodeURIComponent(token)}`)
      .then(async (r) => (r.ok ? r.json() : Promise.reject(new Error((await r.json().catch(() => ({}))).detail || "Not found"))))
      .then(setD).catch((e) => setError((e as Error).message));
  }, [token]);
  if (error) return <div className="mx-auto max-w-lg p-6"><div className="card">{error}</div></div>;
  if (!d) return <div className="p-6 text-slate-500">Loading...</div>;
  const open = d.items.filter((i) => !i.bought);
  const done = d.items.filter((i) => i.bought);
  const when = d.event_date ? new Date(d.event_date + "T00:00").toLocaleDateString("en-CA", { dateStyle: "long" }) : null;
  return (
    <div className="mx-auto max-w-2xl space-y-4 px-4 py-6">
      <header className="space-y-1">
        <div className="flex items-center gap-2 text-sm text-slate-500"><img src="/icon.svg" alt="" className="h-5 w-5" /> Shared from PriceWatch</div>
        <h1 className="text-2xl font-bold">{d.name}</h1>
        <p className="text-slate-600 dark:text-slate-300">{[d.occasion, d.recipient && `for ${d.recipient}`, when].filter(Boolean).join(" · ")}</p>
      </header>
      {!d.items.length && <div className="card">Nothing on this list yet.</div>}
      <div className="space-y-2">
        {open.map((i) => (
          <div key={i.name} className="card flex gap-3">
            {i.image_url && <img src={i.image_url} alt="" className="h-16 w-16 shrink-0 rounded object-contain" loading="lazy" />}
            <div className="min-w-0 flex-1">
              <div className="break-words font-semibold">{i.name}</div>
              <div className="text-sm text-slate-500">
                {i.price_cents != null ? <>{money(i.price_cents)}{i.store ? ` at ${i.store}` : ""}</> : "No price yet"}
                {i.good_price && <span className="ml-2 font-semibold text-green-700 dark:text-green-400">good price now</span>}
              </div>
              {i.url && <a className="text-sm text-blue-700 underline dark:text-blue-300" href={i.url} target="_blank" rel="noreferrer noopener">View at {i.store}</a>}
            </div>
          </div>
        ))}
      </div>
      {done.length > 0 && (
        <div className="space-y-1">
          <h2 className="text-sm font-semibold text-slate-500">Already bought</h2>
          {done.map((i) => <div key={i.name} className="text-sm text-slate-500 line-through">{i.name}</div>)}
        </div>
      )}
      <p className="text-xs text-slate-400">Prices are before tax and were checked by PriceWatch; the store's site has the final price.</p>
    </div>
  );
}
