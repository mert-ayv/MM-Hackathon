import { useEffect, useRef, useState } from "react";
import type { Thread } from "../lib/model";
import { eur, eurShort } from "../lib/format";
import { cx } from "./ui";

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(600);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(240, e.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return { ref, w };
}

const isNum = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);

export function CLine({
  threads,
  cOpen,
  cBest,
  cAlt,
  rounds,
  selected,
  onSelect,
  height = 240,
  big = false,
}: {
  threads: Thread[];
  cOpen: number | null;
  cBest: number | null;
  cAlt: number | null;
  rounds: number;
  selected?: { sid: string; round: number } | null;
  onSelect?: (sid: string, round: number) => void;
  height?: number;
  big?: boolean;
}) {
  const { ref, w } = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const fs = big ? 13 : 11;
  const m = { l: big ? 70 : 58, r: big ? 96 : 84, t: 14, b: 26 };
  const iw = w - m.l - m.r;
  const ih = height - m.t - m.b;

  const vals: number[] = [];
  for (const t of threads) {
    t.standing.forEach((s) => isNum(s.c) && vals.push(s.c));
    t.asks.forEach((a) => isNum(a.c) && vals.push(a.c));
  }
  [cOpen, cBest, cAlt].forEach((v) => isNum(v) && vals.push(v));
  if (!vals.length) vals.push(0, 1);
  let lo = Math.min(...vals);
  let hi = Math.max(...vals);
  const pad = Math.max((hi - lo) * 0.08, 1);
  lo -= pad;
  hi += pad;
  const xmax = Math.max(1, rounds);
  const X = (r: number) => m.l + (r / xmax) * iw;
  const Y = (c: number) => m.t + (1 - (c - lo) / (hi - lo)) * ih;
  const ticks = niceTicks(lo, hi, 4);

  const refs: { key: string; v: number | null; label: string; dash: string; color: string }[] = [
    { key: "open", v: cOpen, label: "C open", dash: "5 4", color: "#3A3A3D" },
    { key: "best", v: cBest, label: "C best", dash: "2 3", color: "#FF5A1F" },
    { key: "alt", v: cAlt, label: "C alt", dash: "8 3 2 3", color: "#8C93A3" },
  ];

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * w;
    const r = Math.round(((px - m.l) / iw) * xmax);
    setHover(r >= 0 && r <= xmax ? r : null);
  };

  return (
    <div ref={ref} className="relative w-full">
      <div className={cx("mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-ink-2", big ? "text-sm" : "text-[0.72rem]")}>
        {threads.map((t) => (
          <span key={t.sid} className="inline-flex items-center gap-1.5">
            <span className="h-[3px] w-4 rounded-full" style={{ background: t.color }} />
            {t.short}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5 text-ink-3">
          <svg width="10" height="10"><circle cx="5" cy="5" r="3.5" fill="white" stroke="#6E6E73" strokeWidth="1.5" /></svg>
          our ask
        </span>
      </div>
      <svg
        width={w}
        height={height}
        className="block select-none"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        onClick={() => {
          if (hover !== null && onSelect && threads[0]) {
            const sid = selected?.sid ?? threads[0].sid;
            onSelect(sid, hover);
          }
        }}
        role="img"
        aria-label="C over rounds per supplier"
      >
        {/* grid */}
        {ticks.map((t) => (
          <g key={t}>
            <line x1={m.l} x2={w - m.r} y1={Y(t)} y2={Y(t)} stroke="#F1F1EE" />
            <text x={m.l - 8} y={Y(t)} dy="0.32em" textAnchor="end" fontSize={fs} fill="#A1A1A6" className="font-mono">
              {eurShort(t)}
            </text>
          </g>
        ))}
        {Array.from({ length: xmax + 1 }, (_, r) => (
          <text key={r} x={X(r)} y={height - 6} textAnchor="middle" fontSize={fs} fill="#A1A1A6" className="font-mono">
            {r === 0 ? "open" : `R${r}`}
          </text>
        ))}
        {selected && selected.round >= 0 && (
          <rect x={X(selected.round) - Math.min(18, iw / xmax / 2)} width={Math.min(36, iw / xmax)} y={m.t} height={ih} fill="#FFF1EB" />
        )}
        {/* reference lines */}
        {refs.map((r) =>
          isNum(r.v) ? (
            <g key={r.key}>
              <line x1={m.l} x2={w - m.r} y1={Y(r.v)} y2={Y(r.v)} stroke={r.color} strokeDasharray={r.dash} strokeWidth={1.25} />
              <text x={w - m.r + 6} y={Y(r.v)} dy="0.32em" fontSize={fs} fill={r.color === "#FF5A1F" ? "#D9430E" : r.color} fontWeight={600}>
                {r.label}
              </text>
            </g>
          ) : null,
        )}
        {/* asks */}
        {threads.map((t) => {
          const pts = t.asks.filter((a) => isNum(a.c));
          return (
            <g key={`ask-${t.sid}`}>
              {pts.length > 1 && (
                <polyline points={pts.map((a) => `${X(a.round)},${Y(a.c!)}`).join(" ")} fill="none" stroke={t.color} strokeOpacity={0.35} strokeWidth={1.25} strokeDasharray="3 3" />
              )}
              {pts.map((a) => (
                <circle key={a.round} cx={X(a.round)} cy={Y(a.c!)} r={big ? 4.5 : 3.5} fill="white" stroke={t.color} strokeWidth={1.5} />
              ))}
            </g>
          );
        })}
        {/* standing offers */}
        {threads.map((t) => {
          const pts = t.standing.filter((s) => isNum(s.c));
          if (!pts.length) return null;
          const last = pts[pts.length - 1];
          const ended = t.status === "walked_away" || t.status === "no_bid";
          return (
            <g key={t.sid} opacity={ended ? 0.45 : 1}>
              <polyline
                points={pts.map((s) => `${X(s.round)},${Y(s.c!)}`).join(" ")}
                fill="none"
                stroke={t.color}
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
                style={{ transition: "all .5s ease" }}
              />
              {pts.map((s) => (
                <circle
                  key={s.round}
                  cx={X(s.round)}
                  cy={Y(s.c!)}
                  r={big ? 5.5 : 4.5}
                  fill={t.color}
                  stroke="white"
                  strokeWidth={2}
                  className="cursor-pointer"
                  onClick={(e) => {
                    e.stopPropagation();
                    onSelect?.(t.sid, s.round);
                  }}
                />
              ))}
              {threads.length > 1 && (
                <text x={X(last.round) + 9} y={Y(last.c!)} dy="0.32em" fontSize={fs} fill="#3A3A3D" fontWeight={600}>
                  {t.short}
                  {ended ? " ✕" : ""}
                </text>
              )}
            </g>
          );
        })}
        {hover !== null && <line x1={X(hover)} x2={X(hover)} y1={m.t} y2={m.t + ih} stroke="#0B0B0C" strokeOpacity={0.25} />}
      </svg>
      {hover !== null && (
        <Tooltip x={X(hover)} w={w} big={big}>
          <div className="mb-1 font-semibold">{hover === 0 ? "Opening quotes" : `Round ${hover}`}</div>
          {threads.map((t) => {
            const s = [...t.standing].reverse().find((p) => p.round <= hover);
            const a = t.asks.find((p) => p.round === hover);
            return (
              <div key={t.sid} className="flex items-center gap-2">
                <span className="h-2 w-2 rounded-full" style={{ background: t.color }} />
                <span className="text-ink-2">{t.short}</span>
                <span className="ml-auto font-mono tabular-nums">{eur(s?.c)}</span>
                {a && <span className="font-mono tabular-nums text-ink-3">ask {eur(a.c)}</span>}
              </div>
            );
          })}
        </Tooltip>
      )}
    </div>
  );
}

function Tooltip({ x, w, children, big }: { x: number; w: number; children: React.ReactNode; big: boolean }) {
  const left = x > w * 0.6;
  return (
    <div
      className={cx(
        "pointer-events-none absolute top-8 z-10 min-w-[13rem] rounded-lg border border-line bg-white/95 px-3 py-2 shadow-lg backdrop-blur",
        big ? "text-sm" : "text-xs",
      )}
      style={left ? { right: w - x + 12 } : { left: x + 12 }}
    >
      {children}
    </div>
  );
}

function niceTicks(lo: number, hi: number, n: number): number[] {
  const span = hi - lo;
  const step0 = span / n;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((s) => span / s <= n) ?? step0;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) out.push(v);
  return out;
}
