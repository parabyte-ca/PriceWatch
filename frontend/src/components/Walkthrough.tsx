import { useState } from "react";
import { Link } from "react-router-dom";

interface Step { icon: string; title: string; text: string[]; to?: string; go?: string }

export const STEPS: Step[] = [
  {
    icon: "👋", title: "Welcome to PriceWatch",
    text: [
      "Tell PriceWatch what you want to buy and it compares every Canadian store's price, with tax and shipping for your province.",
      "It keeps checking about daily and tells you when a price is really good, using its own price history, not the store's \"was\" price.",
    ],
  },
  {
    icon: "➕", title: "Add something",
    text: [
      "On Add, type a product name, paste a store link, scan a barcode or take a photo of the product or its box.",
      "You get every store's price, cheapest first. Press Watch to track them all.",
      "Wrong product in the list? Tap Not this. Only one store matters to you? Tap Only this.",
    ],
    to: "/add", go: "Open Add",
  },
  {
    icon: "🏠", title: "Home: what to buy now",
    text: [
      "Buy now at the top lists items at a good price today. Below are today's biggest drops on your items and matching forum deals.",
      "Deals by category follows kinds of products (TVs, kitchen, 3D printers...) and collects their sales. Tap Watch on a deal to track it.",
    ],
    to: "/", go: "Open Home",
  },
  {
    icon: "📈", title: "An item's page",
    text: [
      "Tap any item to see its verdict (buy, wait, or buy and keep watching), every store's price, the price history and \"Will it get cheaper?\".",
      "Set a target price there and you are alerted when any store reaches it. Verify asks for a fresh price from a store right now.",
    ],
  },
  {
    icon: "🔔", title: "Get alerts on your phone",
    text: [
      "In Settings, add an ntfy link under Apprise URLs or turn on notifications for this device, then send a test.",
      "Alerts have Open store, Bought and Snooze 24h buttons, so you can act straight from the notification.",
    ],
    to: "/settings", go: "Open Settings",
  },
  {
    icon: "🧾", title: "After you buy",
    text: [
      "Press Bought on the item (or in the alert), or photograph your receipt on the Bought page.",
      "PriceWatch keeps watching that store. If the price drops while you can still claim it, you get a note with what to show the store.",
    ],
    to: "/purchases", go: "Open Bought",
  },
  {
    icon: "🎁", title: "Lists, sharing and gifts",
    text: [
      "Keep several lists on the Lists page and share one with a household member.",
      "On a shared gift list, tap I'll buy this so others know. The person the list is for never sees who is buying what.",
      "A Family link lets relatives see a list without an account.",
    ],
    to: "/lists", go: "Open Lists",
  },
  {
    icon: "🛍️", title: "Black Friday plan",
    text: [
      "Pick what you mean to buy and set a budget. Each item says Buy now, Wait for a sale or Any time, with the best store.",
      "On Black Friday, Cyber Monday and Boxing Day mornings you get the plan as a checklist. Try Practice run to check your alerts work.",
    ],
    to: "/plan", go: "Open the plan",
  },
  {
    icon: "💬", title: "Ask PriceWatch",
    text: [
      "When the household admin has added a Claude key, the Ask PriceWatch button answers questions about your lists and prices in plain language.",
      "You can open this walkthrough again any time from Me.",
    ],
  },
];

/** A short tour of the app: shown once after signing in, and any time from Me. */
export default function Walkthrough({ onClose }: { onClose: () => void }) {
  const [n, setN] = useState(0);
  const step = STEPS[n];
  const last = n === STEPS.length - 1;
  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center bg-black/50 p-0 sm:items-center sm:p-4" role="dialog"
      aria-modal="true" aria-labelledby="tour-title">
      <div className="w-full max-w-md rounded-t-2xl bg-white p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] shadow-xl sm:rounded-2xl dark:bg-slate-900">
        <div className="flex items-start justify-between gap-2">
          <span className="text-4xl" aria-hidden>{step.icon}</span>
          <button className="text-sm text-slate-500 hover:underline" onClick={onClose}>Skip</button>
        </div>
        <h2 id="tour-title" className="mt-2 text-lg font-semibold">{step.title}</h2>
        <div className="mt-2 space-y-2 text-sm text-slate-700 dark:text-slate-300">
          {step.text.map((t) => <p key={t}>{t}</p>)}
        </div>
        {step.to && (
          <Link to={step.to} onClick={onClose} className="mt-3 inline-block text-sm text-red-700 hover:underline dark:text-red-400">
            {step.go} →
          </Link>
        )}
        <div className="mt-4 flex items-center justify-between gap-2">
          <div className="flex gap-1" aria-label={`Step ${n + 1} of ${STEPS.length}`}>
            {STEPS.map((s, i) => (
              <button key={s.title} onClick={() => setN(i)} aria-label={`Step ${i + 1}: ${s.title}`}
                className={`h-2 w-2 rounded-full ${i === n ? "bg-red-700" : "bg-slate-300 dark:bg-slate-700"}`} />
            ))}
          </div>
          <div className="flex gap-2">
            {n > 0 && <button className="btn-ghost" onClick={() => setN(n - 1)}>Back</button>}
            <button className="btn-primary" onClick={() => (last ? onClose() : setN(n + 1))}>{last ? "Done" : "Next"}</button>
          </div>
        </div>
      </div>
    </div>
  );
}

const key = (userId: number) => `pw-tour-done-${userId}`;

export function tourDone(userId: number): boolean {
  try { return localStorage.getItem(key(userId)) === "1"; } catch { return true; }
}

export function markTourDone(userId: number) {
  try { localStorage.setItem(key(userId), "1"); } catch { /* private window: shown again next time */ }
}
