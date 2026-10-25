import { useEffect, useRef, useState } from "react";
import { eur, eurShort } from "../../lib/format";
import { cx, useTween } from "../ui";

const isNum = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);

const reducedMotion = () => {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
};

export function useWidth<T extends HTMLElement>(initial = 600) {
  const ref = useRef<T>(null);
  const [w, setW] = useState(initial);
  useEffect(() => {
    if (!ref.current) return;
    setW(Math.max(160, ref.current.clientWidth));
    const ro = new ResizeObserver(([e]) => setW(Math.max(160, e.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return { ref, w };
}

/** Score 0..1 as a ring; the arc animates in. */
export function ScoreRing({ score, size = 120, stroke, label = "score" }: { score: number | null; size?: number; stroke?: number; label?: string }) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    const id = requestAnimationFrame(() => setShown(score ?? 0));
    return () => cancelAnimationFrame(id);
  }, [score]);
  const tv = useTween(shown, 900) ?? 0;
  const v = reducedMotion() ? (score ?? 0) : tv;
  const sw = stroke ?? Math.max(4, size / 11);
  const r = (size - sw) / 2;
  const c = 2 * Math.PI * r;
  const small = size < 70;
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#F1F1EE" strokeWidth={sw} />
        {isNum(score) && (
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke="#FF5A1F"
            strokeWidth={sw}
            strokeLinecap="round"
            strokeDasharray={`${c * Math.min(1, Math.max(0, v))} ${c}`}
          />
        )}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={cx("font-semibold tabular-nums tracking-tight text-ink", small ? "text-[0.8rem]" : "")} style={small ? undefined : { fontSize: size * 0.26 }}>
          {isNum(score) ? v.toFixed(2) : "–"}
        </span>
        {!small && <span className="text-[0.62rem] uppercase tracking-[0.14em] text-ink-3">{label}</span>}
      </div>
    </div>
  );
}

/** Tiny price-convergence line: supplier standing (solid) and our asks (dashed). */
export function Sparkline({
  supplier,
  ours,
  best,
  w = 140,
  h = 36,
}: {
  supplier: (number | null)[];
  ours: (number | null)[];
  best?: number | null;
  w?: number;
  h?: number;
}) {
  const vals = [...supplier, ...ours, best].filter(isNum);
  if (vals.length < 2) return <div style={{ width: w, height: h }} />;
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const n = Math.max(supplier.length, ours.length + 1, 2);
  const x = (i: number) => 2 + (i / (n - 1)) * (w - 4);
  const y = (v: number) => (hi === lo ? h / 2 : 3 + (1 - (v - lo) / (hi - lo)) * (h - 6));
  const path = (pts: (number | null)[], off = 0) =>
    pts
      .map((v, i) => (isNum(v) ? `${x(i + off).toFixed(1)},${y(v).toFixed(1)}` : null))
      .filter(Boolean)
      .map((p, i) => (i ? "L" : "M") + p)
      .join(" ");
  const lastS = [...supplier].reverse().find(isNum);
  const lastI = supplier.length - 1 - [...supplier].reverse().findIndex(isNum);
  return (
    <svg width={w} height={h} className="overflow-visible">
      {isNum(best) && <line x1={0} x2={w} y1={y(best)} y2={y(best)} stroke="#A1A1A6" strokeDasharray="2 3" strokeWidth={1} />}
      <path d={path(ours, 1)} fill="none" stroke="#0B0B0C" strokeWidth={1.4} strokeDasharray="3 2" opacity={0.55} />
      <path d={path(supplier)} fill="none" stroke="#FF5A1F" strokeWidth={2} strokeLinejoin="round" />
      {isNum(lastS) && <circle cx={x(lastI)} cy={y(lastS)} r={3} fill="#FF5A1F" />}
    </svg>
  );
}

/** Opening → deal → best as one bar: how much of the reachable saving we captured. */
export function CaptureBar({
  cOpen,
  cDeal,
  cBest,
  cAlt,
  big = false,
}: {
  cOpen: number | null;
  cDeal: number | null;
  cBest: number | null;
  cAlt?: number | null;
  big?: boolean;
}) {
  const ok = isNum(cOpen) && isNum(cBest) && cOpen > cBest;
  const k = ok && isNum(cDeal) ? Math.min(1, Math.max(0, (cOpen! - cDeal) / (cOpen! - cBest!))) : 0;
  const [shown, setShown] = useState(0);
  useEffect(() => {
    const id = requestAnimationFrame(() => setShown(k));
    return () => cancelAnimationFrame(id);
  }, [k]);
  const tt = useTween(shown, 1100) ?? 0;
  const tk = reducedMotion() ? k : tt;
  if (!ok) return null;
  return (
    <div className="w-full">
      <div className={cx("relative rounded-full bg-paper-3", big ? "h-4" : "h-2.5")}>
        <div className="absolute inset-y-0 left-0 rounded-full bg-accent" style={{ width: `${tk * 100}%` }} />
        <div className="absolute inset-y-0 right-0 w-[3px] rounded-r-full bg-ink" />
      </div>
      <div className="mt-2 grid grid-cols-3 text-[0.72rem] leading-tight">
        <div>
          <div className="text-ink-3">Their opening</div>
          <div className="font-mono tabular-nums text-ink-2">{eurShort(cOpen)}</div>
        </div>
        <div className="text-center">
          <div className="font-medium text-accent-deep">Our deal</div>
          <div className="font-mono font-semibold tabular-nums text-ink">{isNum(cDeal) ? eurShort(cDeal) : "–"}</div>
        </div>
        <div className="text-right">
          <div className="text-ink-3">Best possible</div>
          <div className="font-mono tabular-nums text-ink-2">{eurShort(cBest)}</div>
        </div>
      </div>
      {isNum(cAlt) && (
        <div className="mt-1.5 text-[0.7rem] text-ink-3">
          Walk-away alternative <span className="font-mono tabular-nums">{eur(cAlt)}</span>
        </div>
      )}
    </div>
  );
}

const TONE: Record<string, string> = {
  ink: "border-ink bg-ink text-white",
  accent: "border-accent/50 bg-accent-soft text-accent-deep",
  muted: "border-line bg-paper-2 text-ink-2",
  good: "border-ink bg-ink text-white",
  bad: "border-accent bg-accent text-white",
};

export function IconChip({ icon, label, detail, tone = "muted", title }: { icon?: string; label: string; detail?: string; tone?: string; title?: string }) {
  return (
    <span title={title} className={cx("inline-flex max-w-full items-center gap-1.5 rounded-lg border px-2 py-1 text-[0.74rem] font-medium", TONE[tone])}>
      {icon && <span aria-hidden className="text-[0.8rem] leading-none">{icon}</span>}
      <span className="truncate">{label}</span>
      {detail && <span className="truncate font-mono text-[0.7rem] opacity-75">{detail}</span>}
    </span>
  );
}
