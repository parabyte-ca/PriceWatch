import { useState } from "react";
import { api, Item, money, toCents, toDollars } from "../api";

interface Line { name: string; price_cents: number | null; quantity: number; item_id: number | null }
interface ReadResult { is_receipt: boolean; store: string | null; date: string | null; lines: Line[] }

/** Bought: photograph a store receipt; Claude reads it, you check which items it bought, then Save. */
export default function ReceiptScan({ onSaved }: { onSaved: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [r, setR] = useState<ReadResult | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [rows, setRows] = useState<{ item: string; price: string; keep: boolean }[]>([]);

  const read = async (file: File) => {
    setBusy(true); setError(""); setR(null);
    try {
      const bmp = await createImageBitmap(file);
      const scale = Math.min(1, 1600 / Math.max(bmp.width, bmp.height));
      const c = document.createElement("canvas"); c.width = Math.round(bmp.width * scale); c.height = Math.round(bmp.height * scale);
      c.getContext("2d")?.drawImage(bmp, 0, 0, c.width, c.height);
      const [res, its] = await Promise.all([
        api<ReadResult>("/api/purchases/receipt/read", { method: "POST", json: { image_b64: c.toDataURL("image/jpeg", 0.9).split(",")[1] } }),
        api<Item[]>("/api/items"),
      ]);
      if (!res.is_receipt) { setError("That does not look like a receipt. Try again with the whole receipt in the photo."); return; }
      setItems(its); setR(res);
      setRows(res.lines.map((l) => ({ item: l.item_id ? String(l.item_id) : "", price: toDollars(l.price_cents), keep: !!l.item_id })));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (!r) return;
    const lines = rows.map((x, i) => ({ ...x, i })).filter((x) => x.keep && x.item && toCents(x.price))
      .map((x) => ({ item_id: Number(x.item), price_cents: toCents(x.price) as number, name: r.lines[x.i].name }));
    if (!lines.length) { setError("Pick at least one line and its item."); return; }
    setBusy(true);
    try {
      const s = await api<{ saved: number; skipped: number }>("/api/purchases/receipt/save", { method: "POST", json: { store: r.store, date: r.date, lines } });
      setR(null); setError(`Saved ${s.saved} purchase${s.saved === 1 ? "" : "s"}${s.skipped ? ` (${s.skipped} already recorded)` : ""}; price protection is on.`);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card space-y-2 text-sm">
      <label className="btn-ghost w-full cursor-pointer">
        {busy && !r ? "Reading the receipt…" : "🧾 Add purchases from a receipt photo"}
        <input type="file" accept="image/*" capture="environment" className="hidden" disabled={busy}
          onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void read(f); }} />
      </label>
      {error && <p className={error.startsWith("Saved") ? "text-green-700 dark:text-green-400" : "text-red-600"}>{error}</p>}
      {r && (
        <div className="space-y-2">
          <div className="text-slate-500">{[r.store, r.date].filter(Boolean).join(" · ")}. Tick the lines you want recorded and check the item for each.</div>
          {r.lines.map((l, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-2 dark:border-slate-800">
              <input type="checkbox" checked={rows[i].keep} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, keep: e.target.checked } : x)))} aria-label={`Record ${l.name}`} />
              <span className="min-w-0 flex-1 truncate font-mono text-xs" title={l.name}>{l.name}</span>
              <input className="input w-24 py-1" inputMode="decimal" value={rows[i].price}
                onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, price: e.target.value } : x)))} aria-label="Price" />
              <select className="input w-full py-1 sm:w-56" value={rows[i].item}
                onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, item: e.target.value, keep: !!e.target.value } : x)))}>
                <option value="">Not one of my items</option>
                {items.map((it) => <option key={it.id} value={it.id}>{it.name}</option>)}
              </select>
            </div>
          ))}
          <div className="flex gap-2">
            <button className="btn-primary" disabled={busy} onClick={save}>Save purchases</button>
            <button className="btn-ghost" onClick={() => setR(null)}>Cancel</button>
          </div>
          <p className="text-xs text-slate-500">Receipt total {money(r.lines.reduce((t, l) => t + (l.price_cents || 0) * (l.quantity || 1), 0))} before tax (lines read).</p>
        </div>
      )}
    </div>
  );
}
