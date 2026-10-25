import { useEffect, useMemo, useState } from "react";
import { useRuns } from "../lib/api";
import type { CaseResponse } from "../lib/api";
import { buildModel } from "../lib/model";
import type { CaseModel } from "../lib/model";
import type { CaseSummary, RunMeta } from "../lib/types";
import { dateTime, eur, eurShort } from "../lib/format";
import { href } from "../lib/router";
import { Card, cx, Empty, Label, Pill, Segmented, StatusBadge } from "../components/ui";
import { IconChip, Sparkline } from "../components/story/visuals";
import { withLabels } from "./NegotiationView";
import { outcome, plainName, reviewReasons } from "../lib/story";
import type { ReviewReason } from "../lib/story";

const isNum = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);

// Featured first (the pitch's negotiations), when their run is present
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

type Segment = "all" | "review" | "deal" | "walked";

interface Loaded {
  model: CaseModel;
  reasons: ReviewReason[];
}

/** Loads and models every listed negotiation once (the inbox needs the review reasons up front). */
function useModels(picks: Pick[]): Map<string, Loaded> {
  const [out, setOut] = useState<Map<string, Loaded>>(new Map());
  const keys = picks.map((p) => `${p.run.run_id}/${p.c.case_id}`).join("|");
  useEffect(() => {
    let alive = true;
    Promise.all(
      picks.map(async (p) => {
        const k = `${p.run.run_id}/${p.c.case_id}`;
        try {
          const r = await fetch(`/api/runs/${encodeURIComponent(p.run.run_id)}/cases/${encodeURIComponent(p.c.case_id)}`);
          const d = (await r.json()) as CaseResponse;
          const model = withLabels(buildModel(d.events));
          return [k, { model, reasons: reviewReasons(model) }] as const;
        } catch {
          return null;
        }
      }),
    ).then((rows) => alive && setOut(new Map(rows.filter((r): r is NonNullable<typeof r> => !!r))));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keys]);
  return out;
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
    // the latest negotiation per case that ended without a deal: a real inbox shows those too
    const lastNoDeal = new Map<string, Pick>();
    for (const run of data.runs) {
      if (SKIP.test(run.run_id) || /naive/i.test(run.agent ?? "")) continue;
      for (const c of run.case_summaries) {
        if (c.status !== "ended" || c.deal !== false) continue;
        const key = c.real_case_id ?? c.case_id.replace(/~\d+$/, "");
        const old = lastNoDeal.get(key);
        if (!old || (c.last_ts ?? "") > (old.c.last_ts ?? "")) lastNoDeal.set(key, { run, c, pinned: false });
      }
    }
    for (const [k, p] of lastNoDeal) best.set(`${k}#no-deal`, p);
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
    // featured first, then by € saved, then most recent
    return all.sort((a, b) => order(a) - order(b) || (b.c.saved ?? -Infinity) - (a.c.saved ?? -Infinity) || (b.c.last_ts ?? "").localeCompare(a.c.last_ts ?? ""));
  }, [data]);

  const models = useModels(picks);
  const [seg, setSeg] = useState<Segment>("all");
  const [q, setQ] = useState("");
  const keyOf = (p: Pick) => `${p.run.run_id}/${p.c.case_id}`;
  const segOf = (p: Pick): Segment[] => {
    const l = models.get(keyOf(p));
    const s: Segment[] = ["all"];
    if (l?.reasons.length) s.push("review");
    if (p.c.deal && !l?.reasons.length) s.push("deal");
    if (!p.c.deal) s.push("walked");
    return s;
  };
  const types = useMemo(() => ["all", ...new Set(picks.map((p) => p.c.type ?? "other"))], [picks]);
  const ql = q.trim().toLowerCase();
  const shown = picks
    .filter((p) => type === "all" || (p.c.type ?? "other") === type)
    .filter((p) => segOf(p).includes(seg))
    .filter((p) => {
      if (!ql) return true;
      const m = models.get(keyOf(p))?.model;
      const names = [p.c.supplier_name ?? "", p.c.title ?? "", ...(m?.threads.map((t) => t.name) ?? [])].join(" ").toLowerCase();
      return names.includes(ql);
    });
  const count = (sg: Segment) => picks.filter((p) => segOf(p).includes(sg)).length;

  const total = picks.reduce((s, p) => s + (p.c.deal && isNum(p.c.saved) ? p.c.saved : 0), 0);
  const deals = picks.filter((p) => p.c.deal).length;
  const vsAlt = picks.reduce((s, p) => {
    const m = models.get(keyOf(p))?.model;
    const v = m ? outcome(m).vsAlternative : null;
    return s + (p.c.deal && isNum(v) && v > 0 ? v : 0);
  }, 0);

  if (error) return <Empty>Could not load runs: {error}</Empty>;
  if (!data) return <div className="py-24 text-center text-sm text-ink-3">Loading negotiations…</div>;

  const SEGS: { value: Segment; label: string }[] = [
    { value: "all", label: "All" },
    { value: "review", label: "Needs review" },
    { value: "deal", label: "Closed · deal" },
    { value: "walked", label: "Walked away" },
  ];

  return (
    <div className="flex flex-col gap-7 pb-32">
      <div className="flex flex-wrap items-end justify-between gap-6">
        <div>
          <Label>Negotiations</Label>
          <h1 className="mt-1 text-[1.9rem] font-semibold tracking-tight text-ink">Every deal, at a glance</h1>
          <div className="mt-1 text-[0.9rem] text-ink-3">What the agent negotiated, and what needs your eyes. Open one to see why it decided what it did.</div>
        </div>
        <div className="flex gap-8">
          <Kpi label="Saved vs openings" value={eurShort(total)} accent />
          <Kpi label="Better than walking away" value={models.size ? eurShort(vsAlt) : "…"} />
          <Kpi label="Deals closed" value={`${deals}/${picks.length}`} />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-xl border border-line bg-paper-2 p-1">
          {SEGS.map((o) => (
            <button
              key={o.value}
              onClick={() => setSeg(o.value)}
              className={cx(
                "inline-flex items-center gap-2 rounded-lg px-3.5 py-1.5 text-[0.82rem] font-medium transition-colors",
                seg === o.value ? "bg-ink text-white shadow-sm" : "text-ink-2 hover:text-ink",
              )}
            >
              {o.value === "review" && <span className={cx("h-1.5 w-1.5 rounded-full", seg === o.value ? "bg-accent" : "bg-accent")} />}
              {o.label}
              <span className={cx("font-mono text-[0.72rem]", seg === o.value ? "text-white/60" : "text-ink-4")}>{models.size || o.value === "all" ? count(o.value) : "·"}</span>
            </button>
          ))}
        </div>
        {types.length > 2 && (
          <Segmented value={type} onChange={setType} options={types.map((t) => ({ value: t, label: t === "all" ? "All categories" : t.replace(/_/g, " ") }))} />
        )}
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search supplier…"
          className="ml-auto w-56 rounded-lg border border-line bg-white px-3 py-1.5 text-[0.82rem] outline-none placeholder:text-ink-4 focus:border-ink"
        />
      </div>

      {shown.length > 0 ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {shown.map((p) => (
            <NegCard key={keyOf(p)} p={p} loaded={models.get(keyOf(p))} />
          ))}
        </div>
      ) : (
        <Empty>{picks.length ? "Nothing here." : "No finished negotiations yet."}</Empty>
      )}
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

