// The agent as the Studio shows it: one node per stage of the real pipeline (docs/ARCHITECTURE.md),
// with defaults from csee Params / variants v14 and the final router (starter-kit/csee/agents/router.py).
import type { StudioNode, Suggestion } from "./studio";

export const AGENT_VERSION = "Playbook v14";

// case type -> approach + main lever, from ROUTES on main (Sun 25 Oct), in plain words from a fixed vocabulary
export const APPROACHES = ["Planner", "Deep anchor", "Soft anchor", "Small steps", "Lever sweep"] as const;
export const ROUTES: { type: string; label: string; approach: (typeof APPROACHES)[number]; lever: string }[] = [
  { type: "price_increase", label: "Price increase", approach: "Planner", lever: "Payment terms" },
  { type: "renewal", label: "Renewal", approach: "Planner", lever: "Supplier facts" },
  { type: "rfq", label: "RFQ", approach: "Deep anchor", lever: "Rival quotes" },
  { type: "raw_material", label: "Raw material", approach: "Planner", lever: "Index clause" },
  { type: "capacity", label: "Capacity", approach: "Soft anchor", lever: "Lead time" },
  { type: "quality", label: "Quality", approach: "Small steps", lever: "Quality terms" },
  { type: "bundling", label: "Bundling", approach: "Lever sweep", lever: "All terms" },
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
      { key: "fallback", label: "Unknown case type", value: "Concession planner", options: ["Concession planner", "Lever sweep", "Ask a buyer"] },
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
      { key: "cash_rate", label: "Cash-short supplier's rate", value: 0.14, unit: "%", min: 0.05, max: 0.25, step: 0.01 },
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
      { key: "own_quote_claims", label: "Cite their own previous quote", value: true, hint: "\u201cYour last quote was €X\u201d" },
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
      { key: "model", label: "Model", value: "claude-opus-5-5", options: ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "template only"] },
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
    subtitle: "€ saved, terms, lessons to the ledger",
    params: [
      { key: "log_ledger", label: "Write to experiment ledger", value: true },
      { key: "voice_debrief", label: "Voice debrief to the buyer", value: true },
    ],
  },
];

// Each suggestion is grounded in what a real product has: one negotiation's own log, or comparable deals
// (same category / argument across negotiations). Quotes are verbatim from runs/20261025-025817-router-x-practice.
export const SEED_SUGGESTIONS: Suggestion[] = [
  {
    id: "seed-own-quote",
    nodeId: "evidence",
    paramKey: "own_quote_claims",
    title: "Stop citing a supplier's own previous quote",
    rationale:
      "In 6 of 6 comparable deals the supplier checked this argument and marked it irrelevant, while notice period, forecast and quality record were verified. It costs a slot that a verified fact could use.",
    before: "on",
    after: "off",
    evidenceKind: "comparable_deals",
    evidenceCount: 6,
    evidence: {
      runId: "20261025-025817-router-x-practice",
      caseId: "case:P01",
      round: 1,
      quote: "However, the rival quote data you cite does not concern this part or our company.",
    },
    source: "analysis",
    status: "pending",
    createdAt: "2026-10-25T07:40:00.000Z",
  },
  {
    id: "seed-cash-signal",
    nodeId: "planner",
    title: "Escalate when a supplier keeps asking for faster payment",
    rationale:
      "Kalwisz asked for faster payment in 4 of 5 replies and offered to reflect it in the price. Payment was outside our brief, so the agent kept answering \u201c60 days is fixed\u201d and the supplier only moved €0.50 per round.",
    before: "Supplier signals cash pressure and payment terms are outside the brief",
    after: "Ask the category buyer to unlock faster payment, then trade it for price",
    evidenceKind: "this_negotiation",
    evidence: {
      runId: "20261025-025817-router-x-practice",
      caseId: "case:P11",
      round: 2,
      quote: "Waiting 60 days for cash is tough for us, so we need this price to make it work.",
    },
    source: "analysis",
    status: "pending",
    createdAt: "2026-10-25T07:52:00.000Z",
  },
  {
    id: "seed-verified-facts",
    nodeId: "evidence",
    paramKey: "max_claims",
    title: "Allow a third argument when all three are verified facts",
    rationale:
      "In Brandlhuber's first reply all three facts we cited (quality record, volume change, notice period) came back verified, and their offer moved 4.2 % in one round, the biggest step of the negotiation.",
    before: "2",
    after: "3",
    evidenceKind: "this_negotiation",
    evidence: {
      runId: "20261024-165810-go49mor-v15",
      caseId: "case:P01",
      round: 1,
      quote: "We did not know that - a fair point.",
    },
    source: "analysis",
    status: "pending",
    createdAt: "2026-10-25T08:05:00.000Z",
  },
  {
    id: "seed-lead-time",
    nodeId: "levers",
    title: "Trade lead time when the supplier calls it a hard requirement",
    rationale:
      "Ravensteiner called its 56-day lead time strictly required in round 1. Insisting on our shorter lead time costs a concession every round; conceding the lead time early buys a price step instead.",
    before: "Supplier states a lead time is strictly required",
    after: "Offer their lead time in the next term sheet and ask for a lower unit price in return",
    evidenceKind: "this_negotiation",
    evidence: {
      runId: "20261025-025817-router-x-practice",
      caseId: "case:P10",
      round: 1,
      quote: "The Lieferzeit 56 days is strictly required to integrate this volume into our production schedule.",
    },
    source: "analysis",
    status: "pending",
    createdAt: "2026-10-25T08:10:00.000Z",
  },
];
