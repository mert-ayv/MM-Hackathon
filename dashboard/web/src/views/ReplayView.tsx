import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CaseResponse } from "../lib/api";
import { buildModel, type CaseModel, type Thread } from "../lib/model";
import { eur, eurDelta, termValue } from "../lib/format";
import { href } from "../lib/router";
import type { BaseEvent, Decision, MessageSent, Plan, Reply, Specialists } from "../lib/types";
import { ClaimBadge, cx, Empty, Label, Mono, Segmented, StatusBadge } from "../components/ui";
import { Gauge } from "../components/Gauge";
import { CLine } from "../components/CLine";
import { Waterfall } from "../components/Waterfall";
import { ResultCard } from "./CaseView";
import { AgentMark } from "./RunsView";

type Speed = "1" | "4" | "16" | "demo";
const SPEEDS: { value: Speed; label: string }[] = [
  { value: "1", label: "1×" },
  { value: "4", label: "4×" },
  { value: "16", label: "16×" },
  { value: "demo", label: "Demo" },
];
const INTERNAL = new Set(["dossier", "specialists", "plan"]);

const ms = (e?: BaseEvent) => (e ? new Date(e.ts).getTime() : 0);

/** Wait before showing event i (i ≥ 1), from the real ts gap. */
function gapBefore(all: BaseEvent[], i: number, speed: Speed): number {
  const raw = Math.max(0, ms(all[i]) - ms(all[i - 1])) || 400;
  if (speed === "demo") {
    const prev = all[i - 1]?.type;
    // give an e-mail that just typed in time to land; skim the agent's internal steps
    if (prev === "reply" || prev === "message_sent") return Math.min(Math.max(raw, 1500), 2200);
    if (INTERNAL.has(all[i].type)) return Math.min(Math.max(raw, 450), 1100);
    return Math.min(Math.max(raw, 600), 2000);
  }
  return Math.max(40, raw / Number(speed));
}

export function ReplayView({ data, error, runId, caseId, at }: { data: CaseResponse | null; error: string | null; runId: string; caseId: string; at?: number }) {
  if (error && !data) return <Empty>Couldn't load {caseId}: {error}</Empty>;
  if (!data) return <div className="py-20 text-center text-ink-3">Loading…</div>;
  return <Replay events={data.events} runId={runId} caseId={caseId} at={at} />;
}

