// The voice copilot's brain on the browser side: which negotiation is open, the debrief text (built by
// code, never by the LLM), and the client tools the ElevenLabs agent calls. Every number it says comes
// from these tools, which read the run log and the supplier data through the local API. Each tool also
// emits a visual card for the dock, so the numbers are seen, not only heard.
import { buildModel, type CaseModel, type Thread } from "./model";
import { studio, formatValue } from "./studio";
import type { BaseEvent, Priced } from "./types";

export interface CaseRef {
  runId: string;
  caseId: string;
}

// The pitch's showcase negotiation (P01 Brandlhuber): the fallback when no case is open
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
// visual cards: what a tool found, drawn in the dock's transcript

export type Tone = "deal" | "better" | "worse" | "neutral";
export interface Bar {
  label: string;
  eur: number;
  tone: Tone;
}
export interface TermDelta {
  term: string;
  eur: number; // + = costs us more
}
export type Card =
  | { kind: "verdict"; title: string; supplier: string; saved: number | null; askPct: number | null; dealPct: number | null; bars: Bar[]; deal: boolean; rounds: number }
  | { kind: "money"; headline: string; bars: Bar[]; terms: TermDelta[]; findings: string[] }
  | {
      kind: "round";
      round: number;
      supplier: string;
      ourEur: number | null;
      ourMove: number | null;
      theirEur: number | null;
      theirMove: number | null;
      status?: string;
      claims: { text: string; result: string }[];
      quote?: string;
    }
  | { kind: "breakdown"; what: string; total: number | null; terms: TermDelta[] }
  | { kind: "supplier"; name: string; chips: string[]; facts: { label: string; value: string }[] }
  | { kind: "history"; supplier: string; rows: { date: string; label: string; asked: number | null; settled: number | null }[]; category: string | null; catSettled: number[]; thisCase?: { asked: number | null; settled: number | null } }
  | { kind: "proposal"; title: string; node: string; before: string; after: string; evidence: string };

export function onShow(round?: number, supplier?: string) {
  window.dispatchEvent(new CustomEvent("copilot:show", { detail: { round, supplier } }));
}

// ---------------------------------------------------------------------------------------------------
// activity bus: tool chips, toasts and cards for the dock

export type Activity = { id: number; kind: "tool" | "toast"; text: string } | { id: number; kind: "card"; card: Card; text: string };
const activityListeners = new Set<(a: Activity) => void>();
let activitySeq = 0;
export function onActivity(fn: (a: Activity) => void) {
  activityListeners.add(fn);
  return () => {
    activityListeners.delete(fn);
  };
}
export function emit(kind: "tool" | "toast", text: string) {
  const a: Activity = { id: ++activitySeq, kind, text };
  activityListeners.forEach((fn) => fn(a));
}
function card(c: Card) {
  const a: Activity = { id: ++activitySeq, kind: "card", card: c, text: c.kind };
  activityListeners.forEach((fn) => fn(a));
}

// ---------------------------------------------------------------------------------------------------
// data: the run log and the supplier knowledge

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

type Json = Record<string, unknown>;
const getJson = new Map<string, Promise<Json | null>>();
function fetchJson(url: string): Promise<Json | null> {
  let p = getJson.get(url);
  if (!p) {
    p = fetch(url)
      .then((r) => (r.ok ? (r.json() as Promise<Json>) : null))
      .catch(() => null);
    getJson.set(url, p);
  }
  return p;
}
export const supplierData = (sid: string) => fetchJson(`/api/voice/supplier/${encodeURIComponent(sid)}`);
const historyData = (sid: string) => fetchJson(`/api/voice/history/${encodeURIComponent(sid)}`);

const r0 = (n: number | null | undefined) => (typeof n === "number" ? Math.round(n) : null);
const isNum = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);
const speakEur = (n: number) => `€${Math.round(n).toLocaleString("en-US")}`;
const last = <T,>(xs: T[]): T | undefined => xs[xs.length - 1];
const shortCase = (id: string) => id.replace(/^case:/, "");
const pct1 = (x: number | null) => (x === null ? null : Math.round(x * 1000) / 10);

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

