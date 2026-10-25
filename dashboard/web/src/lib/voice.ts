// The voice copilot's brain on the browser side: which negotiation is open, the debrief text (built by
// code, never by the LLM), and the client tools the ElevenLabs agent calls. Every number it says comes
// from these tools, which read the run log through the local API.
import { buildModel, type CaseModel, type Thread } from "./model";
import { studio, formatValue } from "./studio";
import type { BaseEvent } from "./types";

export interface CaseRef {
  runId: string;
  caseId: string;
}

// The pitch's showcase negotiation (P01 Brandlhuber, 0.926): the fallback when no case is open
export const SHOWCASE: CaseRef = { runId: "20261024-165810-go49mor-v15", caseId: "case:P01" };

declare global {
  interface Window {
    __copilotCase?: { runId: string; caseId: string; summary?: unknown };
  }
}

export function currentCase(): CaseRef | null {
  const path = window.location.hash.replace(/^#\/?/, "").split("?")[0];
  const parts = path.split("/").map(decodeURIComponent);
  if ((parts[0] === "n" || parts[0] === "case" || parts[0] === "replay") && parts[1] && parts[2])
    return { runId: parts[1], caseId: parts[2] };
  const w = window.__copilotCase;
  return w?.runId && w.caseId ? { runId: w.runId, caseId: w.caseId } : null;
}

export function mode(): "negotiation" | "playbook" {
  return window.location.hash.startsWith("#/studio") ? "playbook" : "negotiation";
}

// ---------------------------------------------------------------------------------------------------
// activity bus: tool chips and toasts for the dock

export type Activity = { id: number; kind: "tool" | "toast"; text: string };
const activityListeners = new Set<(a: Activity) => void>();
let activitySeq = 0;
export function onActivity(fn: (a: Activity) => void) {
  activityListeners.add(fn);
  return () => {
    activityListeners.delete(fn);
  };
}
export function emit(kind: Activity["kind"], text: string) {
  const a = { id: ++activitySeq, kind, text };
  activityListeners.forEach((fn) => fn(a));
}

// ---------------------------------------------------------------------------------------------------
// case data

const cache = new Map<string, Promise<CaseModel>>();
export function loadCase(ref: CaseRef): Promise<CaseModel> {
  const k = `${ref.runId}/${ref.caseId}`;
  let p = cache.get(k);
  if (!p) {
    p = fetch(`/api/runs/${encodeURIComponent(ref.runId)}/cases/${encodeURIComponent(ref.caseId)}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} for ${k}`);
        return r.json() as Promise<{ events: BaseEvent[] }>;
      })
      .then((d) => buildModel(d.events));
    p.catch(() => cache.delete(k));
    cache.set(k, p);
  }
  return p;
}

const r0 = (n: number | null | undefined) => (typeof n === "number" ? Math.round(n) : null);
const speakEur = (n: number) => `€${Math.round(n).toLocaleString("en-US")}`;
const last = <T,>(xs: T[]): T | undefined => xs[xs.length - 1];
const shortCase = (id: string) => id.replace(/^case:/, "");

function dealThread(m: CaseModel): Thread | undefined {
  const sid = m.result?.supplier_id;
  return m.threads.find((t) => t.sid === sid) ?? m.threads[0];
}

function findThread(m: CaseModel, supplier?: string): Thread | undefined {
  if (!supplier) return dealThread(m);
  const q = supplier.toLowerCase();
  return (
    m.threads.find((t) => t.sid.toLowerCase() === q) ??
    m.threads.find((t) => t.name.toLowerCase().includes(q) || t.short.toLowerCase().includes(q) || q.includes(t.short.toLowerCase())) ??
    dealThread(m)
  );
}

function claimStats(m: CaseModel) {
  const out: { round: number; supplier: string; text: string; result: string }[] = [];
  for (const t of m.threads)
    for (const rd of t.rounds) {
      const claims = rd.message?.claims ?? [];
      for (const cr of rd.reply?.claim_results ?? [])
        out.push({ round: rd.round, supplier: t.short, text: claims[cr.index]?.text ?? `claim ${cr.index + 1}`, result: cr.result });
    }
  return out;
}

const claimTopic = (text: string) => text.split(":")[0].trim();

function fmtDate(d: unknown) {
  if (typeof d !== "string") return null;
  const t = new Date(d);
  return Number.isNaN(+t) ? d : t.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
}

