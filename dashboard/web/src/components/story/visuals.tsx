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
export function ScoreRing({
  score,
  size = 120,
  stroke,
  label = "score",
  fmt = (v) => v.toFixed(2),
}: {
  score: number | null;
  size?: number;
  stroke?: number;
  label?: string;
  fmt?: (v: number) => string;
}) {
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
          {isNum(score) ? fmt(v) : "–"}
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

/**
 * Where the deal sits on one cost axis (C per year, cheaper to the left): their opening, our deal,
 * the walk-away alternative. Markers alternate above / below so close values never collide.
 */
export function CostScale({ cOpen, cDeal, cAlt }: { cOpen: number | null; cDeal: number | null; cAlt: number | null }) {
  const pts = [
    { k: "open", label: "Their opening", c: cOpen, cls: "bg-ink-3", text: "text-ink-2" },
    { k: "alt", label: "Walk away", c: cAlt, cls: "bg-ink-4", text: "text-ink-3" },
    { k: "deal", label: "Our deal", c: cDeal, cls: "bg-accent", text: "text-accent-deep" },
  ].filter((p): p is typeof p & { c: number } => isNum(p.c));
  const [on, setOn] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setOn(true));
    return () => cancelAnimationFrame(id);
  }, []);
  if (pts.length < 2) return null;
  const lo = Math.min(...pts.map((p) => p.c));
  const hi = Math.max(...pts.map((p) => p.c));
  const span = Math.max(1, hi - lo);
  const x = (c: number) => 6 + ((c - lo) / span) * 88; // % of width, 6 % margin each side
  const sorted = [...pts].sort((a, b) => a.c - b.c);
  const deal = pts.find((p) => p.k === "deal");
  return (
    <div className="w-full">
      <div className="relative h-[92px]">
        <div className="absolute left-0 right-0 top-[44px] h-[3px] rounded-full bg-paper-3" />
        {deal && (
          <div
            className="absolute top-[44px] h-[3px] rounded-full bg-accent transition-all duration-1000"
            style={{ left: `${x(deal.c)}%`, width: on ? `${Math.max(0, x(Math.max(...pts.map((p) => p.c))) - x(deal.c))}%` : "0%" }}
          />
        )}
        {sorted.map((p, i) => {
          const up = i % 2 === 0;
          const isDeal = p.k === "deal";
          return (
            <div key={p.k} className="absolute -translate-x-1/2" style={{ left: `${x(p.c)}%`, top: 0 }}>
              <div className={cx("absolute left-1/2 -translate-x-1/2 whitespace-nowrap text-center leading-tight", up ? "top-0" : "top-[58px]")}>
                <div className={cx("text-[0.68rem]", isDeal ? "font-semibold" : "", p.text)}>{p.label}</div>
                <div className={cx("font-mono text-[0.74rem] tabular-nums", isDeal ? "font-semibold text-ink" : "text-ink-2")}>{eurShort(p.c)}</div>
              </div>
              <span
                className={cx("absolute left-1/2 top-[45.5px] -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-white", p.cls, isDeal ? "h-4 w-4" : "h-2.5 w-2.5")}
              />
            </div>
          );
        })}
      </div>
      <div className="flex justify-between text-[0.62rem] uppercase tracking-[0.12em] text-ink-4">
        <span>← cheaper for us</span>
        <span>total cost per year</span>
      </div>
    </div>
  );
}