/** The outcome in product terms (no arena score: a real buyer has no "best possible" reference). */
export function metrics(m: CaseModel) {
  const r = m.result;
  const buyer = (m.caseFile?.buyer ?? {}) as Json;
  const cur = buyer.current_unit_price;
  const t = dealThread(m);
  const openTerms = t?.standing[0]?.priced?.terms;
  const pct = (p: unknown) => (isNum(cur) && isNum(p) && cur ? (p - cur) / cur : null);
  const deal = !!r?.deal;
  const askPct = pct(openTerms?.unit_price);
  const dealPct = deal ? pct(r?.terms?.unit_price) : null;
  return {
    deal,
    supplier: t?.short ?? "the supplier",
    supplierId: t?.sid,
    rounds: m.maxRound,
    unitPrice: isNum(r?.terms?.unit_price) ? (r!.terms!.unit_price as number) : null,
    currentUnitPrice: isNum(cur) ? cur : null,
    costOpen: r?.c_open ?? m.cOpen,
    costDeal: deal ? (r?.c_deal ?? null) : null,
    costAlt: r?.c_alt ?? m.cAlt,
    saved: deal && isNum(r?.c_open) && isNum(r?.c_deal) ? r!.c_open! - r!.c_deal! : null,
    vsAlternative: deal && isNum(r?.c_alt) && isNum(r?.c_deal) ? r!.c_alt! - r!.c_deal! : null,
    askPct,
    dealPct,
    avertedPts: askPct !== null && dealPct !== null ? askPct - dealPct : null,
  };
}

/** The spoken opening: ~20 s, every figure from the log. */
export function buildDebrief(m: CaseModel): string {
  const x = metrics(m);
  const res = m.result;
  const parts: string[] = [];
  if (x.deal && x.saved !== null) {
    const price = x.unitPrice !== null ? `€${x.unitPrice.toFixed(2)} per unit` : "the agreed terms";
    const from = fmtDate(res?.terms?.effective_date);
    parts.push(`${shortCase(m.caseId)}, ${x.supplier}: we closed in ${x.rounds} rounds at ${price}${from ? ` from ${from}` : ""}.`);
    if (x.askPct !== null && x.dealPct !== null && x.askPct > 0)
      parts.push(`They asked for ${pct1(x.askPct)} percent more, we settled at ${pct1(x.dealPct)} percent.`);
    parts.push(`That is ${speakEur(x.saved)} below their opening offer${x.vsAlternative && x.vsAlternative > 0 ? ` and ${speakEur(x.vsAlternative)} below our alternative supplier` : ""}.`);
  } else if (res) {
    parts.push(`${shortCase(m.caseId)}, ${x.supplier}: no deal, the negotiation ended with ${String(res.end_reason ?? "no agreement").replace(/_/g, " ")}.`);
  } else {
    parts.push(`${shortCase(m.caseId)} with ${x.supplier} is still running, round ${m.maxRound} so far.`);
  }
  const verified = claimStats(m).filter((c) => c.result === "verified");
  if (verified.length) {
    const topics = [...new Set(verified.map((c) => claimTopic(c.text)))].slice(0, 3);
    parts.push(`${verified.length === 1 ? "One of our arguments was" : `${verified.length} of our arguments were`} verified by the supplier: ${topics.join(", ")}.`);
  }
  parts.push("Ask me why we did anything, where we left money, or what I would change.");
  return parts.join(" ");
}

// the arena's briefing explains its scoring; the copilot talks money, not scores
const briefing = (b: unknown) => (typeof b === "string" ? b.replace(/\s*Score:[^.]*\./, "") : undefined);

