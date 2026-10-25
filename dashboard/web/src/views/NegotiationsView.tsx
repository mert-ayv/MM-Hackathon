import { useMemo, useState } from "react";
import { useCase, useRuns } from "../lib/api";
import { buildModel } from "../lib/model";
import type { CaseSummary, RunMeta } from "../lib/types";
import { eur, eurShort } from "../lib/format";
import { href } from "../lib/router";
import { Card, cx, Empty, Label, Pill, Segmented, StatusBadge } from "../components/ui";
import { ScoreRing, Sparkline } from "../components/story/visuals";
import { withLabels } from "./NegotiationView";

const isNum = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);

// The showcase negotiations for the pitch, in this order (used when the run is present)
const PINS: { run: string; case: string }[] = [
  { run: "20261024-165810-go49mor-v15", case: "case:P01" }, // Brandlhuber, the demo video's case
  { run: "20261025-025817-router-x-practice", case: "case:P11" },
  { run: "20261024-171018-go49mor-v16", case: "case:D02" },
  { run: "20261025-011015-annika-kc-practice", case: "case:P10" },
];

const SKIP = /naive|sim|fixture|base$/i;

interface Pick {
  run: RunMeta;
  c: CaseSummary;
  pinned: boolean;
}

export function NegotiationsView({ version }: { version: string | null }) {
  const { data, error } = useRuns(version);
  const [type, setType] = useState("all");

  const picks = useMemo(() => {
    if (!data) return [] as Pick[];
    const best = new Map<string, Pick>();
    for (const run of data.runs) {
      if (SKIP.test(run.run_id) || /naive/i.test(run.agent ?? "")) continue;
      for (const c of run.case_summaries) {
        if (c.status !== "ended" || !isNum(c.score)) continue;
        const key = c.real_case_id ?? c.case_id.replace(/~\d+$/, "");
        const old = best.get(key);
        if (!old || c.score! > old.c.score! + 1e-6 || (Math.abs(c.score! - old.c.score!) < 1e-6 && (c.last_ts ?? "") > (old.c.last_ts ?? "")))
          best.set(key, { run, c, pinned: false });
      }
    }
    for (const p of PINS) {
      const run = data.runs.find((r) => r.run_id === p.run);
      const c = run?.case_summaries.find((x) => x.case_id === p.case);
      if (run && c) best.set(p.case, { run, c, pinned: true });
    }
    const all = [...best.values()];
    const order = (p: Pick) => {
      const i = PINS.findIndex((x) => x.run === p.run.run_id && x.case === p.c.case_id);
      return i < 0 ? 100 : i;
    };
    return all.sort((a, b) => order(a) - order(b) || (a.c.real_case_id ?? a.c.case_id).localeCompare(b.c.real_case_id ?? b.c.case_id));
  }, [data]);

  const types = useMemo(() => ["all", ...new Set(picks.map((p) => p.c.type ?? "other"))], [picks]);
  const shown = picks.filter((p) => type === "all" || (p.c.type ?? "other") === type);
  const pinned = shown.filter((p) => p.pinned);
  const rest = shown.filter((p) => !p.pinned);

  const total = picks.reduce((s, p) => s + (p.c.deal && isNum(p.c.saved) ? p.c.saved : 0), 0);
  const deals = picks.filter((p) => p.c.deal).length;
  const mean = picks.length ? picks.reduce((s, p) => s + (p.c.score ?? 0), 0) / picks.length : null;

  if (error) return <Empty>Could not load runs: {error}</Empty>;
  if (!data) return <div className="py-24 text-center text-sm text-ink-3">Loading negotiations…</div>;

  return (
    <div className="flex flex-col gap-8 pb-32">
      <div className="flex flex-wrap items-end justify-between gap-6">
        <div>
          <Label>Negotiations</Label>
          <h1 className="mt-1 text-[1.9rem] font-semibold tracking-tight text-ink">Every deal, at a glance</h1>
          <div className="mt-1 text-[0.9rem] text-ink-3">The agent's best negotiation per case. Open one to see why it decided what it did.</div>
        </div>
        <div className="flex gap-8">
          <Kpi label="Saved vs openings" value={eurShort(total)} accent />
          <Kpi label="Deals" value={`${deals}/${picks.length}`} />
          <Kpi label="Mean score" value={isNum(mean) ? mean.toFixed(2) : "–"} />
        </div>
      </div>

      {types.length > 2 && (
        <Segmented value={type} onChange={setType} options={types.map((t) => ({ value: t, label: t === "all" ? "All" : t.replace(/_/g, " ") }))} />
      )}

      {pinned.length > 0 && (
        <section>
          <Label className="mb-3">Showcase</Label>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {pinned.map((p) => (
              <NegCard key={`${p.run.run_id}/${p.c.case_id}`} p={p} big />
            ))}
          </div>
        </section>
      )}
      {rest.length > 0 && (
        <section>
          <Label className="mb-3">All cases</Label>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {rest.map((p) => (
              <NegCard key={`${p.run.run_id}/${p.c.case_id}`} p={p} />
            ))}
          </div>
        </section>
      )}
      {!picks.length && <Empty>No finished negotiations yet.</Empty>}
    </div>
  );
}