function Replay({ events, runId, caseId, at }: { events: BaseEvent[]; runId: string; caseId: string; at?: number }) {
  const all = useMemo(() => [...events].sort((a, b) => a.seq - b.seq), [events]);
  const full = useMemo(() => buildModel(all), [all]);
  const [idx, setIdx] = useState(() => Math.max(1, Math.min(events.length, at ?? 1)));
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<Speed>("demo");
  const [chart, setChart] = useState<"line" | "terms">("line");
  const n = all.length;

  const m = useMemo(() => buildModel(all.slice(0, idx), { cBest: full.cBest }), [all, idx, full.cBest]);

  useEffect(() => {
    if (!playing) return;
    if (idx >= n) {
      setPlaying(false);
      return;
    }
    const id = setTimeout(() => setIdx((i) => Math.min(n, i + 1)), gapBefore(all, idx, speed));
    return () => clearTimeout(id);
  }, [playing, idx, n, speed, all]);

  const toggle = useCallback(() => {
    setPlaying((p) => {
      if (!p && idx >= n) setIdx(1);
      return !p;
    });
  }, [idx, n]);

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;
      if (e.key === " ") {
        e.preventDefault();
        toggle();
      } else if (e.key === "ArrowRight") {
        setPlaying(false);
        setIdx((i) => Math.min(n, i + 1));
      } else if (e.key === "ArrowLeft") {
        setPlaying(false);
        setIdx((i) => Math.max(1, i - 1));
      } else if (e.key === "Home") {
        setPlaying(false);
        setIdx(1);
      } else if (e.key === "End") {
        setPlaying(false);
        setIdx(n);
      } else if (["1", "2", "3", "4"].includes(e.key)) {
        setSpeed(SPEEDS[Number(e.key) - 1].value);
      } else if (e.key === "f") {
        if (document.fullscreenElement) document.exitFullscreen();
        else document.documentElement.requestFullscreen?.();
      }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [toggle, n]);

  const last = all[idx - 1];
  const nextGap = idx < n ? gapBefore(all, idx, speed) : 1800;
  const typing = playing && (last?.type === "message_sent" || last?.type === "reply");
  const t0 = ms(all[0]);
  const elapsed = (ms(last) - t0) / 1000;
  const total = (ms(all[n - 1]) - t0) / 1000;

  // focus thread: the one the latest event belongs to
  const focusSid = (last?.supplier_id as string) || m.current.sid || m.threads[0]?.sid;
  const focus = m.threads.find((t) => t.sid === focusSid) ?? m.threads[0];
  const round = (last?.round as number) ?? (focus?.rounds.length ? focus.rounds[focus.rounds.length - 1].round : 0);

  return (
    <div className="flex min-h-[calc(100vh-4rem)] flex-col">
      {/* title bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 pb-5">
        <div className="flex items-center gap-4">
          <a href={href({ name: "case", runId, caseId })} className="rounded-full border border-line px-3 py-1.5 text-sm text-ink-3 hover:border-ink hover:text-ink">
            ← Case
          </a>
          <AgentMark agent={full.agent ?? null} size="lg" />
          <div>
            <h1 className="text-[1.6rem] font-semibold leading-tight tracking-tight">{full.title}</h1>
            <div className="text-sm text-ink-3">
              <Mono>{caseId}</Mono> · {full.threads.map((t) => t.short).join(", ")}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="rounded-full bg-ink px-4 py-1.5 font-mono text-sm font-semibold text-white">
            {idx <= 1 ? "Opening" : `Round ${Math.max(1, round)}`}
          </div>
          {m.result ? <StatusBadge status={m.result.deal ? "accepted" : "walked_away"} size="lg" /> : playing ? (
            <span className="inline-flex items-center gap-2 text-sm font-medium text-accent-deep">
              <span className="h-2 w-2 animate-pulsedot rounded-full bg-accent" /> Live
            </span>
          ) : null}
        </div>
      </div>

      {/* stage */}
      <div className="grid flex-1 gap-6 xl:grid-cols-12">
        <div className="min-w-0 xl:col-span-7">
          <div className={cx("grid gap-4", m.threads.length === 2 && "md:grid-cols-2", m.threads.length >= 3 && "md:grid-cols-3")}>
            {m.threads.map((t) => (
              <Lane key={t.sid} t={t} m={m} last={last} typing={typing} typeMs={nextGap * 0.8} single={m.threads.length === 1} focus={t.sid === focus?.sid} />
            ))}
          </div>
        </div>
        <div className="space-y-5 xl:col-span-5">
          <div className="rounded-2xl border border-line bg-white p-7 shadow-card">
            <Gauge
              big
              cOpen={m.cOpen}
              cBest={m.cBest}
              cAlt={m.cAlt}
              current={m.current}
              score={m.result ? m.result.score ?? m.liveScore : m.liveScore}
              marks={m.threads.length > 1 ? m.threads.map((t) => ({ key: t.sid, label: t.short, c: t.current?.c ?? null, color: t.color, dimmed: t.status === "walked_away" || t.status === "no_bid" })) : []}
            />
          </div>
          <div className="rounded-2xl border border-line bg-white p-6 shadow-card">
            <div className="mb-3 flex items-center justify-between">
              <Label>{chart === "line" ? "C over rounds" : `C by term · ${focus?.short ?? ""} vs its opening`}</Label>
              <Segmented value={chart} onChange={setChart} options={[{ value: "line", label: "Rounds" }, { value: "terms", label: "By term" }]} />
            </div>
            {chart === "line" ? (
              <CLine big threads={m.threads} cOpen={m.cOpen} cBest={m.cBest} cAlt={m.cAlt} rounds={full.maxRound} height={210} selected={focus ? { sid: focus.sid, round: Math.max(0, round) } : null} />
            ) : (
              <Waterfall big showTerms={false} sheet={focus?.current?.priced} base={focus?.current?.round ? focus?.opening?.priced : null} sheetLabel="Standing now" />
            )}
          </div>
          {m.result && idx === n ? (
            <div className="animate-rise">
              <ResultCard m={m} big />
            </div>
          ) : (
            <AgentCard m={m} last={last} />
          )}
        </div>
      </div>


      {/* transport */}
      <div className="sticky bottom-0 z-20 -mx-8 mt-6 border-t border-line bg-white/95 px-8 py-4 backdrop-blur">
        <div className="flex flex-wrap items-center gap-5">
          <div className="flex items-center gap-2">
            <IconBtn title="Restart (Home)" onClick={() => { setPlaying(false); setIdx(1); }}>⏮</IconBtn>
            <IconBtn title="Step back (←)" onClick={() => { setPlaying(false); setIdx((i) => Math.max(1, i - 1)); }}>◀</IconBtn>
            <button
              onClick={toggle}
              title="Play / pause (Space)"
              className="flex h-12 w-12 items-center justify-center rounded-full bg-accent text-white shadow transition hover:bg-accent-deep"
            >
              {playing ? (
                <svg width="16" height="16" viewBox="0 0 16 16"><rect x="3" y="2" width="3.5" height="12" rx="1" fill="currentColor" /><rect x="9.5" y="2" width="3.5" height="12" rx="1" fill="currentColor" /></svg>
              ) : (
                <svg width="16" height="16" viewBox="0 0 16 16"><path d="M4 2 L14 8 L4 14 Z" fill="currentColor" /></svg>
              )}
            </button>
            <IconBtn title="Step (→)" onClick={() => { setPlaying(false); setIdx((i) => Math.min(n, i + 1)); }}>▶</IconBtn>
            <IconBtn title="End (End)" onClick={() => { setPlaying(false); setIdx(n); }}>⏭</IconBtn>
          </div>
          <div className="flex min-w-[16rem] flex-1 items-center gap-3">
            <Mono className="w-14 text-right text-sm text-ink-3">{clock(elapsed)}</Mono>
            <Scrubber all={all} idx={idx} onSeek={(i) => { setPlaying(false); setIdx(i); }} />
            <Mono className="w-14 text-sm text-ink-3">{clock(total)}</Mono>
          </div>
          <Segmented size="lg" value={speed} onChange={setSpeed} options={SPEEDS} />
          <Mono className="text-xs text-ink-4">
            {idx}/{n}
          </Mono>
        </div>
      </div>
    </div>
  );
}

