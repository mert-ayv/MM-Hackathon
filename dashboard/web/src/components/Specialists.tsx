import type { RoundData } from "../lib/model";
import { eur, eurDelta, duration } from "../lib/format";
import { SPECIALIST_ORDER, type Priced } from "../lib/types";
import { cx, Empty, Label, Mono } from "./ui";

const ICON: Record<string, string> = {
  price: "€",
  cash: "◷",
  logistics: "⇢",
  quality: "◆",
  volume: "▤",
  index: "↗",
  relationship: "♡",
};

export function SpecialistsPanel({ rd, big = false }: { rd?: RoundData; big?: boolean }) {
  const outs = rd?.specialists?.outputs;
  if (!outs) return <Empty>No specialists output for this round{rd ? "" : " – select a round"}. Baseline agents don't log one.</Empty>;
  const names = [...SPECIALIST_ORDER.filter((n) => n in outs), ...Object.keys(outs).filter((n) => !SPECIALIST_ORDER.includes(n))];
  const max = Math.max(1, ...names.flatMap((n) => [Math.abs(outs[n]?.value_for_us_eur ?? 0), Math.abs(outs[n]?.value_for_supplier_eur ?? 0)]));
  return (
    <div className="divide-y divide-line-2">
      <div className={cx("grid grid-cols-[7rem_1fr_1fr] gap-3 pb-2 text-ink-3", big ? "text-xs" : "text-[0.66rem]")}>
        <span className="uppercase tracking-[0.12em]">Specialist</span>
        <span className="uppercase tracking-[0.12em]">Worth to us</span>
        <span className="uppercase tracking-[0.12em]">Worth to supplier</span>
      </div>
      {names.map((n) => {
        const o = outs[n] ?? {};
        const us = o.value_for_us_eur ?? 0;
        const them = o.value_for_supplier_eur ?? 0;
        const idle = !o.proposal && !o.claim && Math.abs(us) < 0.5;
        return (
          <div key={n} className={cx("py-2.5", idle && "opacity-55")}>
            <div className="grid grid-cols-[7rem_1fr_1fr] items-center gap-3">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 items-center justify-center rounded-md bg-paper-3 text-xs text-ink-2">{ICON[n] ?? "•"}</span>
                <span className={cx("font-medium capitalize", big ? "text-sm" : "text-[0.8rem]")}>{n}</span>
              </div>
              <ValueBar v={us} max={max} accent />
              <ValueBar v={them} max={max} />
            </div>
            {(o.proposal || o.claim || o.note) && (
              <div className={cx("mt-1.5 pl-9 leading-snug text-ink-2", big ? "text-sm" : "text-[0.75rem]")}>
                {o.proposal && <Mono className="mr-2 rounded bg-paper-3 px-1.5 py-0.5 text-[0.7rem] text-ink">{o.proposal}</Mono>}
                {o.claim && <span className="text-ink">“{o.claim}” </span>}
                {o.note && <span className="text-ink-3">{o.note}</span>}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function ValueBar({ v, max, accent }: { v: number; max: number; accent?: boolean }) {
  const w = (Math.abs(v) / max) * 50;
  return (
    <div className="flex items-center gap-2">
      <div className="relative h-2 flex-1 rounded-full bg-paper-3">
        <div className="absolute inset-y-[-2px] left-1/2 w-px bg-line" />
        {Math.abs(v) >= 0.5 && (
          <div
            className={cx("absolute inset-y-0 rounded-full transition-all duration-500", v >= 0 ? (accent ? "bg-accent" : "bg-ink-2") : "bg-ink-4")}
            style={v >= 0 ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }}
          />
        )}
      </div>
      <Mono className={cx("w-[4.6rem] text-right text-[0.72rem]", Math.abs(v) < 0.5 ? "text-ink-4" : v > 0 ? "text-ink" : "text-ink-3")}>
        {Math.abs(v) < 0.5 ? "–" : eurDelta(v)}
      </Mono>
    </div>
  );
}

export function PlanPanel({
  rd,
  onPick,
  picked,
  big = false,
}: {
  rd?: RoundData;
  onPick?: (p: Priced, label: string) => void;
  picked?: Priced | null;
  big?: boolean;
}) {
  const plan = rd?.plan;
  const dec = rd?.decision;
  if (!plan && !dec) return <Empty>No plan or decision logged for this round.</Empty>;
  return (
    <div className="space-y-3">
      {plan && (
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-[0.75rem] text-ink-3">
          <span>
            Target <Mono className="text-ink">{eur(plan.target?.c)}</Mono>
          </span>
          <span>
            Walk away above <Mono className="text-ink">{eur(plan.walk_away_c, "none")}</Mono>
          </span>
          <span>{plan.candidates?.length ?? 0} candidates</span>
        </div>
      )}
      {plan?.candidates?.map((cand) => {
        const chosen = dec?.candidate_id === cand.id;
        return (
          <div key={cand.id} className={cx("rounded-lg border p-3 transition-colors", chosen ? "border-accent bg-accent-soft/50" : "border-line")}>
            <div className="flex items-start justify-between gap-3">
              <div className={cx("font-medium", big ? "text-base" : "text-sm")}>
                <Mono className="mr-2 text-[0.7rem] text-ink-3">{cand.id}</Mono>
                {cand.label}
              </div>
              {chosen && <span className="rounded-full bg-accent px-2 py-0.5 text-[0.65rem] font-semibold uppercase tracking-wide text-white">Chosen</span>}
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {cand.sheets?.map((s, i) => (
                <button
                  key={i}
                  onClick={() => onPick?.(s, `${cand.id} · sheet ${i + 1}`)}
                  className={cx(
                    "rounded-md border px-2 py-1 font-mono text-[0.72rem] tabular-nums transition-colors hover:border-ink",
                    picked === s ? "border-ink bg-ink text-white" : "border-line bg-white",
                  )}
                  title="Show this sheet's C by term"
                >
                  {eur(s.c)}
                </button>
              ))}
            </div>
            {cand.claims && cand.claims.length > 0 && (
              <ul className="mt-2 space-y-0.5 text-[0.75rem] text-ink-2">
                {cand.claims.map((c, i) => (
                  <li key={i} className="flex gap-1.5">
                    <Mono className="text-ink-4">#{i}</Mono>
                    <span>{c.text}</span>
                  </li>
                ))}
              </ul>
            )}
            {cand.rationale && <p className="mt-2 text-[0.75rem] leading-snug text-ink-3">{cand.rationale}</p>}
          </div>
        );
      })}
      {dec && (
        <div className="rounded-lg bg-ink p-3.5 text-white">
          <div className="flex items-center justify-between">
            <Label className="!text-white/60">Decision · {dec.kind.replace("_", " ")}</Label>
            {typeof dec.decided_in_s === "number" && <Mono className="text-[0.7rem] text-white/50">{duration(dec.decided_in_s)}</Mono>}
          </div>
          <p className={cx("mt-1.5 leading-snug", big ? "text-base" : "text-[0.82rem]")}>{dec.reason || "–"}</p>
        </div>
      )}
    </div>
  );
}
