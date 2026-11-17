import { FormEvent, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, Item, money, toCents, toDollars } from "../api";
import BarcodeScan from "../components/BarcodeScan";
import { useSession } from "../session";

interface FindOffer { pay_with?: { label: string; percent: number }[]; after_perks_cents?: number | null; image?: string | null; local?: string | null; merchant: string; title: string; url: string; store_link: boolean; price_cents: number;
  shipping_cents: number | null; landed_cents: number; kind: string; domain: string | null; confidence: number | null; method: string }
interface FindResult {
  query: string; provider: string | null; cached: boolean; notes: string[];
  product: { name: string | null; brand: string | null; model: string | null; gtin: string | null; image: string | null };
  link: { url: string; store: string; price_cents: number | null; blocked: boolean } | null;
  offers: FindOffer[]; best: FindOffer | null; suggested_target_cents: number | null;
}

const KIND_LABEL: Record<string, string> = { marketplace: "marketplace seller", other: "not a known Canadian store", bundle: "bundle",
  accessory: "accessory", refurbished: "refurbished or used", different: "different model" };

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

  const [stage, setStage] = useState("");
  const STAGE_TEXT: Record<string, string> = {
    photo: "Reading the photo…", product: "Working out the product…", search: "Found stores, looking for more…",
    stores: "Opening store lists…", claude: "Asking Claude about the rest…", done: "",
  };
  const run = (text: string, force = false) => {
    if (!text.trim()) return;
    setBusy("find"); setError(""); setRes(null); setStage("product");
    const apply = (r: FindResult, final: boolean) => {
      setRes(r);
      if (final) { setName(r.product.name || text.trim()); setTarget(toDollars(r.suggested_target_cents)); }
    };
    const es = new EventSource(`/api/find/stream?q=${encodeURIComponent(text.trim())}${force ? "&force=true" : ""}`);
    const stop = () => { es.close(); setBusy(""); setStage(""); };
    for (const name of ["product", "search", "stores", "claude"]) {
      es.addEventListener(name, (ev) => { setStage(name); apply(JSON.parse((ev as MessageEvent).data), false); });
    }
    es.addEventListener("done", (ev) => { apply(JSON.parse((ev as MessageEvent).data), true); stop(); });
    es.addEventListener("error", (ev) => {
      const data = (ev as MessageEvent).data;
      setError(data ? JSON.parse(data).detail : "Search interrupted; try again");
      stop();
    });
  };
  useEffect(() => { if (shared) run(shared); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = (e: FormEvent) => { e.preventDefault(); run(q); };

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

  const photo = async (file: File) => {
    setBusy("find"); setError(""); setStage("photo");
    try {
      const bmp = await createImageBitmap(file);
      const scale = Math.min(1, 1280 / Math.max(bmp.width, bmp.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(bmp.width * scale); canvas.height = Math.round(bmp.height * scale);
      canvas.getContext("2d")?.drawImage(bmp, 0, 0, canvas.width, canvas.height);
      const b64 = canvas.toDataURL("image/jpeg", 0.85).split(",")[1];
      const r = await api<{ found: boolean; q: string | null; barcode: string | null }>("/api/find/photo", { method: "POST", json: { image_b64: b64 } });
      if (!r.found || !r.q) { setError("Could not tell what product that is. Try a clearer photo of the front of the box, or type its name."); setBusy(""); return; }
      setQ(r.q);
      run(r.q);
    } catch (e) {
      setError((e as Error).message); setBusy("");
    }
  };
  const notThis = (o: FindOffer) => {
    if (!res) return;
    api("/api/feedback/not-this-product", { method: "POST", json: { url: o.url, query: res.query, merchant: o.merchant } }).catch(() => {});
    const offers = res.offers.filter((x) => x.url !== o.url);
    const left = offers.filter((x) => x.kind === "store");
    setRes({ ...res, offers, best: left[0] ?? null });
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
        <label className="btn-ghost w-full cursor-pointer text-sm">
          📷 Take a photo of the product or its box
          <input type="file" accept="image/*" capture="environment" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void photo(f); }} />
        </label>
        <details className="text-sm">
          <summary className="cursor-pointer text-slate-500">Scan a barcode with the camera</summary>
          <div className="mt-2"><BarcodeScan onPick={(_n, _b, code) => { setQ(code); run(code); }} /></div>
        </details>
        {busy === "find" && <p className="text-sm text-slate-500">{STAGE_TEXT[stage] || "Checking Canadian stores…"}</p>}
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
                  {o.image ? <img src={o.image} alt="" loading="lazy" className="h-10 w-10 shrink-0 rounded bg-white object-contain" /> : <div className="h-10 w-10 shrink-0" />}
                  <div className="min-w-0 flex-1">
                    <a href={o.url} target="_blank" rel="noreferrer" className={`font-medium hover:underline ${n === 0 ? "text-green-700 dark:text-green-400" : ""}`}>{o.merchant}</a>
                    <div className="truncate text-xs text-slate-500" title={o.title}>{o.title}</div>
                    {o.local && <div className="text-xs text-green-700 dark:text-green-400">📍 {o.local}</div>}
                  </div>
                  <div className="shrink-0 text-right">
                    <div className="font-semibold">{money(o.price_cents)}</div>
                    <div className="text-xs text-slate-500">{money(o.landed_cents)} with tax</div>
                    {o.after_perks_cents != null && <div className="text-xs text-blue-700 dark:text-blue-300" title={(o.pay_with || []).map((p) => `${p.label} ${p.percent}%`).join(" + ")}>
                      {money(o.after_perks_cents)} with {(o.pay_with || []).map((p) => p.label).join(" + ")}</div>}
                  </div>
                  <button className="shrink-0 px-1 text-xs text-slate-400 hover:text-red-600" title="Not this product: hide it from this search from now on"
                    onClick={() => notThis(o)}>Not this</button>
                </li>
              ))}
            </ul>
          )}

          {others.length > 0 && (
            <div className="text-xs">
              <button className="text-slate-500 hover:underline" onClick={() => setShowOther(!showOther)}>
                {showOther ? "Hide" : "Show"} {others.length} other listing{others.length === 1 ? "" : "s"} (bundles, accessories, marketplace sellers…)
              </button>
              {showOther && (
                <ul className="mt-1 space-y-1">
                  {others.map((o) => (
                    <li key={o.url} className="flex gap-2">
                      <a href={o.url} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate hover:underline" title={o.title}>
                        {o.merchant}: {o.title}
                      </a>
                      <span className="shrink-0">{money(o.price_cents)}</span>
                      <span className="shrink-0 text-slate-400">{KIND_LABEL[o.kind] ?? o.kind}</span>
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
