import { useEffect, useRef, useState } from "react";
import { api, money } from "../api";

interface Lookup { gtin: string; provider: string | null; names: { title: string; brand: string | null; exact: boolean; merchant: string | null; price_cents: number | null }[] }

// BarcodeDetector is in Chrome/Edge on Android and desktop; not yet in Safari, so typing the number is the fallback.
type Detector = { detect: (src: HTMLVideoElement) => Promise<{ rawValue: string }[]> };
const DetectorCtor = (window as unknown as { BarcodeDetector?: new (o: { formats: string[] }) => Detector }).BarcodeDetector;

export default function BarcodeScan({ onPick }: { onPick: (name: string, brand: string | null, gtin: string) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [scanning, setScanning] = useState(false);
  const [code, setCode] = useState("");
  const [result, setResult] = useState<Lookup | null>(null);
  const [error, setError] = useState("");
  const canScan = Boolean(DetectorCtor) && window.isSecureContext && !!navigator.mediaDevices?.getUserMedia;

  const lookup = (value: string) => {
    setError(""); setResult(null);
    api<Lookup>(`/api/barcode/${encodeURIComponent(value)}`).then(setResult).catch((e) => setError((e as Error).message));
  };

  useEffect(() => {
    if (!scanning || !DetectorCtor) return;
    let stream: MediaStream | null = null;
    let stop = false;
    const detector = new DetectorCtor({ formats: ["ean_13", "ean_8", "upc_a", "upc_e"] });
    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
        if (!video.current) return;
        video.current.srcObject = stream;
        await video.current.play();
        while (!stop) {
          const found = await detector.detect(video.current).catch(() => []);
          if (found.length) {
            const value = found[0].rawValue;
            setCode(value);
            setScanning(false);
            lookup(value);
            break;
          }
          await new Promise((r) => setTimeout(r, 250));
        }
      } catch (e) {
        setError(`Camera: ${(e as Error).message}`);
        setScanning(false);
      }
    })();
    return () => { stop = true; stream?.getTracks().forEach((t) => t.stop()); };
  }, [scanning]);

  return (
    <div className="card space-y-3">
      <h2 className="text-lg font-semibold">Scan a barcode</h2>
      <p className="text-sm text-slate-500">
        Scan the UPC on a box in a store (or type it), pick the matching product, and it is added with its barcode so matching
        is exact. {!canScan && "This browser cannot scan; type the number instead (scanning works in Chrome on Android over HTTPS)."}
      </p>
      {canScan && (
        <button className="btn-ghost" onClick={() => setScanning(!scanning)}>{scanning ? "Stop camera" : "Scan with camera"}</button>
      )}
      {scanning && <video ref={video} className="w-full rounded-lg" playsInline muted />}
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (code.trim()) lookup(code.trim()); }}>
        <input className="input font-mono" inputMode="numeric" placeholder="UPC / EAN" value={code} onChange={(e) => setCode(e.target.value)} />
        <button className="btn-ghost">Look up</button>
      </form>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {result && (
        <div className="space-y-1">
          {!result.provider && <p className="text-sm text-slate-500">No search provider is set up, so type the name below; the barcode is kept.</p>}
          {result.provider && !result.names.length && <p className="text-sm text-slate-500">No product found for {result.gtin}. Type the name below.</p>}
          {result.names.map((n) => (
            <button key={n.title} className="block w-full rounded-lg border border-slate-200 p-2 text-left text-sm hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"
              onClick={() => onPick(n.title, n.brand, result.gtin)}>
              <div className="break-words font-medium">{n.title}</div>
              <div className="text-xs text-slate-500">{[n.exact && "barcode match", n.merchant, n.price_cents != null && money(n.price_cents)].filter(Boolean).join(" · ")}</div>
            </button>
          ))}
          <button className="text-xs text-slate-500 hover:underline" onClick={() => onPick("", null, result.gtin)}>None of these: I will type the name</button>
        </div>
      )}
    </div>
  );
}
