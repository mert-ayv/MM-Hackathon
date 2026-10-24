import { useEffect, useMemo, useState } from "react";
import type { CaseResponse } from "../lib/api";
import { buildModel, type CaseModel, type Thread } from "../lib/model";
import { eur, eurDelta, score as fmtScore, termLabel, termValue } from "../lib/format";
import { href } from "../lib/router";
import { Card, cx, Empty, Label, Mono, SectionTitle, StatusBadge } from "../components/ui";
import { Gauge } from "../components/Gauge";
import { CLine } from "../components/CLine";
import { Waterfall } from "../components/Waterfall";
import { PlanPanel, SpecialistsPanel } from "../components/Specialists";
import { ThreadTimeline, type Pick } from "../components/Thread";
import { AgentMark } from "./RunsView";

export function CaseView({ data, error, runId, caseId }: { data: CaseResponse | null; error: string | null; runId: string; caseId: string }) {
  const model = useMemo(() => (data ? buildModel(data.events) : null), [data]);
  if (error && !data) return <Empty>Couldn't load {caseId} from {runId}: {error}</Empty>;
  if (!model) return <div className="py-20 text-center text-ink-3">Loading case…</div>;
  return <CaseBody m={model} runId={runId} caseId={caseId} />;
}

function defaultSid(m: CaseModel) {
  return m.result?.supplier_id ?? m.current.sid ?? m.threads[0]?.sid ?? "";
}

/** The round of the latest standing offer: there the specialists and plan explain what got us here. */
function defaultRound(t: Thread | undefined): number {
  if (!t) return 0;
  const r = t.current?.round ?? 0;
  if (r > 0) return r;
  return t.rounds.length ? t.rounds[t.rounds.length - 1].round : 0;
}

function latestPick(t: Thread | undefined): Pick | null {
  if (!t?.current) return null;
  const s = t.current;
  return { priced: s.priced, label: s.round === 0 ? "Opening quote" : `R${s.round} · standing offer`, round: s.round, sid: t.sid };
}

