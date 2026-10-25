import { useEffect, useMemo, useRef, useState } from "react";
import { useCase } from "../lib/api";
import { buildModel } from "../lib/model";
import type { CaseModel } from "../lib/model";
import { copilotSummary, keyMoves, leftOnTable, roundStories, threadLabels, verdict } from "../lib/story";
import type { RoundStory } from "../lib/story";
import { eur, eur2, eurShort, termLabel, termValue } from "../lib/format";
import { Card, cx, Empty, Label, Pill, StatusBadge } from "../components/ui";
import { CaptureBar, IconChip, ScoreRing } from "../components/story/visuals";
import { Convergence } from "../components/story/Convergence";
import { DecisionCard } from "../components/story/DecisionCard";

const isNum = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);

// window.__copilotCase is declared by the voice copilot (lib/voice.ts); written here for it
type CopilotWindow = { __copilotCase?: { runId: string; caseId: string; summary?: unknown } };
const cw = () => window as unknown as CopilotWindow;

export function NegotiationView({ runId, caseId, round, version }: { runId: string; caseId: string; round?: number; version: string | null }) {
  const { data, error } = useCase(runId, caseId, version);
  const model = useMemo(() => (data ? withLabels(buildModel(data.events)) : null), [data]);
  if (error) return <Empty>Could not load this negotiation: {error}</Empty>;
  if (!model) return <div className="py-24 text-center text-sm text-ink-3">Loading negotiation…</div>;
  return <Story key={`${runId}/${caseId}`} model={model} runId={runId} caseId={caseId} round={round} />;
}