/** The spoken opening: ~20 s, every figure from the log. */
export function buildDebrief(m: CaseModel): string {
  const t = dealThread(m);
  const res = m.result;
  const who = t?.short ?? "the supplier";
  const parts: string[] = [];
  if (res?.deal && res.c_open != null && res.c_deal != null) {
    const terms = res.terms ?? {};
    const price = typeof terms.unit_price === "number" ? `€${terms.unit_price.toFixed(2)} per unit` : "the agreed terms";
    const from = fmtDate(terms.effective_date);
    parts.push(
      `${shortCase(m.caseId)}, ${who}: we closed in ${m.maxRound} rounds at ${price}${from ? ` from ${from}` : ""}.`,
      `That is ${speakEur(res.c_open - res.c_deal)} below their opening offer${res.score != null ? `, a score of ${res.score.toFixed(2)}` : ""}.`,
    );
  } else if (res) {
    parts.push(`${shortCase(m.caseId)}, ${who}: no deal, the negotiation ended with ${String(res.end_reason ?? "no agreement").replace(/_/g, " ")}.`);
  } else {
    parts.push(`${shortCase(m.caseId)} with ${who} is still running, round ${m.maxRound} so far.`);
  }
  const verified = claimStats(m).filter((c) => c.result === "verified");
  if (verified.length) {
    const topics = [...new Set(verified.map((c) => claimTopic(c.text)))].slice(0, 3);
    parts.push(`${verified.length} of our arguments were verified by the supplier, among them ${topics.join(", ")}.`);
  }
  if (res?.c_deal != null && res.c_best != null && res.c_deal - res.c_best > 1)
    parts.push(`${speakEur(res.c_deal - res.c_best)} stayed on the table against the best possible deal.`);
  parts.push("Ask me why we did anything, or what I would change.");
  return parts.join(" ");
}

/** Compact facts for the agent's prompt (a dynamic variable). */
export function buildContext(m: CaseModel): string {
  const lines = [`Case ${m.caseId} (${m.type ?? "?"}): ${m.title}. Run ${m.runId ?? "?"}, agent ${m.agent ?? "?"}.`];
  for (const t of m.threads)
    lines.push(`Supplier ${t.name} [${t.sid}]: ${t.rounds.length} rounds, last status ${t.status}.`);
  const r = m.result;
  if (r) lines.push(`Result: deal=${r.deal}, score=${r.score?.toFixed(3)}, C open ${r0(r.c_open)}, C deal ${r0(r.c_deal)}, C best ${r0(r.c_best)}, end ${r.end_reason}.`);
  return lines.join("\n");
}

// ---------------------------------------------------------------------------------------------------
// client tools (names and parameters match dashboard/voice/agent.json)

type P = Record<string, unknown>;
const str = (v: unknown) => (typeof v === "string" && v.trim() ? v.trim() : undefined);
const num = (v: unknown) => (v === undefined || v === null || v === "" ? undefined : Number.isFinite(Number(v)) ? Number(v) : undefined);
const cut = (s: unknown, n: number) => (typeof s === "string" ? (s.length > n ? `${s.slice(0, n)}…` : s) : undefined);
const json = (o: unknown) => JSON.stringify(o, (_k, v) => (typeof v === "number" && !Number.isInteger(v) ? Math.round(v * 100) / 100 : v));

const NODE_IDS = ["intake", "router", "dossier", "evidence", "levers", "planner", "writer", "guard", "outcome"];

async function needCase(): Promise<[CaseRef, CaseModel]> {
  const ref = currentCase() ?? SHOWCASE;
  return [ref, await loadCase(ref)];
}

function show(detail: { round?: number; supplier?: string }) {
  window.dispatchEvent(new CustomEvent("copilot:show", { detail }));
}