function CaseBody({ m, runId, caseId }: { m: CaseModel; runId: string; caseId: string }) {
  const [sid, setSid] = useState(() => defaultSid(m));
  const t = m.threads.find((x) => x.sid === sid) ?? m.threads[0];
  const [round, setRound] = useState<number | null>(() => defaultRound(t));
  const [pick, setPick] = useState<Pick | null>(() => latestPick(t));

  // live: follow new rounds unless the user picked something older
  const lastRound = t?.rounds[t.rounds.length - 1]?.round ?? 0;
  useEffect(() => {
    if (m.result) return;
    setRound(lastRound);
    setPick(latestPick(t));
  }, [lastRound, m.events.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const selectThread = (s: string) => {
    setSid(s);
    const nt = m.threads.find((x) => x.sid === s);
    setRound(defaultRound(nt));
    setPick(latestPick(nt));
  };
  const selectRound = (r: number, s = t?.sid) => {
    const nt = m.threads.find((x) => x.sid === s) ?? t;
    if (s && s !== sid) setSid(s);
    setRound(r);
    const st = nt?.standing.find((x) => x.round === r);
    const rd = nt?.rounds.find((x) => x.round === r);
    if (st) setPick({ priced: st.priced, label: r === 0 ? "Opening quote" : `R${r} · standing offer`, round: r, sid: nt!.sid });
    else if (rd?.message?.sheets?.[0]) setPick({ priced: rd.message.sheets[0], label: `R${r} · our sheet 1`, round: r, sid: nt!.sid });
  };

  const rd = t?.rounds.find((x) => x.round === round);
  const pickThread = m.threads.find((x) => x.sid === pick?.sid);
  const r = m.result;
  const supplierName = m.threads.find((x) => x.sid === r?.supplier_id)?.name;

  return (
    <div className="space-y-8">
      {/* header */}
      <div>
        <div className="mb-3 flex items-center gap-2 text-[0.78rem] text-ink-3">
          <a href="#/" className="hover:text-ink">Runs</a>
          <span>/</span>
          <Mono>{runId}</Mono>
          <span>/</span>
          <Mono className="text-ink">{caseId}</Mono>
        </div>
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div className="flex items-start gap-4">
            <AgentMark agent={m.agent ?? null} size="lg" />
            <div>
              <h1 className="text-[1.85rem] font-semibold leading-tight tracking-tight">{m.title}</h1>
              <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[0.8rem] text-ink-3">
                <Mono className="text-ink-2">{caseId}</Mono>
                {m.type && <span className="rounded-full border border-line px-2 py-0.5 capitalize">{m.type.replace("_", " ")}</span>}
                <span>{m.threads.length} supplier{m.threads.length > 1 ? "s" : ""}</span>
                {!r && (
                  <span className="inline-flex items-center gap-1.5 text-accent-deep">
                    <span className="h-1.5 w-1.5 animate-pulsedot rounded-full bg-accent" /> live
                  </span>
                )}
              </div>
            </div>
          </div>
          <a
            href={href({ name: "replay", runId, caseId })}
            className="inline-flex items-center gap-2.5 rounded-full bg-accent px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-accent-deep"
          >
            <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden>
              <path d="M2 1 L11 6 L2 11 Z" fill="currentColor" />
            </svg>
            Replay
          </a>
        </div>
        {m.caseFile?.briefing && <p className="mt-4 max-w-4xl text-[0.9rem] leading-relaxed text-ink-2">{m.caseFile.briefing}</p>}
      </div>

      {/* result strip */}
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line md:grid-cols-4 xl:grid-cols-8">
        <Stat label="Score" value={fmtScore(r?.score ?? m.liveScore)} strong />
        <Stat label="Outcome" value={r ? (r.deal ? "Deal" : "No deal") : "Running"} sub={r ? `${r.end_reason ?? ""}${supplierName ? ` · ${shortName(supplierName)}` : ""}` : undefined} />
        <Stat label="C open" value={eur(m.cOpen)} />
        <Stat label="C deal" value={eur(r?.c_deal)} />
        <Stat label="C best" value={eur(m.cBest)} />
        <Stat label="C alt" value={eur(m.cAlt)} />
        <Stat label="€ saved" value={r?.deal && m.cOpen !== null && r.c_deal != null ? eur(m.cOpen - r.c_deal) : "–"} accent />
        <Stat label="Rounds" value={String(m.maxRound)} sub={r?.must_haves_ok === false ? "must-have broken" : undefined} />
      </div>

      {/* gauge + C over rounds */}
      <div className="grid gap-5 lg:grid-cols-12">
        <Card className="p-6 lg:col-span-5">
          <SectionTitle title="Where the deal landed" hint="Standing offer (or deal) between the cheapest opening and the best possible" />
          <Gauge
            cOpen={m.cOpen}
            cBest={m.cBest}
            cAlt={m.cAlt}
            current={m.current}
            score={r?.score ?? m.liveScore}
            marks={m.threads.length > 1 ? m.threads.map((x) => ({ key: x.sid, label: x.short, c: x.current?.c ?? null, color: x.color, dimmed: x.status === "walked_away" || x.status === "no_bid" })) : []}
          />
          {r?.deal && r.terms && (
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 border-t border-line-2 pt-3 text-[0.75rem] text-ink-3">
              {Object.entries(r.terms)
                .filter(([, v]) => v !== null && typeof v !== "object")
                .map(([k, v]) => (
                  <span key={k}>
                    {termLabel(k)} <Mono className="text-ink">{termValue(k, v)}</Mono>
                  </span>
                ))}
            </div>
          )}
        </Card>
        <Card className="p-6 lg:col-span-7">
          <SectionTitle title="C over rounds" hint="Each supplier's standing offer (filled) and our cheapest ask (hollow). Click a point to inspect it." />
          <CLine
            threads={m.threads}
            cOpen={m.cOpen}
            cBest={m.cBest}
            cAlt={m.cAlt}
            rounds={m.maxRound}
            selected={t ? { sid: t.sid, round: round ?? 0 } : null}
            onSelect={(s, rr) => selectRound(rr, s)}
          />
        </Card>
      </div>

      {/* threads + side panels */}
      <div className="grid gap-5 lg:grid-cols-12">
        <div className="lg:col-span-7">
          {m.threads.length > 1 && (
            <div className="mb-5 flex flex-wrap gap-2">
              {m.threads.map((x) => (
                <button
                  key={x.sid}
                  onClick={() => selectThread(x.sid)}
                  className={cx(
                    "flex min-w-[12rem] flex-1 items-center gap-3 rounded-xl border px-4 py-3 text-left transition-all",
                    x.sid === t?.sid ? "border-ink bg-white shadow-card ring-1 ring-ink" : "border-line bg-paper-2 hover:border-ink-3",
                  )}
                >
                  <span className="h-8 w-1 rounded-full" style={{ background: x.color }} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold">{x.short}</div>
                    <Mono className="text-[0.72rem] text-ink-3">{eur(x.current?.c)}</Mono>
                  </div>
                  <StatusBadge status={r?.supplier_id === x.sid && r.deal ? "accepted" : x.status} />
                </button>
              ))}
            </div>
          )}
          {t ? (
            <ThreadTimeline t={t} selectedRound={round} picked={pick} onSelectRound={(rr) => selectRound(rr)} onPick={(p) => { setPick(p); setRound(p.round); }} />
          ) : (
            <Empty>No supplier threads in this log yet.</Empty>
          )}
          {r && (
            <div className="mt-6 pl-14">
              <ResultCard m={m} />
            </div>
          )}
        </div>
        <div className="lg:col-span-5">
          <div className="space-y-5 lg:sticky lg:top-20">
            <Card className="p-6">
              <SectionTitle
                title="C by term"
                hint={pick ? <span>{pickThread?.short} · {pick.label}</span> : "Click any term sheet"}
              />
              <Waterfall
                sheet={pick?.priced}
                base={pick && pick.round !== 0 ? pickThread?.opening?.priced : null}
                baseLabel="Opening quote"
                sheetLabel={pick?.label.split(" · ").pop() ?? "This sheet"}
              />
            </Card>
            <Card className="p-6">
              <SectionTitle title="Specialists" hint={rd ? `Round ${rd.round} · ${t?.short}` : "Select a round"} />
              <SpecialistsPanel rd={rd} />
            </Card>
            <Card className="p-6">
              <SectionTitle title="Plan & decision" hint={rd ? `Round ${rd.round}` : undefined} />
              <PlanPanel rd={rd} picked={pick?.priced} onPick={(p, label) => setPick({ priced: p, label, round: rd!.round, sid: t!.sid })} />
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}

function shortName(n: string) {
  return n.replace(/ (GmbH.*|KG|AG|Sp\. z o\.o\.)$/, "");
}

function Stat({ label, value, sub, strong, accent }: { label: string; value: string; sub?: string; strong?: boolean; accent?: boolean }) {
  return (
    <div className="bg-paper px-4 py-3.5">
      <Label>{label}</Label>
      <Mono className={cx("mt-1 block font-semibold", strong ? "text-[1.6rem] leading-tight" : "text-[1.05rem]", accent && "text-accent-deep")}>{value}</Mono>
      {sub && <div className="mt-0.5 truncate text-[0.7rem] text-ink-3">{sub}</div>}
    </div>
  );
}

export function ResultCard({ m, big = false }: { m: CaseModel; big?: boolean }) {
  const r = m.result;
  if (!r) return null;
  const t = m.threads.find((x) => x.sid === r.supplier_id);
  return (
    <div className={cx("rounded-2xl bg-ink text-white", big ? "p-6" : "p-5")}>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <Label className="!text-white/50">Result · {r.end_reason ?? "ended"}</Label>
          <div className={cx("mt-1 font-semibold tracking-tight", big ? "text-3xl" : "text-xl")}>
            {r.deal ? `Deal with ${t?.short ?? r.supplier_id}` : "No deal"}
          </div>
          {!r.deal && m.cAlt !== null && <div className="mt-1 text-sm text-white/60">Scored on our alternative ({eur(m.cAlt)})</div>}
        </div>
        <div className="flex items-end gap-8">
          {r.deal && r.c_deal != null && m.cOpen !== null && (
            <div className="text-right">
              <Label className="!text-white/50">Saved vs opening</Label>
              <Mono className={cx("block font-semibold text-accent", big ? "text-3xl" : "text-xl")}>{eurDelta(r.c_deal - m.cOpen)}</Mono>
            </div>
          )}
          <div className="text-right">
            <Label className="!text-white/50">Score</Label>
            <Mono className={cx("block font-semibold", big ? "text-5xl" : "text-3xl")}>{fmtScore(r.score)}</Mono>
          </div>
        </div>
      </div>
    </div>
  );
}
