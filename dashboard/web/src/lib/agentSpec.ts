// The agent as the Studio shows it: one node per stage of the real pipeline (docs/ARCHITECTURE.md),
// with defaults from csee Params / variants v14 and the final router (starter-kit/csee/agents/router.py).
import type { StudioNode, Suggestion } from "./studio";

export const AGENT_VERSION = "router · v14a";

// case type -> strategy, from ROUTES on main (Sun 25 Oct)
export const ROUTES: { type: string; label: string; strategy: string; evidence: string }[] = [
  { type: "price_increase", label: "Price increase", strategy: "Planner + 14-day cash trade", evidence: "P01 0.975" },
  { type: "renewal", label: "Renewal", strategy: "Planner + dossier", evidence: "P03 0.923 · P04 0.86" },
  { type: "rfq", label: "RFQ", strategy: "Deep anchor, rivals cited", evidence: "P05 0.854 · D02 0.77" },
  { type: "raw_material", label: "Raw material", strategy: "Index clause, hedge-aware", evidence: "P08 0.744" },
  { type: "capacity", label: "Capacity", strategy: "Soft anchor, lead-time trade", evidence: "P10 0.686" },
  { type: "quality", label: "Quality", strategy: "Measured menu, reciprocal steps", evidence: "P11 0.877" },
  { type: "bundling", label: "Bundling", strategy: "Base, every lever", evidence: "P07 0.766" },
];

export const INITIAL_NODES: StudioNode[] = [
  {
    id: "intake",
    kind: "trigger",
    title: "Supplier e-mail in",
    subtitle: "Letter, quote PDF or RFQ reply",
    params: [
      { key: "parallel_threads", label: "Threads in parallel", value: true, hint: "Every supplier of a case at once" },
      { key: "round_clock", label: "Clock per thread", value: 60, unit: "s", min: 20, max: 120, step: 5 },
      { key: "time_aware", label: "Pace to the wave cap", value: true, hint: "Concede faster when few rounds fit" },
    ],
  },
  {
    id: "router",
    kind: "router",
    title: "Case router",
    subtitle: "7 case types → best strategy",
    params: [
      { key: "fallback", label: "Unknown type", value: "base-d/v14a", options: ["base-d/v14a", "mert-plan-dc/v14a", "walk away"] },
      { key: "auto_promote", label: "Promote winners from the ledger", value: false, hint: "Board winner per type → route" },
    ],
  },
  {
    id: "dossier",
    kind: "intel",
    title: "Supplier dossier",
    subtitle: "46 profiles · persona, pressures, floor",
    params: [
      { key: "fullcost_discount", label: "Should-cost scaling", value: 0.95, min: 0.85, max: 1.05, step: 0.01, hint: "Should-cost runs ~5 % high" },
      { key: "cash_rate", label: "Cash-short supplier's cost of money", value: 0.14, unit: "%", min: 0.05, max: 0.25, step: 0.01 },
      { key: "persona_priors", label: "Persona priors for the planner", value: false, hint: "Off: lost when the persona was wrong" },
      { key: "text_signals", label: "Read pressure from their e-mails", value: true },
    ],
  },
  {
    id: "evidence",
    kind: "check",
    title: "Evidence & claims",
    subtitle: "Only verified data arguments",
    params: [
      { key: "max_claims", label: "Arguments per message", value: 2, min: 0, max: 3, step: 1 },
      { key: "claim_order", label: "Order by", value: "measured effect", options: ["measured effect", "strength", "profile"] },
      { key: "should_cost_margin", label: "Cite should-cost when ask is above by", value: 0.08, unit: "%", min: 0.02, max: 0.2, step: 0.01 },
      { key: "rival_only_lower", label: "Cite rivals only when cheaper", value: true },
      { key: "history_claims", label: "Cite order history", value: false, hint: "0 of 26 moved a price" },
    ],
  },
  {
    id: "levers",
    kind: "engine",
    title: "Lever engine",
    subtitle: "Every term at its cheapest for us",
    params: [
      { key: "trade_gain", label: "Trade sheet must save", value: 0.006, unit: "%", min: 0.002, max: 0.02, step: 0.001 },
      { key: "cash_trade_always", label: "Always offer faster payment", value: true },
      { key: "lead_time_trade", label: "Trade lead time for price", value: false, hint: "Capacity cases" },
      { key: "ppm_trade", label: "Offer ppm relief for price", value: true, hint: "Quality cases" },
      { key: "sticky_max_cost", label: "Keep a term if it costs ≤", value: 0.008, unit: "%", min: 0, max: 0.02, step: 0.001 },
    ],
  },
  {
    id: "planner",
    kind: "engine",
    title: "Concession planner",
    subtitle: "Anchor, then concede slower than them",
    params: [
      { key: "anchor_leverage", label: "Opening anchor below their ask", value: 0.22, unit: "%", min: 0.05, max: 0.35, step: 0.01 },
      { key: "rfq_anchor_vs_leader", label: "RFQ: below the cheapest rival", value: 0.15, unit: "%", min: 0, max: 0.3, step: 0.01 },
      { key: "concede_early", label: "Gap given per round, early", value: 0.25, unit: "%", min: 0.05, max: 0.6, step: 0.05 },
      { key: "concede_late", label: "Gap given per round, late", value: 0.5, unit: "%", min: 0.1, max: 0.9, step: 0.05 },
      { key: "follow_share", label: "Our step ≤ their last step ×", value: 1.1, min: 0.3, max: 1.5, step: 0.1 },
    ],
  },
  {
    id: "writer",
    kind: "llm",
    title: "E-mail writer",
    subtitle: "LLM words it · code sets every number",
    params: [
      { key: "model", label: "Model", value: "claude-haiku-5-5", options: ["claude-haiku-5-5", "claude-sonnet-5-5", "template only"] },
      { key: "tone", label: "Tone", value: "warm, precise", options: ["warm, precise", "firm", "formal"] },
      { key: "verbatim_claims", label: "Claim sentences verbatim", value: true, hint: "The arena checks the IDs" },
      { key: "language", label: "Mirror supplier's language", value: false },
    ],
  },
  {
    id: "guard",
    kind: "guard",
    title: "Accept / walk-away guard",
    subtitle: "Deterministic close across threads",
    params: [
      { key: "close_gap", label: "Take it when within", value: 0.004, unit: "%", min: 0, max: 0.02, step: 0.001 },
      { key: "push_after_final", label: "Push after a final offer", value: 0, unit: "rounds", min: 0, max: 2, step: 1, hint: "Pushing made P02, P18 walk" },
      { key: "must_beat_alternative", label: "Deal must beat the alternative", value: true },
      { key: "numbers_from_code", label: "Numbers from code only", value: true, hint: "LLM never sets a figure" },
    ],
  },
  {
    id: "outcome",
    kind: "outcome",
    title: "Deal signed",
    subtitle: "Score, € saved, lessons to the ledger",
    params: [
      { key: "log_ledger", label: "Write to experiment ledger", value: true },
      { key: "voice_debrief", label: "Voice debrief to the buyer", value: true },
    ],
  },
];