function NegCard({ p, loaded }: { p: Pick; loaded?: Loaded }) {
  const model = loaded?.model;
  const t = model?.threads.find((x) => x.sid === model.result?.supplier_id) ?? model?.threads[0];
  const cid = (p.c.real_case_id ?? p.c.case_id).replace(/^case:/, "").replace(/~\d+$/, "");
  const supplier = model ? (model.threads.length > 1 ? `${t?.short ?? ""} + ${model.threads.length - 1} more` : t && plainName(t.name)) : p.c.supplier_name;
  const o = model ? outcome(model) : null;
  const reasons = loaded?.reasons ?? [];

  return (
    <a href={href({ name: "negotiation", runId: p.run.run_id, caseId: p.c.case_id })} className="group block">
      <Card className={cx("flex h-full flex-col p-5 transition-all group-hover:-translate-y-0.5 group-hover:border-ink", reasons.length > 0 && "border-accent/40")}>
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-[0.7rem] text-ink-4">{cid}</span>
          {p.c.type && <Pill className="capitalize">{p.c.type.replace(/_/g, " ")}</Pill>}
          <span className="ml-auto">
            <StatusBadge status={p.c.deal ? "agreed" : "walked_away"} />
          </span>
        </div>
        <div className="mt-2 line-clamp-2 text-[0.95rem] font-semibold leading-snug tracking-tight text-ink">{supplier ?? p.c.title}</div>
        <div className="mt-4 flex items-end justify-between gap-3">
          <div>
            <div className={cx("font-mono text-[1.25rem] font-semibold tabular-nums", p.c.deal ? "text-accent" : "text-ink-3")}>
              {p.c.deal && isNum(p.c.saved) ? eur(p.c.saved) : "–"}
            </div>
            <div className="text-[0.68rem] text-ink-3">
              {p.c.deal ? (
                <>
                  saved vs opening
                  {o && isNum(o.increaseAvertedPct) ? ` · ${Math.round(o.increaseAvertedPct * 100)} % of increase averted` : o && isNum(o.savedPct) ? ` · −${(o.savedPct * 100).toFixed(1)} %` : ""}
                </>
              ) : (
                (p.c.end_reason ?? "no deal").replace(/_/g, " ")
              )}
            </div>
          </div>
          {t && <Sparkline supplier={t.standing.map((s) => s.c)} ours={t.asks.map((a) => a.c)} w={110} h={38} />}
        </div>
        <div className="mt-auto flex flex-wrap items-center gap-1.5 border-t border-line pt-3 text-[0.7rem] text-ink-3" style={{ marginTop: "1rem" }}>
          {reasons.length > 0 ? (
            reasons.slice(0, 2).map((r) => <IconChip key={r.label} icon={r.icon} label={r.label} tone="accent" />)
          ) : (
            <span className="inline-flex items-center gap-1.5 text-ink-3">
              <span className="h-1.5 w-1.5 rounded-full bg-ink" /> {model ? "Closed cleanly" : "…"}
            </span>
          )}
          <span className="ml-auto whitespace-nowrap">
            {p.c.last_ts ? `${dateTime(p.c.last_ts)} · ` : ""}
            {p.c.rounds} rounds
          </span>
        </div>
      </Card>
    </a>
  );
}
