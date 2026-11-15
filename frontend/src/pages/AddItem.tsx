import { FormEvent, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, Item, money, toCents } from "../api";
import { useSession } from "../session";

interface Preview {
  url: string;
  retailer: string;
  outcome: string;
  error: string | null;
  method: string;
  product: { name: string | null; price_cents: number | null; was_price_cents: number | null; image: string | null;
    brand: string | null; mpn: string | null; gtin: string | null; in_stock: boolean | null; currency: string | null } | null;
}

const firstUrl = (...values: (string | null)[]) => {
  for (const v of values) {
    const m = v?.match(/https?:\/\/\S+/);
    if (m) return m[0];
  }
  return "";
};

export default function AddItem() {
  const nav = useNavigate();
  const { lists } = useSession();
  const writable = lists.filter((l) => l.role !== "viewer");
  const [listId, setListId] = useState<string>("");
  const chosenList = listId ? Number(listId) : undefined;
  const [params] = useSearchParams();
  const shared = firstUrl(params.get("url"), params.get("text"), params.get("title"));
  const [url, setUrl] = useState(shared);
  const [list, setList] = useState("");
  const [importResult, setImportResult] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [name, setName] = useState("");
  const [target, setTarget] = useState("");
  const [hot, setHot] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [manualName, setManualName] = useState("");
  const [brand, setBrand] = useState("");
  const [model, setModel] = useState("");

  useEffect(() => {
    if (shared) runPreview(shared);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const doPreview = async (e: FormEvent) => {
    e.preventDefault();
    await runPreview(url.trim());
  };

  const runPreview = async (target: string) => {
    setBusy(true);
    setError("");
    setPreview(null);
    try {
      const p = await api<Preview>("/api/preview", { method: "POST", json: { url: target } });
      setPreview(p);
      setName(p.product?.name || "");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const item = await api<Item>("/api/items/from-url", {
        method: "POST",
        json: { url: url.trim(), name: name || undefined, target_price_cents: toCents(target), hot, list_id: chosenList },
      });
      nav(`/items/${item.id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  const createByName = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const item = await api<Item>("/api/items", {
        method: "POST",
        json: { name: manualName, brand: brand || null, model: model || null, target_price_cents: toCents(target), list_id: chosenList },
      });
      const [providers, settings] = await Promise.all([
        api<{ providers: unknown[] }>("/api/discovery/providers"),
        api<{ discover_on_add: boolean }>("/api/settings"),
      ]);
      if (providers.providers.length && settings.discover_on_add) {
        await api(`/api/items/${item.id}/discover`, { method: "POST", json: {} }).catch(() => undefined);
      }
      nav(`/items/${item.id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  const p = preview?.product;
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {writable.length > 1 && (
        <div className="flex items-center gap-2 md:col-span-2">
          <label className="label mb-0">Add to</label>
          <select className="input w-auto" value={listId} onChange={(e) => setListId(e.target.value)}>
            <option value="">My default list</option>
            {writable.map((l) => <option key={l.id} value={l.id}>{l.name}{l.shared ? " (shared)" : ""}</option>)}
          </select>
        </div>
      )}
      <div className="card space-y-3">
        <h2 className="text-lg font-semibold">Add by product URL</h2>
        <form onSubmit={doPreview} className="flex gap-2">
          <input className="input" type="url" required placeholder="https://www.bestbuy.ca/en-ca/product/..." value={url}
            onChange={(e) => setUrl(e.target.value)} />
          <button className="btn-ghost" disabled={busy}>{busy && !preview ? "Reading..." : "Preview"}</button>
        </form>
        {preview && (
          <div className="space-y-3 border-t border-slate-200 pt-3 dark:border-slate-800">
            <div className="flex gap-3">
              {p?.image && <img src={p.image} alt="" className="h-20 w-20 rounded object-contain" />}
              <div className="text-sm">
                <div className="font-medium">{preview.retailer}</div>
                {p?.price_cents != null ? (
                  <div>
                    <span className="text-lg font-bold">{money(p.price_cents)}</span>
                    {p.was_price_cents && <span className="ml-2 text-slate-500 line-through">{money(p.was_price_cents)}</span>}
                    {p.in_stock === false && <span className="ml-2 text-amber-600">out of stock</span>}
                  </div>
                ) : (
                  <div className="text-amber-700">
                    No price found ({preview.error || preview.outcome}). You can still save it and add prices by hand,
                    or switch this retailer to browser mode on the System page.
                  </div>
                )}
                {(p?.brand || p?.mpn || p?.gtin) && (
                  <div className="text-xs text-slate-500">{[p?.brand, p?.mpn, p?.gtin].filter(Boolean).join(" · ")}</div>
                )}
              </div>
            </div>
            <div>
              <label className="label">Name</label>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="flex gap-3">
              <div className="flex-1">
                <label className="label">Target price (before tax)</label>
                <input className="input" inputMode="decimal" placeholder="e.g. 349.99" value={target} onChange={(e) => setTarget(e.target.value)} />
              </div>
              <label className="mt-6 flex items-center gap-2 text-sm">
                <input type="checkbox" checked={hot} onChange={(e) => setHot(e.target.checked)} /> Hot (every 2 h)
              </label>
            </div>
            <button className="btn-primary" onClick={save} disabled={busy}>Save to wishlist</button>
          </div>
        )}
        {error && <p className="text-sm text-red-600">{error}</p>}
      </div>

      <div className="card space-y-3 md:col-span-2">
        <h2 className="text-lg font-semibold">Paste a list</h2>
        <p className="text-sm text-slate-500">One product URL or product name per line. URLs are filled in by their first check.</p>
        <textarea className="input font-mono" rows={5} value={list} onChange={(e) => setList(e.target.value)}
          placeholder={"https://www.bestbuy.ca/en-ca/product/...\nhttps://www.canadiantire.ca/en/pdp/...\nLEGO Titanic 10294"} />
        <div className="flex items-center gap-3">
          <button className="btn-ghost" disabled={busy || !list.trim()} onClick={async () => {
            setBusy(true);
            try {
              const r = await api<{ created: unknown[]; skipped: { line: string; reason: string }[] }>("/api/import", { method: "POST", json: { text: list, list_id: chosenList } });
              setImportResult(`Added ${r.created.length}${r.skipped.length ? `, skipped ${r.skipped.length} (${r.skipped.map((x) => x.reason).join("; ")})` : ""}.`);
              setList("");
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}>Import</button>
          {importResult && <span className="text-sm text-green-700">{importResult}</span>}
        </div>
      </div>

      <div className="card space-y-2 text-sm md:col-span-2">
        <h2 className="text-lg font-semibold">Add from anywhere</h2>
        <p>
          <b>Bookmarklet:</b> drag this to your bookmarks bar, then click it on any product page:{" "}
          <a className="btn-ghost px-2 py-1" href={`javascript:window.open('${location.origin}/share?url='+encodeURIComponent(location.href)+'&title='+encodeURIComponent(document.title))`}
            onClick={(e) => e.preventDefault()}>+ PriceWatch</a>
        </p>
        <p><b>Android:</b> install PriceWatch to your home screen (browser menu, Install app), then use Share, PriceWatch from any shopping app.</p>
        <p><b>iPhone:</b> make a Shortcut that accepts URLs from the Share Sheet and runs "Get contents of URL" with
          method POST to <code>{location.origin}/api/items/from-url</code>, header <code>Authorization: Bearer &lt;your API token&gt;</code>
          (Settings page) and JSON body <code>{`{"url": Shortcut Input}`}</code>.</p>
      </div>

      <form onSubmit={createByName} className="card space-y-3">
        <h2 className="text-lg font-semibold">Add by name</h2>
        <p className="text-sm text-slate-500">
          Creates the item and, when a search provider is configured, looks it up on Google Shopping (Canada). You confirm
          or reject each suggested listing on the item page.
        </p>
        <input className="input" required placeholder="Name, e.g. Sony WH-1000XM6 Headphones Black" value={manualName} onChange={(e) => setManualName(e.target.value)} />
        <div className="flex gap-2">
          <input className="input" placeholder="Brand (optional)" value={brand} onChange={(e) => setBrand(e.target.value)} />
          <input className="input" placeholder="Model / MPN (optional)" value={model} onChange={(e) => setModel(e.target.value)} />
        </div>
        <input className="input" inputMode="decimal" placeholder="Target price (optional)" value={target} onChange={(e) => setTarget(e.target.value)} />
        <button className="btn-ghost" disabled={busy}>{busy ? "Working..." : "Create and search"}</button>
      </form>
    </div>
  );
}