// grounded in logged weaknesses (vault: 11 Results Capacity & Quality; router.py notes)
export const SEED_SUGGESTIONS: Suggestion[] = [
  {
    id: "seed-leadtime",
    nodeId: "levers",
    paramKey: "lead_time_trade",
    title: "Trade lead time for price on capacity cases",
    rationale:
      "Ravensteiner charges about €2.00/unit to hold 42 instead of 56 days. We kept 42 days and took a final €33.20 (0.601). When we took its own 54-day sheet, the score was 0.671.",
    before: "off",
    after: "on",
    evidence: { runId: "20261025-025817-router-x-practice", caseId: "P10", round: 1, quote: "The Lieferzeit 56 days is strictly required to integrate this volume into our production schedule." },
    source: "analysis",
    status: "pending",
    createdAt: "2026-10-25T07:40:00.000Z",
  },
  {
    id: "seed-ppm",
    nodeId: "levers",
    paramKey: "ppm_trade",
    title: "Stop offering ppm relief on quality cases",
    rationale:
      "A looser ppm doesn't buy price: the supplier granted the 1500 ppm we asked for and still wanted €46. Chargebacks cost us more than they are worth to the supplier.",
    before: "on",
    after: "off",
    evidence: { runId: "20261025-025817-router-x-practice", caseId: "P11", round: 1, quote: "Hello, we can do the 1500 ppm you want, but we need EUR 46." },
    source: "analysis",
    status: "pending",
    createdAt: "2026-10-25T07:52:00.000Z",
  },
];
