import { eur, eurDelta } from "../lib/format";
import { cx, Label, Mono, useTween } from "./ui";

export interface GaugeMark {
  key: string;
  label: string;
  c: number | null;
  color: string;
  dimmed?: boolean;
}

const clip = (x: number) => Math.min(1, Math.max(0, x));

/** Lift a mark's label one row when it would collide with its neighbour's. */
function staggered(marks: GaugeMark[], pos: (c: number | null) => number | null) {
  const placed = marks
    .map((m) => ({ m, mp: pos(m.c) }))
    .filter((x): x is { m: GaugeMark; mp: number } => x.mp !== null)
    .sort((a, b) => a.mp - b.mp);
  let lastRow0 = -1;
  return placed.map((x) => {
    const row = lastRow0 >= 0 && x.mp - lastRow0 < 0.16 ? 1 : 0;
    if (row === 0) lastRow0 = x.mp;
    return { ...x, row };
  });
}

export function Gauge({
  cOpen,
  cBest,
  cAlt,
  current,
  marks = [],
  score,
  big = false,
}: {
  cOpen: number | null;
  cBest: number | null;
  cAlt: number | null;
  current: { c: number | null; label: string };
  marks?: GaugeMark[];
  score: number | null;
  big?: boolean;
}) {
  const range = cOpen !== null && cBest !== null && cOpen - cBest > 0.01 ? cOpen - cBest : null;
  const pos = (c: number | null) => (range && c !== null && cOpen !== null ? clip((cOpen - c) / range) : null);
  const p = pos(current.c);
  const tp = useTween(p, 900);
  const ts = useTween(score, 900);
  const tc = useTween(current.c, 900);
  const saved = current.c !== null && cOpen !== null ? cOpen - current.c : null;

  return (
    <div>
      <div className="flex items-end justify-between gap-6">
        <div>
          <Label>Score</Label>
          <div className={cx("font-mono font-semibold leading-none tracking-tight tabular-nums", big ? "mt-2 text-[4.2rem]" : "mt-1.5 text-[2.6rem]")}>
            {ts === null ? <span className="text-ink-4">–</span> : ts.toFixed(2)}
          </div>
        </div>
        <div className="text-right">
          <Label>{current.label}</Label>
          <Mono className={cx("mt-1.5 block font-semibold", big ? "text-3xl" : "text-xl")}>{eur(tc)}</Mono>
          <div className={cx("mt-1 font-mono tabular-nums", big ? "text-base" : "text-xs", saved && saved > 0 ? "text-accent-deep" : "text-ink-3")}>
            {saved !== null ? `${eurDelta(-saved)} vs opening` : " "}
          </div>
        </div>
      </div>

      <div className={cx("relative", marks.length ? (big ? "mt-14 mb-12" : "mt-12 mb-10") : big ? "mt-10 mb-12" : "mt-8 mb-10")}>
        {/* marks above the rail */}
        {staggered(marks, pos).map(({ m, mp, row }) => {
          return (
            <div
              key={m.key}
              className={cx("absolute -translate-x-1/2 transition-[left] duration-700 ease-out", m.dimmed && "opacity-40")}
              style={{ left: `${mp * 100}%`, top: row ? (big ? "-2.6rem" : "-2.3rem") : "-1.35rem" }}
              title={`${m.label}: ${eur(m.c)}`}
            >
              <div className={cx("whitespace-nowrap font-medium text-ink-2", big ? "text-xs" : "text-[0.62rem]")}>{m.label}</div>
              {row > 0 && <div className="mx-auto h-3 w-px bg-line" />}
              <div className="mx-auto mt-0.5 h-2 w-2 rounded-full ring-2 ring-white" style={{ background: m.color }} />
            </div>
          );
        })}
        {/* rail */}
        <div className={cx("relative overflow-hidden rounded-full bg-paper-3", big ? "h-4" : "h-2.5")}>
          <div className="absolute inset-y-0 left-0 rounded-full bg-accent" style={{ width: `${(tp ?? 0) * 100}%` }} />
          {/* quarter ticks */}
          {[0.25, 0.5, 0.75].map((q) => (
            <div key={q} className="absolute inset-y-0 w-px bg-white/70" style={{ left: `${q * 100}%` }} />
          ))}
        </div>
        {/* alternative */}
        {pos(cAlt) !== null && (
          <div className="absolute top-0 -translate-x-1/2" style={{ left: `${pos(cAlt)! * 100}%` }} title={`Alternative ${eur(cAlt)}`}>
            <div className={cx("w-0.5 bg-ink-2", big ? "h-4" : "h-2.5")} />
            <div className={cx("mt-1 whitespace-nowrap text-ink-3", big ? "text-xs" : "text-[0.62rem]")}>alt.</div>
          </div>
        )}
        {/* current marker */}
        {tp !== null && (
          <div className="absolute -translate-x-1/2" style={{ left: `${tp * 100}%`, top: big ? "-6px" : "-5px" }}>
            <div className={cx("rounded-full border-[3px] border-accent bg-white shadow", big ? "h-7 w-7" : "h-5 w-5")} />
          </div>
        )}
        {/* ends */}
        <div className={cx("absolute left-0 mt-2.5 text-left", big ? "text-sm" : "text-[0.7rem]")}>
          <div className="text-ink-3">C open</div>
          <Mono className="font-medium text-ink">{eur(cOpen)}</Mono>
        </div>
        <div className={cx("absolute right-0 mt-2.5 text-right", big ? "text-sm" : "text-[0.7rem]")}>
          <div className="text-ink-3">C best</div>
          <Mono className="font-medium text-ink">{cBest === null ? "at the end" : eur(cBest)}</Mono>
        </div>
      </div>
    </div>
  );
}
