import { useState } from "react";
import { eur, eurDelta, humanize, termLabel, termValue } from "../lib/format";
import { COST_KEYS, type Priced } from "../lib/types";
import { cx, Empty, Mono, Segmented } from "./ui";

type Mode = "delta" | "absolute";

const LABEL: Record<string, string> = {
  price: "Price",
  uncovered_need: "Uncovered need",
  fallback_risk: "Fallback risk",
  payment_terms: "Payment terms",
  freight: "Freight",
  late_delivery: "Late delivery",
  quality: "Quality",
  tooling: "Tooling",
  index_clause: "Index clause",
  index_risk: "Index risk",
  relationship: "Relationship",
};

export function Waterfall({
  sheet,
  base,
  baseLabel = "Opening quote",
  sheetLabel = "This sheet",
  big = false,
  showTerms = true,
  defaultMode = "delta",
}: {
  sheet?: Priced | null;
  base?: Priced | null;
  baseLabel?: string;
  sheetLabel?: string;
  big?: boolean;
  showTerms?: boolean;
  defaultMode?: Mode;
}) {
  const [mode, setMode] = useState<Mode>(defaultMode);
  if (!sheet || !sheet.breakdown || sheet.c === null) return <Empty>Select a priced term sheet to see its C by term.</Empty>;
  const canDelta = !!base?.breakdown && base.c !== null;
  const m: Mode = canDelta ? mode : "absolute";
  const keys = [...COST_KEYS, ...Object.keys(sheet.breakdown).filter((k) => !(COST_KEYS as readonly string[]).includes(k))];

  return (
    <div>
      <div className="mb-4 flex items-center justify-between gap-3">
        {canDelta ? (
          <Segmented
            value={m}
            onChange={setMode}
            options={[
              { value: "delta", label: `Δ vs ${baseLabel.toLowerCase()}` },
              { value: "absolute", label: "C by term" },
            ]}
          />
        ) : (
          <span />
        )}
        <Mono className={cx("font-semibold", big ? "text-xl" : "text-sm")}>C {eur(sheet.c)}</Mono>
      </div>
      {m === "delta" ? (
        <DeltaBars sheet={sheet} base={base!} keys={keys} big={big} baseLabel={baseLabel} sheetLabel={sheetLabel} />
      ) : (
        <AbsBars sheet={sheet} keys={keys} big={big} />
      )}
      {showTerms && (
        <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 border-t border-line-2 pt-3 text-[0.72rem] text-ink-3">
          {Object.entries(sheet.terms).map(([k, v]) => (
            <span key={k}>
              {termLabel(k)} <Mono className="text-ink">{termValue(k, v)}</Mono>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function Row({ label, children, value, big, strong }: { label: string; children: React.ReactNode; value: React.ReactNode; big?: boolean; strong?: boolean }) {
  return (
    <div className={cx("grid items-center gap-3", big ? "grid-cols-[10rem_1fr_7.5rem] py-1.5" : "grid-cols-[7.5rem_1fr_6.2rem] py-1")}>
      <div className={cx("truncate", big ? "text-sm" : "text-[0.75rem]", strong ? "font-semibold text-ink" : "text-ink-2")}>{label}</div>
      <div className={cx("relative", big ? "h-5" : "h-3.5")}>{children}</div>
      <div className={cx("text-right font-mono tabular-nums", big ? "text-sm" : "text-[0.75rem]", strong ? "font-semibold" : "")}>{value}</div>
    </div>
  );
}

const bar = "absolute inset-y-0 rounded-[3px] transition-all duration-700 ease-out";

function DeltaBars({ sheet, base, keys, big, baseLabel, sheetLabel }: { sheet: Priced; base: Priced; keys: string[]; big: boolean; baseLabel: string; sheetLabel: string }) {
  const deltas = keys
    .map((k) => ({ k, d: (sheet.breakdown![k] ?? 0) - (base.breakdown![k] ?? 0) }))
    .filter((x) => Math.abs(x.d) >= 0.5);
  let run = base.c!;
  const steps = deltas.map((x) => {
    const from = run;
    run += x.d;
    return { ...x, from, to: run };
  });
  const values = [base.c!, sheet.c!, ...steps.map((s) => s.to)];
  const lo0 = Math.min(...values);
  const hi0 = Math.max(...values);
  const pad = Math.max((hi0 - lo0) * 0.25, 1);
  const lo = lo0 - pad;
  const hi = hi0 + pad * 0.15;
  const x = (v: number) => ((v - lo) / (hi - lo)) * 100;

  return (
    <div>
      <Row label={baseLabel} value={eur(base.c)} big={big} strong>
        <div className={cx(bar, "left-0 bg-ink")} style={{ width: `${x(base.c!)}%` }} />
        <Break />
      </Row>
      {steps.length === 0 && <div className="py-2 text-xs text-ink-3">Same C by every term.</div>}
      {steps.map((s) => (
        <Row key={s.k} label={LABEL[s.k] ?? humanize(s.k)} value={<span className={s.d < 0 ? "text-accent-deep" : "text-ink-2"}>{eurDelta(s.d)}</span>} big={big}>
          <div
            className={cx(bar, s.d < 0 ? "bg-accent" : "bg-ink-4")}
            style={{ left: `${x(Math.min(s.from, s.to))}%`, width: `${Math.max(0.4, Math.abs(x(s.to) - x(s.from)))}%` }}
            title={`${LABEL[s.k] ?? s.k}: ${eurDelta(s.d)}`}
          />
          <div className="absolute inset-y-[-3px] w-px bg-line" style={{ left: `${x(s.from)}%` }} />
        </Row>
      ))}
      <Row label={sheetLabel} value={eur(sheet.c)} big={big} strong>
        <div className={cx(bar, "left-0 bg-ink")} style={{ width: `${x(sheet.c!)}%` }} />
        <Break />
      </Row>
      <div className="mt-2 flex items-center gap-4 text-[0.68rem] text-ink-3">
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-3 rounded-sm bg-accent" />saves</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-3 rounded-sm bg-ink-4" />costs</span>
        <span className="ml-auto">axis starts at {eur(lo)}</span>
      </div>
    </div>
  );
}

/** Zig-zag break: the bar's axis does not start at 0 */
function Break() {
  return (
    <svg className="absolute left-3 top-1/2 -translate-y-1/2" width="8" height="18" viewBox="0 0 8 18" aria-hidden>
      <path d="M1 0 L7 4.5 L1 9 L7 13.5 L1 18" stroke="white" strokeWidth="2" fill="none" />
    </svg>
  );
}

function AbsBars({ sheet, keys, big }: { sheet: Priced; keys: string[]; big: boolean }) {
  const vals = keys.map((k) => ({ k, v: sheet.breakdown![k] ?? 0 }));
  const max = Math.max(...vals.map((v) => Math.abs(v.v)), 1);
  return (
    <div>
      {vals.map(({ k, v }) => (
        <Row key={k} label={LABEL[k] ?? humanize(k)} big={big} value={<span className={Math.abs(v) < 0.5 ? "text-ink-4" : ""}>{eur(v)}</span>}>
          <div className={cx(bar, k === "price" ? "bg-ink" : "bg-accent")} style={{ left: 0, width: `${Math.abs(v) < 0.5 ? 0 : Math.max(0.6, (Math.abs(v) / max) * 100)}%` }} />
          <div className="absolute inset-y-0 left-0 w-px bg-line" />
        </Row>
      ))}
      <Row label="Total C" value={eur(sheet.c)} big={big} strong>
        <div className="absolute inset-x-0 top-1/2 h-px bg-line" />
      </Row>
    </div>
  );
}
