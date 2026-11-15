import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, Item, money, toCents } from "../api";

interface Preview {
  url: string;
  retailer: string;
  outcome: string;
  error: string | null;
  method: string;
  product: { name: string | null; price_cents: number | null; was_price_cents: number | null; image: string | null;
    brand: string | null; mpn: string | null; gtin: string | null; in_stock: boolean | null; currency: string | null } | null;
}

export default function AddItem() {
  const nav = useNavigate();
  const [url, setUrl] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [name, setName] = useState("");
  const [target, setTarget] = useState("");
  const [hot, setHot] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [manualName, setManualName] = useState("");

  const doPreview = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    setPreview(null);
    try {
      const p = await api<Preview>("/api/preview", { method: "POST", json: { url: url.trim() } });
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
        json: { url: url.trim(), name: name || undefined, target_price_cents: toCents(target), hot },
      });
      nav(`/items/${item.id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  const createByName = async (e: FormEvent) => {
    e.preventDefault();
    const item = await api<Item>("/api/items", { method: "POST", json: { name: manualName, target_price_cents: toCents(target) } });
    nav(`/items/${item.id}`);
  };

  const p = preview?.product;
  return (
    <div className="grid gap-4 md:grid-cols-2">
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
                <input type="checkbox" checked={hot} onChange={(e) => setHot(e.target.checked)} /> Hot (hourly)
              </label>
            </div>
            <button className="btn-primary" onClick={save} disabled={busy}>Save to wishlist</button>
          </div>
        )}
        {error && <p className="text-sm text-red-600">{error}</p>}
      </div>

      <form onSubmit={createByName} className="card space-y-3">
        <h2 className="text-lg font-semibold">Add by name</h2>
        <p className="text-sm text-slate-500">
          Creates an empty item. Add retailer URLs or manual prices on its page. Search-based discovery arrives in v0.2.
        </p>
        <input className="input" required placeholder="e.g. Sony WH-1000XM6" value={manualName} onChange={(e) => setManualName(e.target.value)} />
        <input className="input" inputMode="decimal" placeholder="Target price (optional)" value={target} onChange={(e) => setTarget(e.target.value)} />
        <button className="btn-ghost">Create item</button>
      </form>
    </div>
  );
}
