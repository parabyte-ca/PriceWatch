const STYLES: Record<string, string> = {
  "BUY NOW": "bg-green-600 text-white",
  "BUY + PROTECT": "bg-teal-600 text-white",
  GOOD: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100",
  WAIT: "bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-200",
  "FAKE SALE": "bg-amber-500 text-black",
  "NO DATA": "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
};

export default function Badge({ value }: { value: string }) {
  return (
    <span className={`inline-block whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-bold ${STYLES[value] || STYLES.WAIT}`}>
      {value}
    </span>
  );
}

export function Confidence({ level, days }: { level: string; days?: number }) {
  const cls = level === "HIGH" ? "text-green-700" : level === "MEDIUM" ? "text-amber-700" : "text-slate-500";
  return (
    <span className={`text-xs ${cls}`} title="How much price history backs this verdict: LOW under 14 days, MEDIUM 14 to 59, HIGH 60+">
      {level.toLowerCase()} history{days != null ? ` (${days} d)` : ""}
    </span>
  );
}
