import { useState } from "react";
import type { CaseModel, Thread } from "../../lib/model";
import type { RoundStory } from "../../lib/story";
import { MOVE_ICON } from "../../lib/story";
import { eur, eurShort } from "../../lib/format";
import { useWidth } from "./visuals";

const isNum = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);

/**
 * Price convergence: each supplier's standing offer coming down, our cheapest ask going up,
 * reference lines for their opening, the walk-away alternative and the best possible deal.
 * One clickable node per round of the focused supplier.
 */
export function Convergence({
  model,
  focus,
  stories,
  selected,
  onSelect,
  height = 300,
}: {
  model: CaseModel;
  focus: Thread;
  stories: RoundStory[];
  selected: number | null;
  onSelect: (round: number) => void;
  height?: number;
}) {
  const { ref, w } = useWidth<HTMLDivElement>(900);
  const [hover, setHover] = useState<number | null>(null);
  const m = { l: 64, r: 128, t: 18, b: 64 };
  const iw = Math.max(100, w - m.l - m.r);
  const ih = height - m.t - m.b;

  const vals: number[] = [];
  for (const t of model.threads) {
    t.standing.forEach((s) => isNum(s.c) && vals.push(s.c));
    t.asks.forEach((a) => isNum(a.c) && vals.push(a.c));
  }
  [model.cOpen, model.cBest, model.cAlt].forEach((v) => isNum(v) && vals.push(v));
  if (vals.length < 2) vals.push(0, 1);
  let lo = Math.min(...vals);
  let hi = Math.max(...vals);
  const pad = Math.max((hi - lo) * 0.06, 1);
  lo -= pad;
  hi += pad;
  const xmax = Math.max(1, model.maxRound);
  const x = (r: number) => m.l + (r / xmax) * iw;
  const y = (c: number) => m.t + (1 - (c - lo) / (hi - lo)) * ih;
  const line = (pts: { r: number; c: number | null }[]) =>
    pts
      .filter((p) => isNum(p.c))
      .map((p, i) => `${i ? "L" : "M"}${x(p.r).toFixed(1)},${y(p.c!).toFixed(1)}`)
      .join(" ");
  const area = (t: Thread) => {
    // the gap between their standing offer and our ask, shaded: it closes as they converge
    const s = t.standing.filter((p) => isNum(p.c));
    const a = t.asks.filter((p) => isNum(p.c));
    if (s.length < 2 || !a.length) return "";
    const top = s.map((p) => `${x(p.round)},${y(p.c!)}`);
    const bottom = [...a].reverse().map((p) => `${x(p.round)},${y(p.c!)}`);
    return `M${top.join(" L")} L${bottom.join(" L")} Z`;
  };

  const ticks = 4;
  const refs: { c: number | null; label: string; cls: string; dash?: string }[] = [
    { c: model.cOpen, label: "Their opening", cls: "#6E6E73", dash: "4 4" },
    { c: model.cAlt, label: "Walk-away alt.", cls: "#A1A1A6", dash: "2 4" },
    { c: model.cBest, label: "Best possible", cls: "#0B0B0C", dash: "6 3" },
  ];
  // label rows on the right edge, pushed apart so close lines (deal next to best possible) never overlap
  const refLabelY = new Map<string, number>();
  let lastY = -Infinity;
  refs
    .filter((r) => isNum(r.c) && r.c >= lo && r.c <= hi)
    .map((r) => ({ label: r.label, y: y(r.c!) + 4 }))
    .sort((a, b) => a.y - b.y)
    .forEach((r) => {
      const yy = Math.max(r.y, lastY + 14);
      refLabelY.set(r.label, yy);
      lastY = yy;
    });
  // the deal as priced on the supplier's sheet, so it sits on that supplier's line
  const dealSid = model.current.sid;
  const dealC = model.result?.deal ? (model.threads.find((t) => t.sid === dealSid)?.current?.c ?? model.current.c) : null;
  const nodeY = height - 30;

  return (
    <div ref={ref} className="relative w-full select-none">
      <svg width={w} height={height}>
        {Array.from({ length: ticks + 1 }, (_, i) => lo + ((hi - lo) * i) / ticks).map((v, i) => (
          <g key={i}>
            <line x1={m.l} x2={m.l + iw} y1={y(v)} y2={y(v)} stroke="#F1F1EE" />
            <text x={m.l - 10} y={y(v) + 4} textAnchor="end" className="fill-ink-4 font-mono text-[10px]">
              {eurShort(v)}
            </text>
          </g>
        ))}
        {selected !== null && (
          <rect x={x(selected) - 14} y={m.t - 6} width={28} height={ih + 12} rx={8} fill="#FFF1EB" opacity={0.9} />
        )}
        {refs.map(
          (r) =>
            isNum(r.c) &&
            r.c >= lo &&
            r.c <= hi && (
              <g key={r.label}>
                <line x1={m.l} x2={m.l + iw} y1={y(r.c)} y2={y(r.c)} stroke={r.cls} strokeDasharray={r.dash} strokeWidth={1.2} />
                <text x={m.l + iw + 18} y={refLabelY.get(r.label) ?? y(r.c) + 4} style={{ fill: r.cls }} className="text-[11px] font-medium">
                  {r.label}
                </text>
              </g>
            ),
        )}
        {model.threads.map((t) => {
          const dim = t.sid !== focus.sid;
          return (
            <g key={t.sid} opacity={dim ? 0.22 : 1} style={{ transition: "opacity .3s" }}>
              {!dim && <path d={area(t)} fill={t.color} opacity={0.07} />}
              <path d={line(t.asks.map((a) => ({ r: a.round, c: a.c })))} fill="none" stroke={t.color} strokeWidth={2} strokeDasharray="5 4" opacity={0.7} />
              <path d={line(t.standing.map((s) => ({ r: s.round, c: s.c })))} fill="none" stroke={t.color} strokeWidth={3} strokeLinejoin="round" strokeLinecap="round" />
              {t.standing.map(
                (s) =>
                  isNum(s.c) && (
                    <circle key={`s${s.round}`} cx={x(s.round)} cy={y(s.c)} r={s.status === "final_offer" ? 6 : 4} fill="white" stroke={t.color} strokeWidth={2.5} />
                  ),
              )}
              {t.asks.map((a) => isNum(a.c) && <circle key={`a${a.round}`} cx={x(a.round)} cy={y(a.c)} r={3.2} fill={t.color} opacity={0.75} />)}
            </g>
          );
        })}
        {isNum(dealC) && (
          <g>
            {(() => {
              const t = model.threads.find((tt) => tt.sid === dealSid);
              const r = t?.current?.round ?? model.maxRound;
              return (
                <>
                  <circle cx={x(r)} cy={y(dealC)} r={11} fill="#FF5A1F" opacity={0.18} className="animate-pulsedot" />
                  <circle cx={x(r)} cy={y(dealC)} r={6.5} fill="#FF5A1F" stroke="white" strokeWidth={2} />
                  <text x={x(r) - 12} y={y(dealC) - 14} textAnchor="end" className="fill-accent-deep text-[11px] font-semibold">
                    Deal {eurShort(isNum(model.result?.c_deal) ? model.result!.c_deal! : dealC)}
                  </text>
                </>
              );
            })()}
          </g>
        )}
        {/* round nodes: the agent's move each round */}
        <line x1={m.l} x2={m.l + iw} y1={nodeY} y2={nodeY} stroke="#E7E7E4" strokeWidth={2} />
        <g>
          <circle cx={x(0)} cy={nodeY} r={5} fill="#A1A1A6" />
          <text x={x(0)} y={nodeY + 24} textAnchor="middle" className="fill-ink-4 text-[10px]">
            quote
          </text>
        </g>
        {stories.map((s) => {
          const on = selected === s.round;
          const hot = hover === s.round;
          const icon = MOVE_ICON[s.move];
          return (
            <g
              key={s.round}
              onClick={() => onSelect(s.round)}
              onMouseEnter={() => setHover(s.round)}
              onMouseLeave={() => setHover(null)}
              className="cursor-pointer"
            >
              <line x1={x(s.round)} x2={x(s.round)} y1={m.t} y2={nodeY - 15} stroke={on || hot ? "#FF5A1F" : "transparent"} strokeWidth={1} strokeDasharray="2 3" />
              <circle cx={x(s.round)} cy={nodeY} r={on ? 15 : 13} fill={on ? "#0B0B0C" : "white"} stroke={on ? "#0B0B0C" : hot ? "#FF5A1F" : "#0B0B0C"} strokeWidth={1.5} />
              <text x={x(s.round)} y={nodeY + 4.5} textAnchor="middle" className={on ? "fill-white text-[13px]" : "fill-ink text-[13px]"}>
                {icon}
              </text>
              <text x={x(s.round)} y={nodeY + 30} textAnchor="middle" className={on ? "fill-ink text-[10.5px] font-semibold" : "fill-ink-3 text-[10.5px]"}>
                R{s.round} · {s.moveLabel}
              </text>
              {s.claims.some((c) => c.result === "verified") && <circle cx={x(s.round) + 11} cy={nodeY - 11} r={4} fill="#FF5A1F" stroke="white" strokeWidth={1.5} />}
            </g>
          );
        })}
      </svg>
      {hover !== null &&
        (() => {
          const s = stories.find((z) => z.round === hover);
          if (!s) return null;
          return (
            <div
              className="pointer-events-none absolute z-10 rounded-lg border border-line bg-white px-3 py-2 text-[0.72rem] shadow-card"
              style={{ left: Math.min(w - 220, x(hover) + 14), top: m.t }}
            >
              <div className="font-semibold text-ink">
                Round {s.round} · {s.moveLabel}
              </div>
              <div className="mt-0.5 text-ink-3">
                Our ask <span className="font-mono text-ink">{eur(s.ourBest)}</span>
              </div>
              <div className="text-ink-3">
                Their offer <span className="font-mono text-ink">{eur(s.supplierAfter)}</span>
              </div>
            </div>
          );
        })()}
      <div className="mt-1 flex flex-wrap items-center gap-4 pl-16 text-[0.72rem] text-ink-3">
        <span className="inline-flex items-center gap-1.5">
          <svg width="22" height="6"><line x1="0" x2="22" y1="3" y2="3" stroke="#FF5A1F" strokeWidth="3" /></svg>
          Supplier's offer
        </span>
        <span className="inline-flex items-center gap-1.5">
          <svg width="22" height="6"><line x1="0" x2="22" y1="3" y2="3" stroke="#FF5A1F" strokeWidth="2" strokeDasharray="5 4" /></svg>
          Our ask
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-accent" /> verified argument
        </span>
        <span>Total cost C per year · lower is better</span>
      </div>
    </div>
  );
}