function Kpi({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="text-right">
      <div className={cx("font-mono text-[1.6rem] font-semibold tabular-nums tracking-tight", accent ? "text-accent" : "text-ink")}>{value}</div>
      <div className="text-[0.7rem] uppercase tracking-[0.12em] text-ink-3">{label}</div>
    </div>
  );
}

function NegCard({ p, big }: { p: Pick; big?: boolean }) {
  const { data } = useCase(p.run.run_id, p.c.case_id, null);
  const model = useMemo(() => (data ? withLabels(buildModel(data.events)) : null), [data]);
  const t = model?.threads.find((x) => x.sid === model.result?.supplier_id) ?? model?.threads[0];
  const cid = (p.c.real_case_id ?? p.c.case_id).replace(/^case:/, "").replace(/~\d+$/, "");
  const supplier = model ? (model.threads.length > 1 ? `${t?.short ?? ""} + ${model.threads.length - 1} more` : t?.name) : p.c.supplier_name;

  return (
    <a href={href({ name: "negotiation", runId: p.run.run_id, caseId: p.c.case_id })} className="group block">
      <Card className={cx("h-full p-5 transition-all group-hover:-translate-y-0.5 group-hover:border-ink", big && "border-ink/15")}>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-[0.7rem] text-ink-4">{cid}</span>
              {p.c.type && <Pill className="capitalize">{p.c.type.replace(/_/g, " ")}</Pill>}
            </div>
            <div className="mt-2 line-clamp-2 text-[0.95rem] font-semibold leading-snug tracking-tight text-ink">{supplier ?? p.c.title}</div>
          </div>
          <ScoreRing score={p.c.score} size={58} stroke={5} />
        </div>
        <div className="mt-4 flex items-end justify-between gap-3">
          <div>
            <div className={cx("font-mono text-[1.25rem] font-semibold tabular-nums", p.c.deal ? "text-accent" : "text-ink-3")}>
              {p.c.deal && isNum(p.c.saved) ? eur(p.c.saved) : "–"}
            </div>
            <div className="text-[0.68rem] text-ink-3">{p.c.deal ? "saved vs opening" : (p.c.end_reason ?? "no deal")}</div>
          </div>
          {t && <Sparkline supplier={t.standing.map((s) => s.c)} ours={t.asks.map((a) => a.c)} best={model?.cBest} w={120} h={38} />}
        </div>
        <div className="mt-4 flex items-center justify-between border-t border-line pt-3 text-[0.7rem] text-ink-3">
          <StatusBadge status={p.c.deal ? "agreed" : "walked_away"} />
          <span>
            {p.c.rounds} rounds · {p.run.variant ?? p.run.agent}
          </span>
        </div>
      </Card>
    </a>
  );
}
