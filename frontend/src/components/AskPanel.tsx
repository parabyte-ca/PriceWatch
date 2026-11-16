import { FormEvent, useEffect, useRef, useState } from "react";
import { api } from "../api";

const SUGGESTIONS = [
  "What should I buy now, and what should I wait on?",
  "Will the headphones get cheaper before Boxing Day?",
  "How much have we saved so far?",
  "Can I get anything price-matched cheaper?",
];

const TOOL_LABEL: Record<string, string> = {
  list_items: "your items", item_detail: "item details", purchases: "purchases", savings: "savings", lists: "lists",
  plan_basket: "basket plan", store_policies: "store policies", perks: "perks", recent_alerts: "alerts", sale_calendar: "sale dates",
};

type Msg = { role: "user" | "assistant"; content: string; tools?: string[] };

/** Ask PriceWatch: a chat panel, shown once the household admin has saved a Claude key. Same design as Ask NetWatch. */
export default function AskPanel() {
  const [available, setAvailable] = useState(false);
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const log = useRef<HTMLDivElement>(null);

  useEffect(() => { api<{ available: boolean }>("/api/ask").then((s) => setAvailable(s.available), () => setAvailable(false)); }, [open]);
  useEffect(() => { const el = log.current; if (el) el.scrollTop = el.scrollHeight; }, [msgs, busy, error]);

  async function send(q: string) {
    const question = q.trim();
    if (!question || busy) return;
    const history: Msg[] = [...msgs, { role: "user", content: question }];
    setMsgs(history); setText(""); setBusy(true); setError(null);
    try {
      const r = await api<{ answer: string; tools: string[] }>("/api/ask", { method: "POST", json: { messages: history.map(({ role, content }) => ({ role, content })) } });
      setMsgs([...history, { role: "assistant", content: r.answer || "(no answer)", tools: r.tools || [] }]);
    } catch (e) {
      setError((e as Error).message); setMsgs(msgs); setText(question);
    } finally {
      setBusy(false);
    }
  }
  const submit = (e: FormEvent) => { e.preventDefault(); void send(text); };

  if (!available && !open) return null;
  return (
    <>
      {!open && (
        <button onClick={() => setOpen(true)}
          className="fixed bottom-20 right-4 z-30 rounded-full bg-red-700 px-4 py-2.5 text-sm font-medium text-white shadow-lg hover:bg-red-800 md:bottom-4">
          Ask PriceWatch
        </button>
      )}
      {open && (
        <aside aria-label="Ask PriceWatch"
          className="fixed inset-x-0 bottom-0 z-50 flex max-h-[85dvh] flex-col rounded-t-xl bg-white shadow-2xl ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-700 sm:inset-x-auto sm:bottom-4 sm:right-4 sm:h-[36rem] sm:w-[26rem] sm:rounded-xl">
          <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2 dark:border-slate-800">
            <h2 className="text-sm font-semibold">Ask PriceWatch</h2>
            <div className="flex gap-2">
              {msgs.length > 0 && <button onClick={() => setMsgs([])} className="text-xs text-slate-500 hover:underline">New chat</button>}
              <button onClick={() => setOpen(false)} aria-label="Close" className="px-1 text-slate-500">✕</button>
            </div>
          </div>
          <div ref={log} className="min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain p-4 text-sm" aria-live="polite">
            {msgs.length === 0 && (
              <div className="space-y-2">
                <p className="text-slate-500">Ask about your lists, prices, purchases and savings. Answers come from PriceWatch's own data; Claude can't change anything.</p>
                {SUGGESTIONS.map((s) => (
                  <button key={s} onClick={() => void send(s)} className="block w-full rounded-md bg-slate-100 px-3 py-2 text-left hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700">{s}</button>
                ))}
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={m.role === "user" ? "ml-8 rounded-lg bg-red-50 px-3 py-2 dark:bg-red-950/40" : "mr-4"}>
                <div className="whitespace-pre-wrap break-words">{m.content}</div>
                {m.tools && m.tools.length > 0 && (
                  <div className="mt-1 text-[11px] text-slate-500">Looked at: {[...new Set(m.tools)].map((t) => TOOL_LABEL[t] ?? t).join(", ")}</div>
                )}
              </div>
            ))}
            {busy && <p className="text-slate-500">Looking into it…</p>}
            {error && <p role="alert" className="text-red-600">{error}</p>}
          </div>
          <form onSubmit={submit} className="flex gap-2 border-t border-slate-200 p-3 dark:border-slate-800">
            <input aria-label="Question" className="input" placeholder={available ? "Ask about your list…" : "The household admin needs to add a Claude key"}
              value={text} maxLength={2000} disabled={!available} onChange={(e) => setText(e.target.value)} />
            <button type="submit" disabled={busy || !text.trim() || !available} className="btn-primary">Ask</button>
          </form>
        </aside>
      )}
    </>
  );
}