export function makeClientTools(): Record<string, (p: P) => Promise<string>> {
  return {
    async get_case_summary() {
      emit("tool", "Reading the case");
      const [ref, m] = await needCase();
      const r = m.result;
      return json({
        case: ref.caseId,
        title: m.title,
        type: m.type,
        rounds: m.maxRound,
        suppliers: m.threads.map((t) => ({
          name: t.name,
          id: t.sid,
          status: t.status,
          rounds: t.rounds.length,
          opening_cost_eur: r0(t.standing[0]?.c),
          last_offer_cost_eur: r0(t.current?.c),
        })),
        result: r && {
          deal: r.deal,
          score: r.score,
          terms: r.terms,
          cost_open_eur: r0(r.c_open),
          cost_deal_eur: r0(r.c_deal),
          cost_best_possible_eur: r0(r.c_best),
          cost_alternative_eur: r0(r.c_alt),
          saved_vs_opening_eur: r.c_open != null && r.c_deal != null ? r0(r.c_open - r.c_deal) : null,
          left_on_table_vs_best_eur: r.c_deal != null && r.c_best != null ? r0(r.c_deal - r.c_best) : null,
          end_reason: r.end_reason,
        },
        claims: claimStats(m),
        note: "cost_* = total cost of ownership over the contract in EUR (lower is better).",
      });
    },

    async get_round(p) {
      const [, m] = await needCase();
      const t = findThread(m, str(p.supplier));
      if (!t) return "No supplier thread in this case.";
      const round = num(p.round) ?? t.rounds.length;
      const rd = t.rounds.find((x) => x.round === round);
      emit("tool", `Looking at round ${round}${m.threads.length > 1 ? ` · ${t.short}` : ""}`);
      show({ round, supplier: t.sid });
      if (!rd) return `No round ${round} with ${t.short}; it has rounds 1 to ${t.rounds.length}.`;
      const claims = rd.message?.claims ?? [];
      const prevAsk = t.asks.find((a) => a.round === round - 1)?.c;
      const ask = t.asks.find((a) => a.round === round)?.c;
      const prevStanding = last(t.standing.filter((s) => s.round < round))?.c;
      const standing = rd.reply?.standing?.priced?.c;
      return json({
        supplier: t.name,
        round,
        our_message: rd.message && {
          subject: rd.message.subject,
          body: cut(rd.message.body, 700),
          offers: (rd.message.sheets ?? []).map((s) => ({ cost_eur: r0(s.c), terms: s.terms })),
          arguments: claims.map((c, i) => ({ text: c.text, result: rd.reply?.claim_results?.find((x) => x.index === i)?.result ?? "unknown" })),
        },
        our_cheapest_offer_cost_eur: r0(ask),
        our_move_vs_previous_round_eur: ask != null && prevAsk != null ? r0(ask - prevAsk) : null,
        decision: rd.decision && { kind: rd.decision.kind, reason: rd.decision.reason },
        planner_options: (rd.plan?.candidates ?? []).slice(0, 4).map((c) => ({ id: c.id, label: c.label, rationale: cut(c.rationale, 200) })),
        planner_walk_away_cost_eur: r0(rd.plan?.walk_away_c),
        supplier_reply: rd.reply && {
          status: rd.reply.status,
          body: cut(rd.reply.body, 600),
          reasons: rd.reply.reasons?.slice(0, 4),
          standing_offer_cost_eur: r0(standing),
          their_move_vs_previous_eur: standing != null && prevStanding != null ? r0(standing - prevStanding) : null,
        },
        supplier_internal_notes: rd.backoffice.map((b) => `${b.from ?? "?"}: ${b.text}`).slice(0, 4),
      });
    },

    async get_cost_breakdown(p) {
      const [, m] = await needCase();
      const round = num(p.round);
      if (round === undefined && m.result?.cost_breakdown) {
        emit("tool", "Pricing the deal term by term");
        return json({ what: "the final deal", total_eur: r0(m.result.c_deal), by_term_eur: m.result.cost_breakdown });
      }
      const t = findThread(m, str(p.supplier));
      const pt = last(t?.standing.filter((s) => round === undefined || s.round <= round) ?? []);
      emit("tool", `Pricing ${t?.short ?? "the offer"}${round !== undefined ? ` · round ${round}` : ""}`);
      if (!pt) return "No priced offer found.";
      return json({ what: `${t?.name} standing offer after round ${pt.round}`, total_eur: r0(pt.c), by_term_eur: pt.priced.breakdown, terms: pt.priced.terms });
    },

    async get_supplier(p) {
      const [, m] = await needCase();
      const t = findThread(m, str(p.supplier));
      if (!t) return "No such supplier in this case.";
      emit("tool", `Opening the dossier · ${t.short}`);
      const d = t.dossier;
      return json({
        name: t.name,
        id: t.sid,
        summary: d?.summary,
        persona: d?.persona,
        estimated_cost_floor_eur: r0(d?.floor_estimate),
        facts: d?.facts?.slice(0, 8).map((f) => f.text),
        opening_quote: t.opening?.priced && { cost_eur: r0(t.opening.priced.c), terms: t.opening.priced.terms },
        status: t.status,
      });
    },

    async get_portfolio() {
      emit("tool", "Scanning all negotiations");
      const runs = (await fetch("/api/runs").then((r) => r.json())) as {
        runs: { run_id: string; set?: string; case_summaries?: { case_id: string; type: string | null; score: number | null; deal: boolean | null; saved: number | null; end_reason: string | null }[] }[];
      };
      const rows = runs.runs.flatMap((r) => (r.case_summaries ?? []).map((c) => ({ run: r.run_id, set: r.set, ...c })));
      const byType = new Map<string, { n: number; sum: number; walks: number }>();
      for (const c of rows) {
        const k = c.type ?? "unknown";
        const b = byType.get(k) ?? { n: 0, sum: 0, walks: 0 };
        b.n += 1;
        b.sum += c.score ?? 0;
        if (c.deal === false) b.walks += 1;
        byType.set(k, b);
      }
      return json({
        negotiations: rows.length,
        by_case_type: [...byType].map(([type, b]) => ({ type, negotiations: b.n, mean_score: b.sum / b.n, no_deal: b.walks })),
        weakest: rows.filter((c) => c.score != null).sort((a, b) => (a.score ?? 0) - (b.score ?? 0)).slice(0, 5),
      });
    },

    async list_playbook() {
      emit("tool", "Reading the playbook");
      const s = studio.get();
      return json({
        nodes: s.nodes.map((n) => ({ id: n.id, title: n.title, what: n.subtitle, settings: Object.fromEntries(n.params.map((p) => [p.key, `${p.label}: ${formatValue(p)}`])) })),
        pending_suggestions: s.suggestions.filter((x) => x.status === "pending").map((x) => x.title),
      });
    },

    async propose_change(p) {
      const s = studio.get();
      const nodeId = str(p.nodeId) ?? str(p.node_id) ?? "planner";
      const node = s.nodes.find((n) => n.id === nodeId) ?? s.nodes.find((n) => n.id === "planner");
      if (!node) return "Unknown playbook step.";
      const paramKey = str(p.paramKey) ?? str(p.param_key);
      const param = paramKey ? node.params.find((x) => x.key === paramKey) : undefined;
      const ref = currentCase() ?? SHOWCASE;
      const round = num(p.round);
      const id = studio.propose({
        nodeId: node.id,
        paramKey: param?.key,
        title: str(p.title) ?? "Playbook change",
        rationale: str(p.rationale) ?? "",
        before: param ? formatValue(param) : (str(p.before) ?? ""),
        after: str(p.after) ?? "",
        evidence: { runId: ref.runId, caseId: ref.caseId, round, quote: str(p.quote) },
        source: "voice",
      });
      emit("tool", `Proposed change → ${node.title}`);
      emit("toast", "Suggestion sent to Agent Studio");
      return `Queued as suggestion ${id} on "${node.title}" for the procurement manager to accept or reject in Agent Studio. It is not live yet.`;
    },

    async show(p) {
      const view = str(p.view);
      const round = num(p.round);
      const supplier = str(p.supplier);
      if (view === "studio" || view === "playbook") {
        const node = str(p.nodeId) ?? str(p.node_id);
        window.location.hash = node && NODE_IDS.includes(node) ? `#/studio/${node}` : "#/studio";
        emit("tool", "Opening Agent Studio");
        return "Agent Studio is open.";
      }
      const ref = currentCase() ?? SHOWCASE;
      if (!window.location.hash.startsWith("#/n/") || view === "negotiation")
        window.location.hash = `#/n/${encodeURIComponent(ref.runId)}/${encodeURIComponent(ref.caseId)}${round ? `?round=${round}` : ""}`;
      show({ round, supplier });
      emit("tool", round ? `Showing round ${round}` : "Showing the negotiation");
      return "Shown on screen.";
    },
  };
}

// ---------------------------------------------------------------------------------------------------
// offline demo: a scripted conversation over the showcase, voiced by pre-generated ElevenLabs audio

export interface DemoLine {
  role: "agent" | "user";
  text: string;
  audio?: string; // /voice/<file>.mp3
  tool?: { name: string; params: P };
}
export interface DemoScript {
  case: CaseRef;
  lines: DemoLine[];
}

export async function loadDemo(): Promise<DemoScript | null> {
  try {
    const r = await fetch("/voice/demo.json");
    return r.ok ? ((await r.json()) as DemoScript) : null;
  } catch {
    return null;
  }
}
