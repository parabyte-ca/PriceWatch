import { useEffect } from "react";
import { ago, Item, localTime, money, PriceMatch } from "../api";

/** Full-screen card to show a cashier: the cheaper competitor price, where and when it was seen, and the policy. */
export default function PriceMatchView({ item, o, onClose }: { item: Item; o: PriceMatch; onClose: () => void }) {
  const src = item.sources?.find((s) => s.url === o.match_url);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 overflow-y-auto pb-[env(safe-area-inset-bottom)] pt-[env(safe-area-inset-top)] bg-white text-slate-900 dark:bg-slate-950 dark:text-slate-100" role="dialog" aria-modal="true"
      aria-label="Price match">
      <div className="mx-auto max-w-lg space-y-5 p-5 pb-24">
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm font-semibold uppercase tracking-wide text-slate-500">Price match at {o.at}</span>
          <button className="btn-ghost" onClick={onClose}>Close</button>
        </div>
        <div>
          <div className="text-2xl font-bold leading-tight">{item.name}</div>
          <div className="mt-1 font-mono text-sm text-slate-500">
            {[item.brand, item.model && `Model ${item.model}`, item.gtin && `UPC ${item.gtin}`].filter(Boolean).join(" · ")}
          </div>
        </div>
        <div className="rounded-2xl border-4 border-green-600 p-5 text-center">
          <div className="text-lg">{o.match_to}</div>
          <div className="my-1 text-6xl font-black tracking-tight">{money(o.price_cents)}</div>
          <div className="text-sm text-slate-500">before tax{src?.last_in_stock === false ? " · out of stock" : src?.last_in_stock ? " · in stock" : ""}</div>
        </div>
        <div className="space-y-1 text-sm">
          <div>Seen {src?.last_checked_at ? `${ago(src.last_checked_at)} (${localTime(src.last_checked_at)})` : "recently"} on the store's own site
            {src?.last_seller_type?.startsWith("marketplace") ? ", from a marketplace seller" : ", sold by the store"}.</div>
          <a className="block break-all text-blue-700 underline dark:text-blue-300" href={o.match_url} target="_blank" rel="noreferrer">{o.match_url}</a>
        </div>
        <a className="btn-primary w-full py-3 text-base" href={o.match_url} target="_blank" rel="noreferrer">Open {o.match_to}'s page to show the price</a>
        {(o.policy_notes || o.caveats.length > 0) && (
          <div className="space-y-2 rounded-xl bg-slate-100 p-3 text-sm dark:bg-slate-900">
            {o.policy_notes && <p><b>{o.at}'s policy:</b> {o.policy_notes}</p>}
            {o.caveats.map((c) => <p key={c} className="text-amber-800 dark:text-amber-300">{c}</p>)}
          </div>
        )}
        <p className="text-xs text-slate-500">
          Saves {money(o.saving_cents)} before tax. Stores decide at the till; open the live page so the cashier sees the current price.
        </p>
      </div>
    </div>
  );
}