function clock(s: number) {
  if (!Number.isFinite(s) || s < 0) s = 0;
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

function IconBtn({ children, onClick, title }: { children: React.ReactNode; onClick: () => void; title: string }) {
  return (
    <button onClick={onClick} title={title} className="flex h-9 w-9 items-center justify-center rounded-full border border-line text-xs text-ink-2 transition hover:border-ink hover:text-ink">
      {children}
    </button>
  );
}

function Scrubber({ all, idx, onSeek }: { all: BaseEvent[]; idx: number; onSeek: (i: number) => void }) {
  const t0 = ms(all[0]);
  const span = Math.max(1, ms(all[all.length - 1]) - t0);
  const ref = useRef<HTMLDivElement>(null);
  const seek = (clientX: number) => {
    const r = ref.current!.getBoundingClientRect();
    const target = t0 + ((clientX - r.left) / r.width) * span;
    let best = 1;
    all.forEach((e, i) => {
      if (ms(e) <= target) best = i + 1;
    });
    onSeek(Math.max(1, best));
  };
  const pos = ((ms(all[idx - 1]) - t0) / span) * 100;
  return (
    <div ref={ref} className="relative h-8 flex-1 cursor-pointer" onClick={(e) => seek(e.clientX)}>
      <div className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-paper-3" />
      <div className="absolute left-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-ink transition-[width] duration-300" style={{ width: `${pos}%` }} />
      {all.map((e, i) =>
        e.type === "reply" || e.type === "message_sent" || e.type === "result" ? (
          <div
            key={i}
            className={cx("absolute top-1/2 h-2.5 w-0.5 -translate-y-1/2 rounded", e.type === "result" ? "bg-accent" : e.type === "reply" ? "bg-ink-3" : "bg-ink-4")}
            style={{ left: `${((ms(e) - t0) / span) * 100}%` }}
          />
        ) : null,
      )}
      <div className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-[3px] border-accent bg-white shadow transition-[left] duration-300" style={{ left: `${pos}%` }} />
    </div>
  );
}

/** Reveals text over `duration` ms. */
function TypeIn({ text, active, duration }: { text: string; active: boolean; duration: number }) {
  const [k, setK] = useState(active ? 0 : text.length);
  useEffect(() => {
    if (!active) {
      setK(text.length);
      return;
    }
    setK(0);
    const t0 = performance.now();
    const d = Math.max(300, Math.min(duration, text.length * 25));
    let raf = 0;
    const step = (now: number) => {
      const p = Math.min(1, (now - t0) / d);
      setK(Math.round(p * text.length));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [text, active, duration]);
  return (
    <>
      {text.slice(0, k)}
      {k < text.length && <span className="ml-0.5 inline-block h-[1.05em] w-[2px] translate-y-[2px] animate-pulsedot bg-accent" />}
    </>
  );
}

/** The gist of an e-mail: no salutation, no signature, one paragraph. */
function excerpt(body: string): string {
  const paras = body.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
  const isGreeting = (p: string) => /^(dear|guten tag|hello|hi|sehr geehrte)\b/i.test(p) && p.length < 60;
  const isSign = (p: string) => /^(best regards|kind regards|viele grüße|mit freundlichen|herzliche grüße|yours|regards)/i.test(p);
  const core = paras.filter((p) => !isGreeting(p) && !isSign(p));
  return (core.length ? core : paras).join(" ").replace(/\s*\n\s*/g, " ");
}

type Item =
  | { kind: "opening"; key: string; body: string; c: number | null }
  | { kind: "decision"; key: string; ev: Decision }
  | { kind: "message"; key: string; ev: MessageSent }
  | { kind: "reply"; key: string; ev: Reply; delta: number | null }
  | { kind: "error"; key: string; text: string };

function laneItems(t: Thread): Item[] {
  const items: Item[] = [];
  if (t.opening) items.push({ kind: "opening", key: "open", body: t.opening.body ?? "", c: t.opening.priced?.c ?? null });
  let prevC = t.opening?.priced?.c ?? null;
  for (const rd of t.rounds) {
    if (rd.decision) items.push({ kind: "decision", key: `d${rd.round}`, ev: rd.decision });
    if (rd.message) items.push({ kind: "message", key: `m${rd.round}`, ev: rd.message });
    rd.errors.forEach((e, i) => items.push({ kind: "error", key: `e${rd.round}-${i}`, text: `${e.status ?? ""} ${e.detail ?? ""}` }));
    if (rd.reply) {
      const c = rd.reply.standing?.priced?.c ?? null;
      items.push({ kind: "reply", key: `r${rd.round}`, ev: rd.reply, delta: c !== null && prevC !== null ? c - prevC : null });
      if (c !== null) prevC = c;
    }
  }
  return items;
}

function Lane({ t, m, last, typing, typeMs, single, focus }: { t: Thread; m: CaseModel; last?: BaseEvent; typing: boolean; typeMs: number; single: boolean; focus: boolean }) {
  const items = laneItems(t);
  const box = useRef<HTMLDivElement>(null);
  // keep the newest item in view (scroll the lane only, never the page)
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    const id = setInterval(() => el.scrollTo({ top: el.scrollHeight }), 250); // follow the text while it types in
    const stop = setTimeout(() => clearInterval(id), 2500);
    return () => {
      clearInterval(id);
      clearTimeout(stop);
    };
  }, [items.length]);
  const deal = m.result?.deal && m.result.supplier_id === t.sid;
  const closed = t.status === "walked_away" || t.status === "no_bid";
  const status = deal ? "accepted" : t.status;
  return (
    <div className={cx("flex min-w-0 flex-col rounded-2xl border bg-paper-2 transition-all", focus && !single ? "border-ink" : "border-line", closed && "opacity-60")}>
      <div className="flex items-center gap-3 border-b border-line px-4 py-3">
        <span className="h-7 w-1 rounded-full" style={{ background: t.color }} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-base font-semibold">{t.short}</div>
          <Mono className="text-sm text-ink-3">{eur(t.current?.c)}</Mono>
        </div>
        <StatusBadge status={status} />
      </div>
      <div ref={box} className="max-h-[calc(100vh-19.5rem)] space-y-3 overflow-y-auto p-3">
        {items.map((it, i) => {
          const newest = i === items.length - 1;
          const isLast = (it.kind === "message" || it.kind === "reply") && last && it.ev === last;
          return (
            <div key={it.key} className="animate-rise">
              <LaneItem it={it} t={t} typing={!!isLast && typing} typeMs={typeMs} compact={single ? i < items.length - 3 : !newest} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

function LaneItem({ it, t, typing, typeMs, compact }: { it: Item; t: Thread; typing: boolean; typeMs: number; compact: boolean }) {
  const clamp = compact ? "line-clamp-2" : "";
  const text = (b: string | undefined) => (compact ? excerpt(b ?? "") : b ?? "");
  if (it.kind === "opening")
    return (
      <div className="rounded-xl border border-line bg-white p-4">
        <div className="mb-1 flex items-center justify-between text-sm">
          <span className="font-semibold">{t.short} · opening quote</span>
          <Mono className="text-sm font-semibold">{eur(it.c)}</Mono>
        </div>
        <p className={cx("whitespace-pre-wrap text-[0.95rem] leading-relaxed text-ink-2", clamp)}>{text(it.body)}</p>
      </div>
    );
  if (it.kind === "decision")
    return (
      <div className="flex gap-2.5 px-1 text-[0.9rem] leading-snug text-ink-3">
        <span className={cx("mt-0.5 shrink-0 self-start rounded px-1.5 py-0.5 text-[0.62rem] font-semibold uppercase tracking-wider", it.ev.kind === "send" ? "bg-paper-3 text-ink-2" : "bg-accent text-white")}>
          {it.ev.kind.replace("_", " ")}
        </span>
        <span className={clamp}>{it.ev.reason || (it.ev.kind === "accept" ? "Accept the standing offer." : it.ev.kind === "walk_away" ? "Walk away." : "")}</span>
      </div>
    );
  if (it.kind === "error") return <div className="rounded-lg bg-accent-soft px-3 py-2 font-mono text-xs text-accent-deep">{it.text}</div>;
  if (it.kind === "message") {
    const sheets = it.ev.sheets ?? [];
    return (
      <div className="ml-6 rounded-xl bg-ink p-4 text-white">
        <div className="mb-1 text-xs text-white/50">Hollerau → {t.short}</div>
        <div className="text-[0.95rem] font-semibold">{it.ev.subject}</div>
        <p className={cx("mt-1.5 whitespace-pre-wrap text-[0.95rem] leading-relaxed text-white/85", clamp)}>
          <TypeIn text={text(it.ev.body)} active={typing} duration={typeMs} />
        </p>
        {sheets.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {sheets.map((s, i) => (
              <span key={i} className="rounded-md bg-white/10 px-2 py-1 font-mono text-xs tabular-nums">
                {termValue("unit_price", s.terms.unit_price)} · C {eur(s.c)}
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }
  const rp = it.ev;
  return (
    <div className={cx("mr-6 rounded-xl border bg-white p-4", rp.status === "final_offer" ? "border-accent" : "border-line")}>
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="text-xs text-ink-3">{rp.from ?? t.short}</span>
        <StatusBadge status={rp.status} />
      </div>
      <p className={cx("whitespace-pre-wrap text-[0.95rem] leading-relaxed text-ink-2", clamp)}>
        <TypeIn text={text(rp.body)} active={typing} duration={typeMs} />
      </p>
      {(rp.standing?.priced || (rp.claim_results?.length ?? 0) > 0) && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {rp.standing?.priced && (
            <span className="rounded-md bg-paper-3 px-2 py-1 font-mono text-xs font-semibold tabular-nums">
              C {eur(rp.standing.priced.c)}
              {it.delta !== null && Math.abs(it.delta) >= 0.5 && <span className={cx("ml-1.5", it.delta < 0 ? "text-accent-deep" : "text-ink-3")}>{eurDelta(it.delta)}</span>}
            </span>
          )}
          {rp.claim_results?.map((c) => <ClaimBadge key={c.index} result={c.result} />)}
        </div>
      )}
    </div>
  );
}

/** What the agent is doing right now: specialists, plan or decision. */
function AgentCard({ m, last }: { m: CaseModel; last?: BaseEvent }) {
  // find the newest internal step across threads
  let step: { kind: string; ev: BaseEvent } | null = null;
  for (let i = m.events.length - 1; i >= 0; i--) {
    const e = m.events[i];
    if (["dossier", "specialists", "plan", "decision"].includes(e.type)) {
      step = { kind: e.type, ev: e };
      break;
    }
  }
  if (!step) return null;
  const t = m.threads.find((x) => x.sid === step!.ev.supplier_id);
  const fresh = step.ev === last;
  let title = "";
  let body: React.ReactNode = null;
  if (step.kind === "dossier") {
    title = "Reading the supplier";
    body = <p>{String(step.ev.summary ?? "")}</p>;
  } else if (step.kind === "specialists") {
    const outs = (step.ev as Specialists).outputs ?? {};
    const top = Object.entries(outs)
      .filter(([, o]) => (o.value_for_us_eur ?? 0) > 0.5)
      .sort((a, b) => (b[1].value_for_us_eur ?? 0) - (a[1].value_for_us_eur ?? 0))
      .slice(0, 3);
    title = `${Object.keys(outs).length} specialists priced their levers`;
    body = (
      <div className="space-y-1.5">
        {top.map(([name, o]) => (
          <div key={name} className="flex items-center justify-between gap-3">
            <span className="capitalize">
              {name} <Mono className="text-sm text-white/50">{o.proposal}</Mono>
            </span>
            <Mono className="font-semibold text-accent">{eurDelta(o.value_for_us_eur)}</Mono>
          </div>
        ))}
        {!top.length && <span className="text-white/60">No lever worth more for us right now.</span>}
      </div>
    );
  } else if (step.kind === "plan") {
    const p = step.ev as Plan;
    title = `Strategist weighs ${p.candidates?.length ?? 0} options`;
    body = (
      <div className="space-y-1">
        {p.candidates?.map((c) => (
          <div key={c.id} className="flex items-center justify-between gap-3">
            <span>{c.label}</span>
            <Mono className="text-sm text-white/60">{c.sheets?.map((s) => eur(s.c)).join(" / ")}</Mono>
          </div>
        ))}
      </div>
    );
  } else {
    const d = step.ev as Decision;
    title = d.kind === "send" ? "Decision: send" : d.kind === "accept" ? "Decision: accept" : "Decision: walk away";
    body = <p>{d.reason || "No reason logged for this move."}</p>;
  }
  return (
    <div key={step.ev.seq} className={cx("rounded-2xl bg-ink p-6 text-white", fresh && "animate-rise")}>
      <div className="mb-2 flex items-center justify-between">
        <Label className="!text-white/50">Agent{t ? ` · ${t.short}` : ""}</Label>
        {fresh && <span className="h-2 w-2 animate-pulsedot rounded-full bg-accent" />}
      </div>
      <div className="mb-2 text-lg font-semibold">{title}</div>
      <div className="text-[1rem] leading-relaxed text-white/85">{body}</div>
    </div>
  );
}
