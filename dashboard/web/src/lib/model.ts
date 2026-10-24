import type {
  BackofficeNote,
  BaseEvent,
  CaseFile,
  CaseOpened,
  Decision,
  Dossier,
  ErrorEvent,
  MessageSent,
  Opening,
  Plan,
  Priced,
  Reply,
  Result,
  Specialists,
} from "./types";
import { shortSupplier } from "./format";

export interface RoundData {
  round: number;
  specialists?: Specialists;
  plan?: Plan;
  decision?: Decision;
  message?: MessageSent;
  reply?: Reply;
  errors: ErrorEvent[];
  backoffice: BackofficeNote[];
}

export interface StandingPoint {
  round: number;
  c: number | null;
  priced: Priced;
  offerId?: string;
  status?: string;
  ts: string;
}

export interface Thread {
  sid: string;
  name: string;
  short: string;
  color: string;
  opening?: Opening;
  dossier?: Dossier;
  rounds: RoundData[];
  standing: StandingPoint[]; // round 0 = opening quote
  asks: { round: number; c: number | null }[]; // our cheapest sheet per message
  status: string; // last supplier status, or "accepted"/"walked_away" from us
  closedBy?: "us" | "supplier";
  current?: StandingPoint;
  errors: ErrorEvent[];
}

export interface CaseModel {
  caseId: string;
  runId?: string;
  agent?: string;
  caseFile?: CaseFile;
  title: string;
  type?: string;
  threads: Thread[];
  cOpen: number | null;
  cBest: number | null;
  cAlt: number | null;
  result?: Result;
  events: BaseEvent[];
  last?: BaseEvent;
  maxRound: number;
  /** The cost we would have now: the deal, or the cheapest live standing offer. */
  current: { c: number | null; sid?: string; label: string };
  liveScore: number | null;
  hasAgentInternals: boolean;
}

// Fixed per-supplier identity colours (case order): accent, ink, slate
export const SERIES = ["#FF5A1F", "#0B0B0C", "#8C93A3"];

const isNum = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);

export function scoreOf(cOpen: number | null, c: number | null, cBest: number | null): number | null {
  if (!isNum(cOpen) || !isNum(c) || !isNum(cBest)) return null;
  if (cOpen - cBest <= 0.01) return c <= cBest + 0.01 ? 1 : 0;
  return Math.min(1, Math.max(0, (cOpen - c) / (cOpen - cBest)));
}

