import { FormEvent, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, Item, money, toCents, toDollars } from "../api";
import BarcodeScan from "../components/BarcodeScan";
import { useSession } from "../session";

interface FindOffer { merchant: string; title: string; url: string; store_link: boolean; price_cents: number;
  shipping_cents: number | null; landed_cents: number; kind: string; domain: string | null; confidence: number | null; method: string }
interface FindResult {
  query: string; provider: string | null; cached: boolean; notes: string[];
  product: { name: string | null; brand: string | null; model: string | null; gtin: string | null; image: string | null };
  link: { url: string; store: string; price_cents: number | null; blocked: boolean } | null;
  offers: FindOffer[]; best: FindOffer | null; suggested_target_cents: number | null;
}

const KIND_LABEL: Record<string, string> = { marketplace: "Marketplace sellers", other: "Other sites (not a known Canadian store)" };

const firstShared = (...values: (string | null)[]) => values.find((v) => v && v.trim()) || "";

/** Add: one box for a name, a store link or a barcode. Shows every store's price, then Watch tracks them all. */
export default function AddItem() {
  const nav = useNavigate();
  const { lists } = useSession();
  const writable = lists.filter((l) => l.role !== "viewer");
  const [params] = useSearchParams();
  const shared = firstShared(params.get("q"), params.get("url"), params.get("text"), params.get("title"));
  const [q, setQ] = useState(shared);
  const [res, setRes] = useState<FindResult | null>(null);
  const [busy, setBusy] = useState<"" | "find" | "watch">("");
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [target, setTarget] = useState("");
  const [listId, setListId] = useState("");
  const [showOther, setShowOther] = useState(false);

  const run = async (text: string, force = false) => {
    if (!text.trim()) return;
    setBusy("find"); setError(""); setRes(null);
    try {
      const r = await api<FindResult>("/api/find", { method: "POST", json: { q: text.trim(), force } });
      setRes(r);
      setName(r.product.name || text.trim());
      setTarget(toDollars(r.suggested_target_cents));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };
  useEffect(() => { if (shared) void run(shared); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = (e: FormEvent) => { e.preventDefault(); void run(q); };

  const watch = async () => {
    if (!res) return;
    setBusy("watch"); setError("");
    try {
      const w = await api<{ item: Item }>("/api/watch", { method: "POST", json: {
        name: name.trim() || res.product.name || q, brand: res.product.brand, model: res.product.model,
        gtin: res.product.gtin && /^\d{8,14}$/.test(res.product.gtin) ? res.product.gtin : null, image_url: res.product.image,
        query: res.query, target_price_cents: toCents(target), link_url: res.link?.url ?? null,
        list_id: listId ? Number(listId) : undefined,
      } });
      nav(`/items/${w.item.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy("");
    }
  };

  const stores = res?.offers.filter((o) => o.kind === "store") ?? [];
  const others = res?.offers.filter((o) => o.kind !== "store") ?? [];

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <form onSubmit={submit} className="card space-y-3">
        <h1 className="text-lg font-semibold">What are you shopping for?</h1>
        <div className="flex gap-2">
          <input className="input text-base sm:text-sm" autoFocus enterKeyHint="search" value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="Name, store link or barcode, e.g. Nintendo Switch 2" aria-label="Product" />
          <button className="btn-primary" disabled={!!busy || !q.trim()}>{busy === "find" ? "Searching…" : "Compare"}</button>
        </div>
        <details className="text-sm">
          <summary className="cursor-pointer text-slate-500">Scan a barcode with the camera</summary>
          <div className="mt-2"><BarcodeScan onPick={(_n, _b, code) => { setQ(code); void run(code); }} /></div>
        </details>
        {busy === "find" && <p className="text-sm text-slate-500">Checking Canadian stores… this takes a few seconds.</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}
      </form>

      {res && (
        <div className="card space-y-4">
          <div className="flex gap-3">
            {res.product.image && <img src={res.product.image} alt="" className="h-16 w-16 shrink-0 rounded object-contain" />}
            <div className="min-w-0">
              <div className="font-semibold">{res.product.name || res.query}</div>
              <div className="text-xs text-slate-500">{[res.product.brand, res.product.model, res.product.gtin].filter(Boolean).join(" · ")}</div>
            </div>
          </div>

          {res.best ? (
            <div className="rounded-lg border border-green-600/40 bg-green-50 p-3 text-green-900 dark:bg-green-950/40 dark:text-green-100">
              <div className="text-xs uppercase tracking-wide opacity-80">Best price right now</div>
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="text-2xl font-bold">{money(res.best.price_cents)}</span>
                <span className="font-medium">at {res.best.merchant}</span>
              </div>
              <div className="text-xs opacity-80">{money(res.best.landed_cents)} with tax{res.best.shipping_cents === 0 ? ", free shipping" : ""} · {stores.length} store{stores.length === 1 ? "" : "s"} compared</div>
            </div>
          ) : (
            <p className="text-sm text-slate-500">
              {res.provider ? "No Canadian store prices found for this yet. Watch it anyway and PriceWatch keeps looking every day." : res.notes[0]}
            </p>
          )}

          {stores.length > 0 && (
            <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
              {stores.map((o, n) => (
                <li key={o.url} className="flex items-center gap-3 py-2">
                  <div className="min-w-0 flex-1">
                    <a href={o.url} target="_blank" rel="noreferrer" className={`font-medium hover:underline ${n === 0 ? "text-green-700 dark:text-green-400" : ""}`}>{o.merchant}</a>
                    <div className="truncate text-xs text-slate-500" title={o.title}>{o.title}</div>
                  </div>
                  <div className="shrink-0 text-right">
                    <div className="font-semibold">{money(o.price_cents)}</div>
                    <div className="text-xs text-slate-500">{money(o.landed_cents)} with tax</div>
                  </div>
                </li>
              ))}
            </ul>
          )}

          {others.length > 0 && (
            <div className="text-xs">
              <button className="text-slate-500 hover:underline" onClick={() => setShowOther(!showOther)}>
                {showOther ? "Hide" : "Show"} {others.length} marketplace or other listing{others.length === 1 ? "" : "s"}
              </button>
              {showOther && (
                <ul className="mt-1 space-y-1">
                  {others.map((o) => (
                    <li key={o.url} className="flex gap-2">
                      <a href={o.url} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate hover:underline" title={o.title}>
                        {o.merchant}: {o.title}
                      </a>
                      <span className="shrink-0">{money(o.price_cents)}</span>
                      <span className="shrink-0 text-slate-400">{KIND_LABEL[o.kind] ? (o.kind === "marketplace" ? "marketplace" : "other") : ""}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {res.notes.length > 0 && res.best && res.notes.map((n) => <p key={n} className="text-xs text-amber-700">{n}</p>)}

          <div className="space-y-2 border-t border-slate-200 pt-3 dark:border-slate-800">
            <label className="label" htmlFor="w-name">Name</label>
            <input id="w-name" className="input" value={name} onChange={(e) => setName(e.target.value)} />
            <div className="flex flex-wrap items-end gap-2">
              <div className="w-40">
                <label className="label" htmlFor="w-target">Alert me at</label>
                <input id="w-target" className="input" inputMode="decimal" value={target} onChange={(e) => setTarget(e.target.value)} placeholder="optional" />
              </div>
              {writable.length > 1 && (
                <div>
                  <label className="label" htmlFor="w-list">List</label>
                  <select id="w-list" className="input w-auto" value={listId} onChange={(e) => setListId(e.target.value)}>
                    <option value="">My default list</option>
                    {writable.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
                  </select>
                </div>
              )}
              <button className="btn-primary ml-auto" disabled={!!busy} onClick={watch}>{busy === "watch" ? "Saving…" : "Watch"}</button>
            </div>
            <p className="text-xs text-slate-500">
              {res.suggested_target_cents ? "The suggested alert is about 10% under today's best price. " : ""}
              Watching tracks every store above and re-checks prices about daily.
              {res.cached ? " These results are from the last week's search; " : " "}
              {res.cached && <button className="hover:underline" onClick={() => run(q, true)}>search again</button>}
            </p>
          </div>
        </div>
      )}

      <p className="px-1 text-xs text-slate-500">
        Tip: on Android, install PriceWatch (browser menu, Install app), then use Share, PriceWatch from any shopping app.
      </p>
    </div>
  );
}
