import { useEffect, useState } from "react";
import { api } from "../api";

function b64ToBytes(b64: string): Uint8Array<ArrayBuffer> {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

type State = "unsupported" | "insecure" | "off" | "on" | "denied" | "busy";

export default function PushToggle() {
  const [state, setState] = useState<State>("busy");
  const [msg, setMsg] = useState("");

  const sub = async () => (await navigator.serviceWorker.ready).pushManager.getSubscription();

  useEffect(() => {
    if (!window.isSecureContext) return setState("insecure");
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) return setState("unsupported");
    if (Notification.permission === "denied") return setState("denied");
    sub().then((s) => setState(s ? "on" : "off")).catch(() => setState("off"));
  }, []);

  const turnOn = async () => {
    setMsg("");
    setState("busy");
    try {
      const perm = await Notification.requestPermission();
      if (perm !== "granted") return setState(perm === "denied" ? "denied" : "off");
      const { public_key } = await api<{ public_key: string }>("/api/push/key");
      const reg = await navigator.serviceWorker.ready;
      const s = (await reg.pushManager.getSubscription()) ||
        (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(public_key) }));
      const json = s.toJSON();
      await api("/api/push/subscribe", { method: "POST", json: { endpoint: json.endpoint, keys: json.keys, user_agent: navigator.userAgent.slice(0, 300) } });
      setState("on");
    } catch (e) {
      setMsg((e as Error).message);
      setState("off");
    }
  };

  const turnOff = async () => {
    setState("busy");
    try {
      const s = await sub();
      if (s) {
        await api("/api/push/unsubscribe", { method: "POST", json: { endpoint: s.endpoint } });
        await s.unsubscribe();
      }
    } finally {
      setState("off");
    }
  };

  const test = () =>
    api<{ sent: number }>("/api/push/test", { method: "POST" })
      .then(() => setMsg("Test sent"))
      .catch((e) => setMsg((e as Error).message));

  return (
    <div className="space-y-2 border-t border-slate-200 pt-3 dark:border-slate-800">
      <div className="font-medium">Notifications on this device</div>
      {state === "insecure" && (
        <p className="text-xs text-slate-500">Needs HTTPS (Tailscale Serve or the reverse proxy). Plain http:// on the LAN cannot receive app notifications.</p>
      )}
      {state === "unsupported" && (
        <p className="text-xs text-slate-500">This browser cannot receive app notifications. On iPhone/iPad, add PriceWatch to the home screen first (iOS 16.4 or later) and open it from there.</p>
      )}
      {state === "denied" && <p className="text-xs text-slate-500">Notifications are blocked for this site in the browser settings.</p>}
      <div className="flex flex-wrap gap-2">
        {(state === "off" || state === "busy") && (
          <button className="btn-ghost" disabled={state === "busy"} onClick={turnOn}>Turn on for this device</button>
        )}
        {state === "on" && (
          <>
            <button className="btn-ghost" onClick={test}>Send test to my devices</button>
            <button className="btn-ghost" onClick={turnOff}>Turn off for this device</button>
          </>
        )}
      </div>
      {msg && <p className="text-xs text-slate-500">{msg}</p>}
      <p className="text-xs text-slate-500">Works alongside the Apprise/ntfy URLs above. Alerts come with Open and Snooze buttons.</p>
    </div>
  );
}