/** Build the view model from (a prefix of) a case's events. `hints` lets replay know the end values. */
export function buildModel(events: BaseEvent[], hints: { cBest?: number | null } = {}): CaseModel {
  const sorted = [...events].sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0));
  const threads = new Map<string, Thread>();
  let caseFile: CaseFile | undefined;
  let cAlt: number | null = null;
  let result: Result | undefined;
  let caseId = "";
  let runId: string | undefined;
  let agent: string | undefined;
  let internals = false;

  const thread = (sid: string, name?: string): Thread => {
    let t = threads.get(sid);
    if (!t) {
      const n = name ?? sid;
      t = {
        sid,
        name: n,
        short: shortSupplier(name, sid),
        color: SERIES[threads.size % SERIES.length],
        rounds: [],
        standing: [],
        asks: [],
        status: "open",
        errors: [],
      };
      threads.set(sid, t);
    } else if (name && t.name === sid) {
      t.name = name;
      t.short = shortSupplier(name, sid);
    }
    return t;
  };
  const round = (t: Thread, r: number): RoundData => {
    let rd = t.rounds.find((x) => x.round === r);
    if (!rd) {
      rd = { round: r, errors: [], backoffice: [] };
      t.rounds.push(rd);
      t.rounds.sort((a, b) => a.round - b.round);
    }
    return rd;
  };

  for (const e of sorted) {
    caseId ||= (e.case_id as string) ?? "";
    runId ||= e.run_id as string | undefined;
    agent ||= e.agent as string | undefined;
    switch (e.type) {
      case "case_opened": {
        const ev = e as CaseOpened;
        caseFile = ev.case;
        cAlt = isNum(ev.c_alt) ? ev.c_alt : null;
        const order = ev.case?.suppliers ?? Object.keys(ev.opening ?? {});
        for (const sid of order) thread(sid, ev.opening?.[sid]?.supplier_name);
        for (const [sid, o] of Object.entries(ev.opening ?? {})) {
          const t = thread(sid, o?.supplier_name);
          t.opening = o;
          if (o?.priced) t.standing.push({ round: 0, c: o.priced.c ?? null, priced: o.priced, offerId: o.offer_id, status: "open", ts: e.ts });
        }
        break;
      }
      case "dossier": {
        const ev = e as Dossier;
        if (!ev.supplier_id) break;
        thread(ev.supplier_id, ev.supplier_name).dossier = ev;
        internals = true;
        break;
      }
      case "specialists":
      case "plan":
      case "decision":
      case "message_sent":
      case "reply": {
        const sid = e.supplier_id as string;
        const r = e.round as number;
        if (!sid || !isNum(r)) break;
        const t = thread(sid);
        const rd = round(t, r);
        if (e.type === "specialists") { rd.specialists = e as Specialists; internals = true; }
        if (e.type === "plan") { rd.plan = e as Plan; internals = true; }
        if (e.type === "decision") {
          const d = e as Decision;
          rd.decision = d;
          if (d.kind === "accept") { t.status = "accepted"; t.closedBy = "us"; }
          if (d.kind === "walk_away") { t.status = "walked_away"; t.closedBy = "us"; }
        }
        if (e.type === "message_sent") {
          const m = e as MessageSent;
          rd.message = m;
          const cs = (m.sheets ?? []).map((s) => s?.c).filter(isNum);
          t.asks.push({ round: r, c: cs.length ? Math.min(...cs) : null });
        }
        if (e.type === "reply") {
          const rp = e as Reply;
          rd.reply = rp;
          if (rp.status) {
            t.status = rp.status;
            if (rp.status === "walked_away" || rp.status === "no_bid") t.closedBy = "supplier";
          }
          if (rp.standing?.priced) {
            t.standing.push({ round: r, c: rp.standing.priced.c ?? null, priced: rp.standing.priced, offerId: rp.standing.offer_id, status: rp.status, ts: e.ts });
          }
        }
        break;
      }
      case "error": {
        const ev = e as ErrorEvent;
        if (ev.supplier_id) {
          const t = thread(ev.supplier_id);
          t.errors.push(ev);
          const last = t.rounds[t.rounds.length - 1];
          if (last) last.errors.push(ev);
        }
        break;
      }
      case "result":
        result = e as Result;
        break;
      case "backoffice": {
        const notes = (e.messages as BackofficeNote[] | undefined) ?? [];
        for (const n of notes) {
          if (!n?.supplier_id || typeof n.round !== "number") continue;
          const t = threads.get(n.supplier_id);
          if (t) round(t, n.round).backoffice.push(n);
        }
        break;
      }
      default:
        break; // unknown types are ignored
    }
  }

  const list = [...threads.values()];
  for (const t of list) t.current = t.standing[t.standing.length - 1];

  const openings = list.map((t) => t.standing[0]?.c).filter(isNum);
  const cOpen = isNum(result?.c_open) ? result!.c_open! : openings.length ? Math.min(...openings) : null;
  const cBest = isNum(result?.c_best) ? result!.c_best! : isNum(hints.cBest) ? hints.cBest : null;
  if (isNum(result?.c_alt)) cAlt = result!.c_alt!;

  let current: CaseModel["current"] = { c: null, label: "No offer yet" };
  if (result) {
    if (result.deal && isNum(result.c_deal)) {
      const t = list.find((x) => x.sid === result!.supplier_id);
      current = { c: result.c_deal, sid: result.supplier_id ?? undefined, label: `Deal · ${t?.short ?? result.supplier_id}` };
    } else {
      current = { c: cAlt, label: cAlt !== null ? "No deal · alternative" : "No deal" };
    }
  } else {
    const live = list.filter((t) => t.status !== "walked_away" && t.status !== "no_bid" && isNum(t.current?.c));
    if (live.length) {
      const best = live.reduce((a, b) => (a.current!.c! <= b.current!.c! ? a : b));
      current = { c: best.current!.c, sid: best.sid, label: `Best standing · ${best.short}` };
    }
  }
  const liveScore = result
    ? isNum(result.score) ? result.score : scoreOf(cOpen, current.c, cBest)
    : scoreOf(cOpen, current.c, cBest);

  const maxRound = Math.max(0, ...list.flatMap((t) => t.rounds.map((r) => r.round)));
  return {
    caseId,
    runId,
    agent,
    caseFile,
    title: caseFile?.title ?? caseId,
    type: caseFile?.type,
    threads: list,
    cOpen,
    cBest,
    cAlt,
    result,
    events: sorted,
    last: sorted[sorted.length - 1],
    maxRound,
    current,
    liveScore,
    hasAgentInternals: internals,
  };
}

/** Our claims in the arena's order: message_sent.claims, else the chosen plan candidate's. */
export function sentClaims(rd: RoundData | undefined): { id: string; text: string }[] {
  if (rd?.message?.claims) return rd.message.claims;
  return rd?.plan?.candidates?.find((c) => c.id === rd.decision?.candidate_id)?.claims ?? [];
}

/** Which of our claims a claim_result index refers to. */
export function claimText(rd: RoundData | undefined, index: number): string | undefined {
  if (rd?.message?.claims) return rd.message.claims[index]?.text;
  if (!rd?.plan || !rd.decision?.candidate_id) return undefined;
  const cand = rd.plan.candidates?.find((c) => c.id === rd.decision!.candidate_id);
  return cand?.claims?.[index]?.text;
}

/** The round whose reply a given round's claim results belong to is that round itself. */
export function previousStanding(t: Thread, round: number): StandingPoint | undefined {
  const before = t.standing.filter((s) => s.round < round);
  return before[before.length - 1];
}
