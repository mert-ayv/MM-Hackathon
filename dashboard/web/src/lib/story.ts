// Story layer for the negotiation views: turns the case model into short, visual facts.
// Every number comes from the logged events (priced sheets, results); nothing is estimated here.
import type { CaseModel, RoundData, Thread } from "./model";
import { sentClaims } from "./model";
import type { Priced, Terms } from "./types";
import { eur2, termLabel, termValue } from "./format";

const isNum = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);

export type MoveKind = "anchor" | "concede" | "hold" | "trade" | "accept" | "walk" | "push";

export interface Chip {
  icon: string;
  label: string;
  detail?: string;
  tone?: "ink" | "accent" | "muted" | "good" | "bad";
}

export interface ClaimChip {
  label: string;
  value?: string;
  result?: string;
}

export interface RoundStory {
  round: number;
  sid: string;
  move: MoveKind;
  moveLabel: string;
  ourBest: number | null; // our cheapest sheet's C this round
  sheets: Priced[];
  chosen?: number; // index of the sheet the supplier answered closest to
  claims: ClaimChip[];
  reason?: string; // planner/strategist reason, one line
  supplierStatus?: string;
  supplierBefore: number | null;
  supplierAfter: number | null;
  supplierStep: number | null; // € the supplier came down this round (positive = good for us)
  supplierStepPct: number | null;
  mood: "moved" | "small" | "held" | "final" | "agreed" | "walked" | "none";
  reasons: string[]; // the supplier's own reasons, one-liners
  mind: string[]; // back-office "my call" notes
  alternatives: Priced[];
  emailOut?: string;
  emailIn?: string;
}

/** One line on why this round looks the way it does, built from logged numbers only. */
export function whyLine(s: RoundStory): string {
  const parts: string[] = [];
  if (s.move === "accept") parts.push("Took the supplier's offer");
  else if (s.move === "walk") parts.push("Walked away");
  else if (s.sheets.length > 1) parts.push(`${s.sheets.length} packages to choose from`);
  else if (s.sheets.length === 1) parts.push("One package");
  if (isNum(s.ourBest) && isNum(s.supplierBefore) && s.move !== "accept") {
    const gap = (s.supplierBefore - s.ourBest) / s.supplierBefore;
    if (gap > 0.0005) parts.push(`asking ${(gap * 100).toFixed(1)} % below their offer`);
  }
  const facts = s.claims.length;
  if (facts) parts.push(`${facts} fact${facts > 1 ? "s" : ""} cited`);
  return parts.join(" · ");
}

/** "Gießerei Brandlhuber GmbH & Co. KG" -> "Gießerei Brandlhuber" */
export function plainName(name: string): string {
  return name.replace(/\s+(GmbH|AG|KG|SE|Ltd\.?|Sp\. z o\.o\.|s\.r\.o\.|a\.s\.|A\.Ş\.|Kft\.)(\s|$).*$/i, "").trim() || name;
}

/** Display names that stay distinct when two suppliers shorten to the same word. */
export function threadLabels(threads: Thread[]): Map<string, string> {
  const count = new Map<string, number>();
  threads.forEach((t) => count.set(t.short, (count.get(t.short) ?? 0) + 1));
  return new Map(
    threads.map((t) => [
      t.sid,
      (count.get(t.short) ?? 0) > 1
        ? plainName(t.name)
        : t.short,
    ]),
  );
}

/** The planner's logged reason, split into short pieces ("anchor 9% below its opening 32.20; ..."). */
export function reasonParts(r: string | undefined): string[] {
  if (!r) return [];
  return r
    .split(/;\s+/)
    .map((x) => x.trim())
    .filter(Boolean)
    .slice(0, 5);
}

export function claimChip(text: string): ClaimChip {
  // "notice period: doc:..., ctr:... (days 51.0)" -> {label: "notice period", value: "days 51"}
  const m = text.match(/^([^:]+):.*?(?:\(([^)]*)\))?\s*$/);
  if (!m) return { label: text.slice(0, 40) };
  const value = m[2]?.replace(/(\d+)\.0\b/g, "$1").replace(/_/g, " ");
  return { label: m[1].trim(), value };
}

