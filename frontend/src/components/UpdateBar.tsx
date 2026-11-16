import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import type { UpdateProgressInfo } from '../lib/updateProgress';
import { isActive, knownEstimate, progressFraction, readPending, startedAt, UPDATE_STAGES } from '../lib/updateProgress';
import { effectiveStages } from './UpdateProgress';

/** A slim bar across the top of every page while an update runs, and the percentage in the tab
 * title. Also shown while PriceWatch restarts mid-update (the server does not answer then). */
export function UpdateBar({ summary, offline }: { summary: { progress: UpdateProgressInfo } | null; offline: boolean }) {
  const [now, setNow] = useState(Date.now());
  const pending = readPending(now);
  const p = summary?.progress;
  const show = isActive(p?.state) || (offline && !!pending);
  useEffect(() => {
    if (!show) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [show]);

  const stages = p ? effectiveStages(p, offline) : UPDATE_STAGES;
  const begin = startedAt(p, pending) ?? now;
  const best = useRef(0);
  const frac = show ? progressFraction(stages, (now - begin) / 1000, knownEstimate(p?.estimate_s), false) : 0;
  best.current = show ? Math.max(best.current, frac) : 0;
  const pct = Math.round(100 * best.current);

  useEffect(() => {
    if (!show) return;
    const before = document.title.replace(/^\d+% · /, '');
    document.title = `${pct}% · ${before}`;
    return () => {
      document.title = before;
    };
  }, [show, pct]);

  if (!show) return null;
  return (
    <Link to="/system" title={`Updating PriceWatch: ${pct}%`} aria-label={`Update in progress, ${pct}%`}
      className="fixed inset-x-0 top-[env(safe-area-inset-top)] z-50 block h-[3px] bg-slate-200/80 dark:bg-slate-800/80 print:hidden">
      <span className="relative block h-full overflow-hidden bg-gradient-to-r from-red-600 via-amber-500 to-emerald-500 shadow-[0_0_10px_rgba(245,158,11,0.8)] transition-[width] duration-1000 ease-linear"
        style={{ width: `${Math.max(3, pct)}%` }}>
        <span className="absolute inset-y-0 left-0 w-1/4 bg-gradient-to-r from-transparent via-white/70 to-transparent motion-safe:animate-sweep" />
      </span>
    </Link>
  );
}