function Story({ model, runId, caseId, round }: { model: CaseModel; runId: string; caseId: string; round?: number }) {
  const stories = useMemo(() => new Map(model.threads.map((t) => [t.sid, roundStories(t)])), [model]);
  const v = useMemo(() => verdict(model), [model]);
  const moves = useMemo(() => keyMoves(model, stories), [model, stories]);
  const left = useMemo(() => leftOnTable(model), [model]);

  const [sid, setSid] = useState(() => model.current.sid ?? moves[0]?.sid ?? model.threads[0]?.sid);
  const focus = model.threads.find((t) => t.sid === sid) ?? model.threads[0];
  const focusStories: RoundStory[] = (focus && stories.get(focus.sid)) || [];
  const [sel, setSel] = useState<number | null>(() => round ?? moves.find((m) => m.sid === sid)?.round ?? focusStories[0]?.round ?? null);
  const [flash, setFlash] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);
  const story = focusStories.find((s) => s.round === sel) ?? focusStories[0];

  useEffect(() => {
    if (round) setSel(round);
  }, [round]);

  // the voice copilot reads the case from here and can point at a round
  useEffect(() => {
    cw().__copilotCase = { runId, caseId, summary: copilotSummary(model, stories) };
    return () => {
      const w = cw();
      if (w.__copilotCase?.runId === runId && w.__copilotCase?.caseId === caseId) delete w.__copilotCase;
    };
  }, [model, stories, runId, caseId]);

  useEffect(() => {
    const on = (e: Event) => {
      const d = (e as CustomEvent<{ round?: number; supplier?: string }>).detail ?? {};
      if (d.supplier) {
        const q = d.supplier.toLowerCase();
        const t = model.threads.find((x) => x.sid.toLowerCase() === q || x.name.toLowerCase().includes(q) || x.short.toLowerCase().includes(q));
        if (t) setSid(t.sid);
      }
      if (isNum(d.round)) setSel(d.round);
      setFlash(true);
      setTimeout(() => cardRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }), 50);
      setTimeout(() => setFlash(false), 2200);
    };
    window.addEventListener("copilot:show", on);
    return () => window.removeEventListener("copilot:show", on);
  }, [model]);

  const pick = (s: string, r: number) => {
    setSid(s);
    setSel(r);
    setTimeout(() => cardRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }), 30);
  };

  const dealThread = model.threads.find((t) => t.sid === model.result?.supplier_id);
  const negotiable = (model.caseFile?.negotiable as string[] | undefined) ?? [];
  const termDiffs = negotiable
    .filter((k) => v.dealTerms && k in v.dealTerms)
    .map((k) => ({ k, from: v.openTerms?.[k], to: v.dealTerms?.[k] }))
    .filter((d) => d.to !== undefined);

  return (
    <div className="flex flex-col gap-6 pb-32">
      <a href="#/n" className="text-[0.8rem] text-ink-3 hover:text-ink">
        ← All negotiations
      </a>

      {/* verdict */}
      <Card className="animate-rise overflow-hidden motion-reduce:animate-none">
        <div className="grid items-center gap-8 p-7 lg:grid-cols-[auto_1fr_380px]">
          <ScoreRing score={v.score} size={148} />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              {model.type && <Pill className="capitalize">{model.type.replace(/_/g, " ")}</Pill>}
              <StatusBadge status={v.deal ? "agreed" : model.result ? "walked_away" : "open"} />
              <span className="text-[0.75rem] text-ink-3">
                {v.rounds} rounds · {model.threads.length} supplier{model.threads.length > 1 ? "s" : ""}
              </span>
            </div>
            <h1 className="mt-2 truncate text-[1.6rem] font-semibold tracking-tight text-ink">{model.title}</h1>
            {v.deal && isNum(v.saved) ? (
              <div className="mt-3 flex flex-wrap items-baseline gap-x-4 gap-y-1">
                <span className="text-[2.2rem] font-semibold tracking-tight text-accent">{eur(v.saved)}</span>
                <span className="text-[1rem] text-ink-2">saved vs {dealThread?.short ?? "their"} opening offer</span>
              </div>
            ) : (
              <div className="mt-3 text-[1.1rem] text-ink-2">{model.result ? `No deal · ${model.result.end_reason ?? ""}` : "In progress"}</div>
            )}
            {isNum(v.askPct) && isNum(v.dealPct) && v.askPct > 0 && (
              <div className="mt-1 text-[1rem] text-ink-2">
                <span className="font-semibold text-ink">{fmtPct(v.dealPct)}</span> instead of <span className="line-through decoration-accent/60">{fmtPct(v.askPct)}</span> on
                today's price
              </div>
            )}
            {termDiffs.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-2">
                {termDiffs.map((d) => {
                  const same = JSON.stringify(d.from) === JSON.stringify(d.to) || d.from === undefined;
                  return (
                    <span key={d.k} className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-paper-2 px-2.5 py-1 text-[0.78rem]">
                      <span className="text-ink-3">{termLabel(d.k)}</span>
                      {!same && <span className="text-ink-4 line-through">{termValue(d.k, d.from)}</span>}
                      {!same && <span className="text-accent">→</span>}
                      <span className="font-medium text-ink">{termValue(d.k, d.to)}</span>
                    </span>
                  );
                })}
              </div>
            )}
          </div>
          <div>
            <Label className="mb-3">Captured of what was reachable</Label>
            <CaptureBar cOpen={model.cOpen} cDeal={v.deal ? model.current.c : null} cBest={model.cBest} cAlt={model.cAlt} big />
          </div>
        </div>
      </Card>

      {/* key moves */}
      {moves.length > 0 && (
        <div>
          <Label className="mb-2.5">Moves that moved the price</Label>
          <div className="grid gap-3 md:grid-cols-3">
            {moves.map((m, i) => (
              <button
                key={`${m.sid}-${m.round}`}
                onClick={() => pick(m.sid, m.round)}
                className={cx(
                  "group flex items-center gap-4 rounded-2xl border bg-white p-4 text-left shadow-card transition-all hover:-translate-y-0.5 hover:border-ink",
                  sel === m.round && sid === m.sid ? "border-accent" : "border-line",
                )}
                style={{ animationDelay: `${i * 80}ms` }}
              >
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-lg text-accent-deep">{m.icon}</span>
                <div className="min-w-0">
                  <div className="font-mono text-[1.15rem] font-semibold tabular-nums text-ink">−{eurShort(m.saved)}</div>
                  <div className="truncate text-[0.78rem] text-ink-2">{m.driver}</div>
                  <div className="text-[0.68rem] text-ink-4">
                    Round {m.round}
                    {model.threads.length > 1 ? ` · ${m.supplier}` : ""}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* convergence */}
      <Card className="p-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-[0.95rem] font-semibold tracking-tight">How the gap closed</h3>
            <div className="text-[0.78rem] text-ink-3">Click a round to see why the agent did what it did</div>
          </div>
          {model.threads.length > 1 && (
            <div className="flex flex-wrap gap-1.5">
              {model.threads.map((t) => (
                <button
                  key={t.sid}
                  onClick={() => {
                    setSid(t.sid);
                    setSel((stories.get(t.sid) ?? [])[0]?.round ?? null);
                  }}
                  className={cx(
                    "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[0.78rem] font-medium transition-colors",
                    t.sid === focus?.sid ? "border-ink bg-ink text-white" : "border-line text-ink-2 hover:border-ink",
                  )}
                >
                  <span className="h-2 w-2 rounded-full" style={{ background: t.color, boxShadow: "0 0 0 1.5px white" }} />
                  {t.short}
                  <span className="opacity-60">{t.sid === model.result?.supplier_id && model.result?.deal ? "✓ deal" : t.status === "walked_away" || t.status === "no_bid" ? "✕" : ""}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        {focus && <Convergence model={model} focus={focus} stories={focusStories} selected={story?.round ?? null} onSelect={(r) => pick(focus.sid, r)} />}
      </Card>

      {/* the selected round */}
      <div ref={cardRef} className="scroll-mt-24">
        {story && focus ? <DecisionCard key={`${focus.sid}-${story.round}`} story={story} thread={focus} flash={flash} /> : <Empty>No rounds logged for this supplier.</Empty>}
      </div>

      {(left.length > 0 || (isNum(v.gapToBest) && v.gapToBest > 1)) && (
        <Card className="p-6">
          <div className="flex flex-wrap items-start justify-between gap-6">
            <div>
              <h3 className="text-[0.95rem] font-semibold tracking-tight">Where we left money</h3>
              <div className="mt-1 text-[0.8rem] text-ink-3">
                {isNum(v.gapToBest) && (
                  <>
                    <span className="font-mono text-ink">{eur(v.gapToBest)}</span> between our deal and the best possible deal.
                  </>
                )}
              </div>
            </div>
            {left.length > 0 && (
              <div className="flex flex-wrap gap-3">
                {left.map((l, i) => (
                  <button
                    key={i}
                    onClick={() => {
                      const t = model.threads.find((x) => x.short === l.supplier);
                      if (t) pick(t.sid, Math.max(1, l.round));
                    }}
                    className="rounded-xl border border-accent/40 bg-accent-soft px-4 py-3 text-left"
                  >
                    <div className="text-[0.68rem] uppercase tracking-[0.12em] text-accent-deep">
                      {l.supplier} · round {l.round} offered
                    </div>
                    <div className="mt-0.5 font-mono text-[1.05rem] font-semibold text-ink">{eur2(l.priced.terms?.unit_price)}</div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {Object.entries(l.priced.terms ?? {})
                        .filter(([k]) => k !== "unit_price")
                        .map(([k, val]) => (
                          <IconChip key={k} label={`${termLabel(k)} ${termValue(k, val)}`} />
                        ))}
                    </div>
                    <div className="mt-1.5 text-[0.72rem] text-ink-2">
                      <span className="font-mono font-semibold text-accent-deep">{eur(l.diff)}</span> cheaper than what we signed
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}

export function withLabels(m: CaseModel): CaseModel {
  const labels = threadLabels(m.threads);
  for (const t of m.threads) t.short = labels.get(t.sid) ?? t.short;
  return m;
}

function fmtPct(p: number) {
  return `${p >= 0 ? "+" : "−"}${Math.abs(p * 100).toFixed(1)} %`;
}