function cleanReason(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

const BOILER = /^(we have reviewed|guten tag|thank you|it is always a pleasure|we appreciate)/i;

export function roundStories(t: Thread): RoundStory[] {
  const out: RoundStory[] = [];
  let prevAsk: number | null = null;
  for (const rd of t.rounds) {
    if (!rd.message && !rd.decision && !rd.reply) continue;
    const sheets = rd.message?.sheets ?? [];
    const cs = sheets.map((s) => s?.c).filter(isNum);
    const ourBest = cs.length ? Math.min(...cs) : null;
    const before = [...t.standing].filter((s) => s.round < rd.round).pop()?.c ?? null;
    const afterPt = t.standing.find((s) => s.round === rd.round);
    const after = afterPt?.c ?? null;
    const step = isNum(before) && isNum(after) ? before - after : null;
    const stepPct = isNum(step) && isNum(before) && before ? step / before : null;

    const d = rd.decision;
    let move: MoveKind = "concede";
    if (d?.kind === "accept") move = "accept";
    else if (d?.kind === "walk_away") move = "walk";
    else if (rd.round === 1 || prevAsk === null) move = "anchor";
    else if (isNum(ourBest) && isNum(prevAsk) && Math.abs(ourBest - prevAsk) / prevAsk < 0.0015) move = "hold";
    else if (isNum(ourBest) && isNum(prevAsk) && ourBest < prevAsk) move = "push";
    if (move === "concede" || move === "anchor") {
      if (sheets.length > 1 && distinctNonPrice(sheets)) move = move === "anchor" ? "anchor" : "trade";
    }
    // a message that accepts a supplier sheet (single sheet equal to a standing/alternative offer)
    if (rd.message && sheets.length === 1 && /we accept your (\w+ )?offer/i.test(rd.message.body ?? "")) move = "accept";
    if (isNum(ourBest)) prevAsk = ourBest;
    if (move === "accept" && !rd.message && out[out.length - 1]?.move === "accept") continue;

    const results = rd.reply?.claim_results ?? [];
    const claims = sentClaims(rd).map((c, i) => ({
      ...claimChip(c.text),
      result: results.find((r) => r.index === i)?.result,
    }));

    const status = rd.reply?.status;
    let mood: RoundStory["mood"] = "none";
    if (status === "agreed") mood = "agreed";
    else if (status === "walked_away" || status === "no_bid") mood = "walked";
    else if (status === "final_offer") mood = "final";
    else if (isNum(stepPct)) mood = stepPct > 0.004 ? "moved" : stepPct > 0.0005 ? "small" : "held";

    const reasons = (rd.reply?.reasons ?? [])
      .map(cleanReason)
      .filter((s) => s && !BOILER.test(s))
      .filter((s) => !/^We checked the .* data you cited/i.test(s)); // shown as claim badges instead
    const mind = rd.backoffice
      .map((b) => b.text ?? "")
      .map((s) => s.match(/My call:\s*([^.]+)/i)?.[1] ?? "")
      .filter(Boolean);

    out.push({
      round: rd.round,
      sid: t.sid,
      move,
      moveLabel: MOVE_LABEL[move],
      ourBest,
      sheets,
      chosen: closestSheet(sheets, afterPt?.priced?.terms),
      claims,
      reason: planReason(rd),
      supplierStatus: status,
      supplierBefore: before,
      supplierAfter: after,
      supplierStep: step,
      supplierStepPct: stepPct,
      mood,
      reasons,
      mind,
      alternatives: (rd.reply?.alternatives ?? []).map((a) => a.priced).filter((p): p is Priced => !!p),
      emailOut: rd.message?.body,
      emailIn: rd.reply?.body,
    });
  }
  return out;
}

export const MOVE_LABEL: Record<MoveKind, string> = {
  anchor: "Anchor",
  concede: "Concede",
  hold: "Hold",
  trade: "Trade",
  accept: "Accept",
  walk: "Walk away",
  push: "Push",
};

export const MOVE_ICON: Record<MoveKind, string> = {
  anchor: "⚓",
  concede: "↗",
  hold: "■",
  trade: "⇄",
  accept: "✓",
  walk: "✕",
  push: "↘",
};

function distinctNonPrice(sheets: Priced[]): boolean {
  const keys = new Set<string>();
  for (const s of sheets) for (const k of Object.keys(s.terms ?? {})) if (k !== "unit_price") keys.add(k);
  for (const k of keys) {
    const vals = new Set(sheets.map((s) => JSON.stringify(s.terms?.[k])));
    if (vals.size > 1) return true;
  }
  return false;
}

function closestSheet(sheets: Priced[], terms?: Terms): number | undefined {
  if (!terms || sheets.length < 2) return undefined;
  let best = -1;
  let score = -1;
  sheets.forEach((s, i) => {
    let n = 0;
    for (const [k, v] of Object.entries(s.terms ?? {})) if (k !== "unit_price" && JSON.stringify(terms[k]) === JSON.stringify(v)) n++;
    if (n > score) (score = n), (best = i);
  });
  return best >= 0 ? best : undefined;
}

function planReason(rd: RoundData): string | undefined {
  const r = rd.decision?.reason;
  if (!r || r === "next_terms") return undefined;
  return r;
}

/** Sheet terms that differ from the supplier's standard / opening terms, as short chips. */
export function sheetChips(p: Priced, ref?: Terms): { k: string; label: string; value: string; changed: boolean }[] {
  return Object.entries(p.terms ?? {})
    .filter(([k]) => k !== "unit_price")
    .map(([k, v]) => ({
      k,
      label: termLabel(k),
      value: termValue(k, v),
      changed: !!ref && JSON.stringify(ref[k]) !== JSON.stringify(v),
    }));
}

export interface KeyMove {
  sid: string;
  supplier: string;
  round: number;
  saved: number;
  driver: string;
  icon: string;
}

/** The (up to 3) rounds where a supplier's standing offer dropped the most. */
export function keyMoves(model: CaseModel, stories: Map<string, RoundStory[]>): KeyMove[] {
  const all: KeyMove[] = [];
  for (const t of model.threads) {
    for (const s of stories.get(t.sid) ?? []) {
      if (!isNum(s.supplierStep) || s.supplierStep <= 0) continue;
      const verified = s.claims.filter((c) => c.result === "verified");
      let driver = `${s.moveLabel} answered`;
      let icon = MOVE_ICON[s.move];
      if (verified.length) {
        driver = `Verified: ${verified.map((c) => c.label).join(", ")}`;
        icon = "✓";
      } else if (s.sheets.length > 1) {
        driver = `${s.sheets.length} packages offered`;
        icon = "⇄";
      }
      all.push({ sid: t.sid, supplier: t.short, round: s.round, saved: s.supplierStep, driver, icon });
    }
  }
  return all.sort((a, b) => b.saved - a.saved).slice(0, 3);
}

export interface Verdict {
  score: number | null;
  saved: number | null; // C_open - C_deal
  gapToBest: number | null; // C_deal - C_best
  deal: boolean;
  supplier?: string;
  rounds: number;
  askPct: number | null; // supplier's opening unit price vs our current price
  dealPct: number | null; // deal unit price vs our current price
  openTerms?: Terms;
  dealTerms?: Terms;
  endReason?: string | null;
}

export function verdict(model: CaseModel): Verdict {
  const r = model.result;
  const cur = (model.caseFile?.buyer as Record<string, unknown> | undefined)?.current_unit_price;
  const dealT = model.threads.find((t) => t.sid === r?.supplier_id);
  const openT = dealT ?? model.threads.reduce<Thread | undefined>((a, t) => (!a || (t.standing[0]?.c ?? Infinity) < (a.standing[0]?.c ?? Infinity) ? t : a), undefined);
  const openTerms = openT?.standing[0]?.priced?.terms;
  const dealTerms = r?.terms ?? undefined;
  const pct = (p: unknown) => (isNum(cur) && isNum(p) && cur ? (p - cur) / cur : null);
  return {
    score: model.liveScore,
    saved: isNum(model.cOpen) && isNum(model.current.c) && r?.deal ? model.cOpen - model.current.c : null,
    gapToBest: isNum(model.current.c) && isNum(model.cBest) && r?.deal ? model.current.c - model.cBest : null,
    deal: !!r?.deal,
    supplier: dealT?.short,
    rounds: model.maxRound,
    askPct: pct(openTerms?.unit_price),
    dealPct: r?.deal ? pct(dealTerms?.unit_price) : null,
    openTerms,
    dealTerms,
    endReason: r?.end_reason,
  };
}

/** Offers the suppliers put on the table that were cheaper for us than the deal we took. */
export function leftOnTable(model: CaseModel): { supplier: string; round: number; priced: Priced; diff: number }[] {
  // compare like with like: the deal's own priced sheet (the result's C adds terms the sheets don't carry)
  const dealT = model.threads.find((t) => t.sid === model.result?.supplier_id);
  const deal = model.result?.deal ? (dealT?.current?.c ?? null) : null;
  if (!isNum(deal)) return [];
  const out: { supplier: string; round: number; priced: Priced; diff: number }[] = [];
  const seen = new Set<string>();
  for (const t of model.threads) {
    for (const s of t.standing) if (isNum(s.c) && s.c < deal - 1) out.push({ supplier: t.short, round: s.round, priced: s.priced, diff: deal - s.c });
    for (const rd of t.rounds)
      for (const a of rd.reply?.alternatives ?? [])
        if (isNum(a.priced?.c) && a.priced!.c! < deal - 1) out.push({ supplier: t.short, round: rd.round, priced: a.priced!, diff: deal - a.priced!.c! });
  }
  return out
    .sort((a, b) => b.diff - a.diff || a.round - b.round)
    .filter((o) => {
      const k = o.supplier + JSON.stringify(o.priced.terms);
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    })
    .slice(0, 3);
}

export function priceLine(p?: Priced): string {
  return p?.terms?.unit_price !== undefined ? eur2(p.terms.unit_price) : "–";
}

export interface Outcome {
  deal: boolean;
  cOpen: number | null;
  cDeal: number | null;
  cAlt: number | null;
  saved: number | null; // vs their opening (C), positive = we pay less
  savedPct: number | null; // saved / C_open
  increaseAvertedPct: number | null; // price-increase cases: share of the asked unit-price increase we averted
  vsAlternative: number | null; // C_alt - C_deal, positive = better than walking away
  floor: number | null; // supplier's estimated cost floor, €/unit (dossier), when logged
  floorSource?: string;
  dealUnit: number | null;
  vsFloorEstimate: number | null; // deal unit price - est. floor, €/unit
}

/** The product's view of a result: money against their opening, our walk-away and their cost floor (no arena score). */
export function outcome(model: CaseModel): Outcome {
  const r = model.result;
  const v = verdict(model);
  const deal = !!r?.deal;
  const cDeal = deal ? (isNum(r?.c_deal) ? r!.c_deal! : model.current.c) : null;
  const cOpen = model.cOpen;
  const saved = isNum(cOpen) && isNum(cDeal) ? cOpen - cDeal : null;
  const dealT = model.threads.find((t) => t.sid === r?.supplier_id);
  const floor = dealT?.dossier?.floor_estimate ?? null;
  const dealUnit = deal && isNum(r?.terms?.unit_price) ? (r!.terms!.unit_price as number) : null;
  return {
    deal,
    cOpen,
    cDeal,
    cAlt: model.cAlt,
    saved,
    savedPct: isNum(saved) && isNum(cOpen) && cOpen ? saved / cOpen : null,
    // only where the supplier asked for an increase; a deal below today's price counts as 100 %
    increaseAvertedPct:
      model.type === "price_increase" && isNum(v.askPct) && isNum(v.dealPct) && v.askPct > 0 ? Math.min(1, Math.max(0, (v.askPct - v.dealPct) / v.askPct)) : null,
    vsAlternative: isNum(model.cAlt) && isNum(cDeal) ? model.cAlt - cDeal : null,
    floor: isNum(floor) ? floor : null,
    floorSource: dealT?.dossier?.floor_source,
    dealUnit,
    vsFloorEstimate: isNum(floor) && isNum(dealUnit) ? dealUnit - floor : null,
  };
}

export interface ReviewReason {
  icon: string;
  label: string;
}

/** Why a manager should look at this negotiation (empty = closed cleanly). By code from the log only. */
export function reviewReasons(model: CaseModel, stories?: Map<string, RoundStory[]>): ReviewReason[] {
  const o = outcome(model);
  const out: ReviewReason[] = [];
  if (model.result && !o.deal) {
    const why = (model.result.end_reason ?? "").replace(/_/g, " ");
    out.push({ icon: "✕", label: !why || /no deal|walked away/i.test(why) ? "No deal" : `No deal · ${why}` });
  }
  if (o.deal && isNum(o.vsAlternative) && o.vsAlternative < 0) out.push({ icon: "↗", label: `${eurK(-o.vsAlternative)} worse than walk-away` });
  const left = leftOnTable(model);
  if (left.length) out.push({ icon: "€", label: `${eurK(left[0].diff)} cheaper offer not taken` });
  if (o.deal && isNum(o.vsFloorEstimate) && isNum(o.floor) && o.floor > 0 && o.vsFloorEstimate / o.floor > 0.05)
    out.push({ icon: "▲", label: `${((o.vsFloorEstimate / o.floor) * 100).toFixed(0)} % above est. floor` });
  const st = stories ?? new Map(model.threads.map((t) => [t.sid, roundStories(t)]));
  const contradicted = [...st.values()].flat().reduce((n, s) => n + s.claims.filter((c) => c.result === "contradicted").length, 0);
  if (contradicted) out.push({ icon: "✕", label: `${contradicted} argument${contradicted > 1 ? "s" : ""} contradicted` });
  return out;
}

function eurK(n: number): string {
  const a = Math.abs(n);
  return a >= 1e6 ? `€${(a / 1e6).toFixed(2)}M` : a >= 1e3 ? `€${(a / 1e3).toFixed(a >= 1e4 ? 0 : 1)}k` : `€${Math.round(a)}`;
}

/** Plain summary for the voice copilot (window.__copilotCase). */
export function copilotSummary(model: CaseModel, stories: Map<string, RoundStory[]>) {
  const v = verdict(model);
  const o = outcome(model);
  return {
    saved_vs_opening: o.saved,
    increase_averted_pct: o.increaseAvertedPct,
    vs_alternative: o.vsAlternative,
    vs_floor_estimate: o.vsFloorEstimate,
    review_reasons: reviewReasons(model, stories).map((r) => r.label),
    title: model.title,
    type: model.type,
    score: v.score,
    deal: v.deal,
    supplier: v.supplier,
    c_open: model.cOpen,
    c_deal: model.result?.c_deal ?? null,
    c_best: model.cBest,
    c_alt: model.cAlt,
    saved_eur: v.saved,
    gap_to_best_eur: v.gapToBest,
    opening_increase_pct: v.askPct,
    deal_increase_pct: v.dealPct,
    deal_terms: v.dealTerms ?? null,
    end_reason: v.endReason ?? null,
    threads: model.threads.map((t) => ({
      supplier_id: t.sid,
      supplier: t.name,
      status: t.status,
      rounds: (stories.get(t.sid) ?? []).map((s) => ({
        round: s.round,
        move: s.move,
        our_best_c: s.ourBest,
        packages: s.sheets.map((p) => ({ terms: p.terms, c: p.c })),
        claims: s.claims,
        planner_reason: s.reason ?? null,
        supplier_status: s.supplierStatus ?? null,
        supplier_standing_c: s.supplierAfter,
        supplier_step_eur: s.supplierStep,
        supplier_reasons: s.reasons,
        supplier_back_office: s.mind,
      })),
    })),
  };
}