/** Compact context for the agent's prompt (a dynamic variable): the case, the outcome and who the supplier is. */
export async function buildContext(m: CaseModel): Promise<string> {
  const x = metrics(m);
  const cf = m.caseFile ?? {};
  const lines = [`Case ${m.caseId} (${m.type ?? "?"}): ${m.title}.`];
  if (typeof cf.briefing === "string") lines.push(`Briefing: ${(briefing(cf.briefing) ?? "").slice(0, 900)}`);
  for (const t of m.threads) {
    lines.push(`Supplier ${t.name} [${t.sid}]: ${t.rounds.length} rounds, last status ${t.status}, opening offer cost €${r0(t.standing[0]?.c)}.`);
    const d = await supplierData(t.sid);
    const p = (d?.profile ?? {}) as Json;
    if (typeof p.situation === "string") lines.push(`  Situation: ${p.situation}`);
    const pressures = Array.isArray(p.pressures) ? (p.pressures as Json[]).map((q) => `${q.type}: ${q.evidence}`).join("; ") : "";
    if (pressures) lines.push(`  Pressures: ${pressures}`);
  }
  if (m.result)
    lines.push(
      `Outcome: deal=${x.deal}, unit price ${x.unitPrice ?? "-"} (today ${x.currentUnitPrice ?? "-"}), saved vs opening €${r0(x.saved)}, ` +
        `asked +${pct1(x.askPct)} %, settled +${pct1(x.dealPct)} %, vs alternative supplier €${r0(x.vsAlternative)}, end ${m.result.end_reason}.`,
    );
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
const TERM_LABEL: Record<string, string> = {
  price: "Price",
  payment_terms: "Payment terms",
  freight: "Freight",
  quality: "Quality",
  relationship: "Relationship",
  late_delivery: "Lead time",
  tooling: "Tooling",
  index_clause: "Index clause",
  index_risk: "Index risk",
  fallback_risk: "Supply risk",
  uncovered_need: "Uncovered volume",
};
const termLabel = (k: string) => TERM_LABEL[k] ?? k.replace(/_/g, " ");

function termDeltas(a: Record<string, number> | null | undefined, b: Record<string, number> | null | undefined): TermDelta[] {
  if (!a || !b) return [];
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  return [...keys]
    .map((k) => ({ term: termLabel(k), eur: (a[k] ?? 0) - (b[k] ?? 0) }))
    .filter((d) => Math.abs(d.eur) >= 1)
    .sort((x, y) => Math.abs(y.eur) - Math.abs(x.eur))
    .slice(0, 5);
}

async function needCase(): Promise<[CaseRef, CaseModel]> {
  const ref = currentCase() ?? SHOWCASE;
  return [ref, await loadCase(ref)];
}

/** Our move and theirs per round on one thread (€ of total cost; + = towards the other side). */
function pace(t: Thread) {
  const out: { round: number; ours: number | null; theirs: number | null; accepting: boolean }[] = [];
  for (const rd of t.rounds) {
    if (rd.round < 1) continue;
    const ask = t.asks.find((a) => a.round === rd.round)?.c;
    const prevAsk = last(t.asks.filter((a) => a.round < rd.round))?.c;
    const stand = rd.reply?.standing?.priced?.c;
    const prevStand = last(t.standing.filter((s) => s.round < rd.round))?.c;
    out.push({
      round: rd.round,
      ours: isNum(ask) && isNum(prevAsk) ? ask - prevAsk : null, // our ask's cost going up = we give
      accepting: isNum(ask) && isNum(prevStand) && ask >= prevStand * 0.998, // we (nearly) met their standing offer: closing, not conceding
      theirs: isNum(stand) && isNum(prevStand) ? prevStand - stand : null, // their offer's cost going down = they give
    });
  }
  return out;
}

// which term a supplier pressure is traded with
const PRESSURE_TERM: Record<string, { term: string; label: string }> = {
  cash: { term: "payment_days", label: "faster payment" },
  volume: { term: "volume_per_year", label: "volume" },
  utilisation: { term: "volume_per_year", label: "volume" },
  capacity: { term: "lead_time_days", label: "lead time" },
  planning: { term: "contract_months", label: "contract length" },
};

export function makeClientTools(): Record<string, (p: P) => Promise<string>> {
  return {
    async get_case_summary() {
      emit("tool", "Reading the case");
      const [ref, m] = await needCase();
      const x = metrics(m);
      const r = m.result;
      const bars: Bar[] = [];
      if (isNum(x.costOpen)) bars.push({ label: "Their opening", eur: x.costOpen, tone: "worse" });
      if (isNum(x.costAlt)) bars.push({ label: "Alternative supplier", eur: x.costAlt, tone: "neutral" });
      if (isNum(x.costDeal)) bars.push({ label: "Our deal", eur: x.costDeal, tone: "deal" });
      card({ kind: "verdict", title: m.title, supplier: x.supplier, saved: x.saved, askPct: x.askPct, dealPct: x.dealPct, bars, deal: x.deal, rounds: x.rounds });
      return json({
        case: ref.caseId,
        title: m.title,
        type: m.type,
        briefing: cut(briefing(m.caseFile?.briefing), 1200),
        our_requirements: m.caseFile?.buyer,
        rounds: m.maxRound,
        suppliers: m.threads.map((t) => ({
          name: t.name,
          id: t.sid,
          status: t.status,
          rounds: t.rounds.length,
          opening_cost_eur: r0(t.standing[0]?.c),
          opening_terms: t.standing[0]?.priced?.terms,
          last_offer_cost_eur: r0(t.current?.c),
        })),
        outcome: r && {
          deal: r.deal,
          terms: r.terms,
          unit_price_today: x.currentUnitPrice,
          increase_asked_pct: pct1(x.askPct),
          increase_settled_pct: pct1(x.dealPct),
          increase_averted_points: pct1(x.avertedPts),
          cost_their_opening_eur: r0(x.costOpen),
          cost_our_deal_eur: r0(x.costDeal),
          cost_alternative_supplier_eur: r0(x.costAlt),
          saved_vs_opening_eur: r0(x.saved),
          below_alternative_eur: r0(x.vsAlternative),
          end_reason: r.end_reason,
        },
        arguments: claimStats(m),
        note: "cost_* = total cost of ownership over the contract in EUR (lower is better for us).",
      });
    },

    async get_round(p) {
      const [, m] = await needCase();
      const t = findThread(m, str(p.supplier));
      if (!t) return "No supplier thread in this case.";
      const round = num(p.round) ?? t.rounds.length;
      const rd = t.rounds.find((x) => x.round === round);
      emit("tool", `Looking at round ${round}${m.threads.length > 1 ? ` · ${t.short}` : ""}`);
      onShow(round, t.sid);
      if (!rd) return `No round ${round} with ${t.short}; it has rounds 1 to ${t.rounds.length}.`;
      const claims = rd.message?.claims ?? [];
      const mv = pace(t).find((x) => x.round === round);
      const ask = t.asks.find((a) => a.round === round)?.c ?? null;
      const standing = rd.reply?.standing?.priced?.c ?? null;
      const args = claims.map((c, i) => ({ text: c.text, result: rd.reply?.claim_results?.find((x) => x.index === i)?.result ?? "not checked" }));
      const quote = rd.reply?.body
        ?.split(/(?<=[.!?])\s+|\n+/)
        .map((s) => s.trim())
        .find((s) => s.length > 25 && s.length < 160 && !/\.\.\.|…/.test(s) && !/^(guten|dear|hello|sehr|best|viele|kind|mit freund)/i.test(s));
      card({ kind: "round", round, supplier: t.short, ourEur: ask, ourMove: mv?.ours ?? null, theirEur: standing, theirMove: mv?.theirs ?? null, status: rd.reply?.status, claims: args.map((a) => ({ text: claimTopic(a.text), result: a.result })), quote });
      return json({
        supplier: t.name,
        round,
        our_email: rd.message && {
          subject: rd.message.subject,
          body: cut(rd.message.body, 2500),
          offers: (rd.message.sheets ?? []).map((s) => ({ cost_eur: r0(s.c), terms: s.terms })),
          arguments: args,
        },
        our_cheapest_offer_cost_eur: r0(ask),
        we_gave_vs_previous_round_eur: r0(mv?.ours),
        decision: rd.decision && { kind: rd.decision.kind, reason: rd.decision.reason },
        planner_options: (rd.plan?.candidates ?? []).slice(0, 4).map((c) => ({ id: c.id, label: c.label, rationale: cut(c.rationale, 300) })),
        planner_walk_away_cost_eur: r0(rd.plan?.walk_away_c),
        supplier_reply: rd.reply && {
          status: rd.reply.status,
          body: cut(rd.reply.body, 2500),
          reasons: rd.reply.reasons,
          standing_offer_cost_eur: r0(standing),
          standing_offer_terms: rd.reply.standing?.priced?.terms,
          they_gave_vs_previous_eur: r0(mv?.theirs),
          other_offers: (rd.reply.alternatives ?? []).map((a) => ({ cost_eur: r0(a.priced?.c), terms: a.priced?.terms })),
        },
        supplier_internal_notes: rd.backoffice.map((b) => `${b.from ?? "?"}: ${b.text}`),
      });
    },

    async get_cost_breakdown(p) {
      const [, m] = await needCase();
      const round = num(p.round);
      if (round === undefined && m.result?.cost_breakdown) {
        emit("tool", "Pricing the deal term by term");
        const terms = Object.entries(m.result.cost_breakdown)
          .filter(([k, v]) => k !== "price" && Math.abs(v) >= 1)
          .map(([k, v]) => ({ term: termLabel(k), eur: v }))
          .sort((a, b) => b.eur - a.eur);
        card({ kind: "breakdown", what: "The deal, besides the price", total: m.result.c_deal ?? null, terms });
        return json({ what: "the final deal", total_eur: r0(m.result.c_deal), by_term_eur: m.result.cost_breakdown });
      }
      const t = findThread(m, str(p.supplier));
      const pt = last(t?.standing.filter((s) => round === undefined || s.round <= round) ?? []);
      emit("tool", `Pricing ${t?.short ?? "the offer"}${round !== undefined ? ` · round ${round}` : ""}`);
      if (!pt) return "No priced offer found.";
      const open = t?.standing[0];
      card({ kind: "breakdown", what: `${t?.short} offer after round ${pt.round} vs their opening`, total: pt.c, terms: termDeltas(pt.priced.breakdown, open?.priced.breakdown) });
      return json({ what: `${t?.name} standing offer after round ${pt.round}`, total_eur: r0(pt.c), by_term_eur: pt.priced.breakdown, terms: pt.priced.terms });
    },

    async get_supplier(p) {
      const [, m] = await needCase();
      const t = findThread(m, str(p.supplier));
      if (!t) return "No such supplier in this case.";
      emit("tool", `Opening the supplier file · ${t.short}`);
      const d = await supplierData(t.sid);
      const prof = (d?.profile ?? {}) as Json;
      const fin = (prof.financial_health ?? {}) as Json;
      const q = (prof.quality ?? {}) as Json;
      const chips = [
        ...(Array.isArray(prof.pressures) ? (prof.pressures as Json[]).filter((x) => x.type !== "other").map((x) => `${x.type} pressure`) : []),
        prof.owner_type ? `${prof.owner_type} owned` : null,
        prof.our_share_of_their_turnover_pct ? `we are ${prof.our_share_of_their_turnover_pct} % of their turnover` : null,
      ].filter(Boolean) as string[];
      const facts = [
        { label: "Equity ratio", value: fin.equity_ratio_pct != null ? `${fin.equity_ratio_pct} %` : "–" },
        { label: "Quality", value: q.ppm != null ? `${q.ppm} ppm · ${q.colour ?? ""}` : "–" },
        { label: "On time", value: q.otd_pct != null ? `${q.otd_pct} %` : "–" },
        { label: "Letters & notes", value: String((d?.correspondence as unknown[] | undefined)?.length ?? 0) },
      ];
      card({ kind: "supplier", name: t.name, chips: chips.slice(0, 5), facts });
      if (!d) return json({ name: t.name, id: t.sid, note: "No supplier data found beyond the negotiation log.", dossier: t.dossier });
      return json({ ...d, dossier_from_run: t.dossier, opening_quote: t.opening?.priced && { cost_eur: r0(t.opening.priced.c), terms: t.opening.priced.terms } });
    },

    async find_missed_value() {
      emit("tool", "Looking for money left on the table");
      const [, m] = await needCase();
      const x = metrics(m);
      const t = dealThread(m);
      const findings: string[] = [];
      const out: Json = { deal: x.deal };
      if (!t) return "No supplier thread in this case.";
      const dealSheet = x.deal ? t.current : last(t.standing);
      const dealC = dealSheet?.c ?? null;

      // 1. offers on the table that were cheaper than what we took
      const cheaper: { supplier: string; round: number; priced: Priced; gap: number }[] = [];
      const seen = new Set<string>();
      if (isNum(dealC))
        for (const th of m.threads) {
          const add = (round: number, priced?: Priced) => {
            if (!priced || !isNum(priced.c) || priced.c >= dealC - 1) return;
            const k = th.sid + JSON.stringify(priced.terms);
            if (seen.has(k)) return;
            seen.add(k);
            cheaper.push({ supplier: th.short, round, priced, gap: dealC - priced.c });
          };
          th.standing.forEach((s) => add(s.round, s.priced));
          th.rounds.forEach((rd) => (rd.reply?.alternatives ?? []).forEach((a) => add(rd.round, a.priced)));
        }
      cheaper.sort((a, b) => b.gap - a.gap);
      out.cheaper_offers_we_did_not_take = cheaper.slice(0, 3).map((c) => ({ supplier: c.supplier, round: c.round, cheaper_by_eur: r0(c.gap), terms: c.priced.terms }));
      if (cheaper[0]) findings.push(`${cheaper[0].supplier} offered a sheet €${Math.round(cheaper[0].gap).toLocaleString("en-US")} cheaper in round ${cheaper[0].round}`);

      // 2. concession pace: rounds where we gave more than they did, and pull-backs
      const steps = pace(t);
      const outPaced = steps.filter((s) => !s.accepting && isNum(s.ours) && s.ours > 1000 && isNum(s.theirs) && s.ours > Math.max(s.theirs, 0) * 1.5);
      const pullbacks = steps.filter((s) => isNum(s.ours) && s.ours < -1);
      out.concession_pace = steps.map((s) => ({ round: s.round, we_gave_eur: r0(s.ours), they_gave_eur: r0(s.theirs), we_accepted_their_offer: s.accepting || undefined }));
      out.rounds_we_out_conceded_them = outPaced.map((s) => s.round);
      out.rounds_we_pulled_back = pullbacks.map((s) => ({ round: s.round, eur: r0(-(s.ours ?? 0)) }));
      for (const s of outPaced.slice(0, 2))
        findings.push(`Round ${s.round}: we gave €${Math.round(s.ours!).toLocaleString("en-US")}, they gave €${Math.round(Math.max(s.theirs ?? 0, 0)).toLocaleString("en-US")}`);
      for (const s of pullbacks.slice(0, 1)) findings.push(`Round ${s.round}: we pulled back €${Math.round(-s.ours!).toLocaleString("en-US")}`);

      // 3. arguments that did not land
      const weak = claimStats(m).filter((c) => c.result !== "verified");
      out.arguments_not_verified = weak;
      if (weak.length) findings.push(`${weak.length} argument${weak.length > 1 ? "s" : ""} not verified (${[...new Set(weak.map((w) => w.result))].join(", ")})`);

      // 4. supplier pressures we never traded on
      const d = t ? await supplierData(t.sid) : null;
      const prof = (d?.profile ?? {}) as Json;
      const pressures = Array.isArray(prof.pressures) ? (prof.pressures as Json[]) : [];
      const open = t.standing[0]?.priced?.terms ?? {};
      const varied = (term: string) => t.rounds.some((rd) => (rd.message?.sheets ?? []).some((s) => s.terms?.[term] !== undefined && s.terms[term] !== open[term]));
      const untraded = pressures
        .map((q) => ({ pressure: String(q.type), evidence: q.evidence, lever: PRESSURE_TERM[String(q.type)] }))
        .filter((q) => q.lever && !varied(q.lever.term));
      out.supplier_pressures = pressures;
      out.pressures_we_never_traded_on = untraded.map((u) => ({ pressure: u.pressure, lever: u.lever!.label, evidence: u.evidence }));
      for (const u of untraded.slice(0, 1)) findings.push(`${u.pressure} pressure known, ${u.lever!.label} never offered`);

      // 5. against their own cost (should-cost of the part)
      const parts = Array.isArray(prof.parts) ? (prof.parts as Json[]) : [];
      const casePart = (m.caseFile?.parts as Json[] | string[] | undefined)?.[0];
      const pid = typeof casePart === "string" ? casePart : (casePart as Json | undefined)?.part_id;
      const part = parts.find((pp) => pp.part_id === pid) ?? parts[0];
      if (part && isNum(part.should_cost_unit) && x.unitPrice !== null) {
        out.unit_price_vs_their_estimated_cost = { unit_price: x.unitPrice, should_cost_unit: part.should_cost_unit, margin_pct: pct1((x.unitPrice - (part.should_cost_unit as number)) / (part.should_cost_unit as number)) };
      }

      const bars: Bar[] = [];
      if (isNum(x.costOpen)) bars.push({ label: "Their opening", eur: x.costOpen, tone: "worse" });
      // the deal at its full cost (as on the outcome card); the cheaper sheet the same gap below it
      const shownDeal = isNum(x.costDeal) ? x.costDeal : dealC;
      if (isNum(shownDeal)) bars.push({ label: x.deal ? "Our deal" : "Last offer", eur: shownDeal, tone: "deal" });
      if (cheaper[0] && isNum(shownDeal)) bars.push({ label: `Cheaper sheet · R${cheaper[0].round}`, eur: shownDeal - cheaper[0].gap, tone: "better" });
      const terms = cheaper[0] ? termDeltas(dealSheet?.priced.breakdown, cheaper[0].priced.breakdown) : [];
      const gap = cheaper[0]?.gap ?? null;
      card({ kind: "money", headline: gap ? `€${Math.round(gap).toLocaleString("en-US")} on the table` : findings.length ? "Where we could do better" : "Nothing obvious left", bars, terms, findings: findings.slice(0, 4) });
      out.note = "Computed by code from this negotiation's log and the supplier data. EUR = total cost over the contract.";
      return json(out);
    },

    async comparable_deals() {
      emit("tool", "Comparing with past deals");
      const [, m] = await needCase();
      const t = dealThread(m);
      if (!t) return "No supplier in this case.";
      const h = (await historyData(t.sid)) as { category?: string | null; with_this_supplier?: Json[]; same_category_other_suppliers?: Json[] } | null;
      const x = metrics(m);
      const rows = (h?.with_this_supplier ?? [])
        .filter((r) => r.settled_pct != null)
        .map((r) => ({ date: String(r.date ?? ""), label: String(r.type ?? ""), asked: (r.asked_pct as number) ?? null, settled: r.settled_pct as number }));
      const cat = (h?.same_category_other_suppliers ?? []).map((r) => r.settled_pct as number).filter(isNum);
      card({ kind: "history", supplier: t.short, rows: rows.slice(-6), category: h?.category ?? null, catSettled: cat, thisCase: { asked: pct1(x.askPct), settled: pct1(x.dealPct) } });
      return json({
        this_negotiation: { increase_asked_pct: pct1(x.askPct), increase_settled_pct: pct1(x.dealPct) },
        past_negotiations_with_this_supplier: h?.with_this_supplier ?? [],
        same_category_other_suppliers: h?.same_category_other_suppliers ?? [],
        note: "From the ERP's negotiation history (data package). Percent = price change asked and settled.",
      });
    },

    async get_portfolio() {
      emit("tool", "Scanning all negotiations");
      const runs = (await fetch("/api/runs").then((r) => r.json())) as {
        runs: { run_id: string; set?: string; case_summaries?: { case_id: string; type: string | null; deal: boolean | null; saved: number | null; c_open: number | null; end_reason: string | null }[] }[];
      };
      const rows = runs.runs.flatMap((r) => (r.case_summaries ?? []).map((c) => ({ run: r.run_id, ...c, saved_pct: isNum(c.saved) && isNum(c.c_open) && c.c_open ? (c.saved / c.c_open) * 100 : null })));
      const byType = new Map<string, { n: number; saved: number; pctSum: number; pctN: number; noDeal: number }>();
      for (const c of rows) {
        const k = c.type ?? "unknown";
        const b = byType.get(k) ?? { n: 0, saved: 0, pctSum: 0, pctN: 0, noDeal: 0 };
        b.n += 1;
        b.saved += c.saved ?? 0;
        if (isNum(c.saved_pct)) {
          b.pctSum += c.saved_pct;
          b.pctN += 1;
        }
        if (c.deal === false) b.noDeal += 1;
        byType.set(k, b);
      }
      return json({
        negotiations: rows.length,
        by_case_type: [...byType].map(([type, b]) => ({ type, negotiations: b.n, mean_saved_vs_opening_pct: b.pctN ? b.pctSum / b.pctN : null, no_deal: b.noDeal })),
        weakest_saved_pct: rows.filter((c) => c.saved_pct !== null).sort((a, b) => (a.saved_pct ?? 0) - (b.saved_pct ?? 0)).slice(0, 5),
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
      const evidenceKind: "this_negotiation" | "comparable_deals" = str(p.evidenceKind) === "comparable_deals" ? "comparable_deals" : "this_negotiation";
      const proposal = {
        nodeId: node.id,
        paramKey: param?.key,
        title: str(p.title) ?? "Playbook change",
        rationale: str(p.rationale) ?? "",
        before: param ? formatValue(param) : (str(p.before) ?? ""),
        after: str(p.after) ?? "",
        evidence: { runId: ref.runId, caseId: ref.caseId, round, quote: str(p.quote) },
        source: "voice" as const,
        evidenceKind,
      };
      const id = studio.propose(proposal);
      card({
        kind: "proposal",
        title: proposal.title,
        node: node.title,
        before: proposal.before,
        after: proposal.after,
        evidence: `${evidenceKind === "comparable_deals" ? "Comparable deals" : "This negotiation"} · ${shortCase(ref.caseId)}${round ? ` · round ${round}` : ""}`,
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
      onShow(round, supplier);
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
