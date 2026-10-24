// Shapes from docs/run-log.md. Everything optional-ish: readers must survive missing fields.

export type Terms = Record<string, unknown>;

export interface Priced {
  terms: Terms;
  c: number | null;
  breakdown: Record<string, number> | null;
}

export interface BaseEvent {
  ts: string;
  seq: number;
  run_id?: string;
  agent?: string;
  case_id?: string;
  session_id?: string | null;
  type: string;
  [key: string]: unknown;
}

export interface Opening {
  offer_id?: string;
  supplier_name?: string;
  priced?: Priced;
  standard_terms?: Terms;
  body?: string;
  reasons?: string[] | null;
}

export interface CaseFile {
  case_id?: string;
  title?: string;
  type?: string;
  briefing?: string;
  suppliers?: string[];
  negotiable?: string[];
  round_limit?: number;
  buyer?: Record<string, unknown>;
  [k: string]: unknown;
}

export interface CaseOpened extends BaseEvent {
  type: "case_opened";
  case?: CaseFile;
  opening?: Record<string, Opening>;
  c_alt?: number | null;
}

export interface Persona {
  owner_type?: string;
  style?: string;
  pressures?: string[];
  what_moves_it?: string[];
  avoid?: string[];
}

export interface Dossier extends BaseEvent {
  type: "dossier";
  supplier_id: string;
  supplier_name?: string;
  summary?: string;
  persona?: Persona;
  floor_estimate?: number | null;
  floor_source?: string;
  facts?: { id: string; text: string }[];
}

export interface SpecialistOutput {
  lever?: string | null;
  value_for_us_eur?: number | null;
  value_for_supplier_eur?: number | null;
  proposal?: string | null;
  claim?: string | null;
  note?: string | null;
}

export interface Specialists extends BaseEvent {
  type: "specialists";
  round: number;
  supplier_id: string;
  outputs?: Record<string, SpecialistOutput>;
}

export interface Candidate {
  id: string;
  label?: string;
  sheets?: Priced[];
  claims?: { id: string; text: string }[];
  rationale?: string;
}

export interface Plan extends BaseEvent {
  type: "plan";
  round: number;
  supplier_id: string;
  target?: Priced | null;
  walk_away_c?: number | null;
  candidates?: Candidate[];
}

export interface Decision extends BaseEvent {
  type: "decision";
  round: number;
  supplier_id: string;
  kind: "send" | "accept" | "walk_away" | string;
  candidate_id?: string | null;
  reason?: string;
  decided_in_s?: number;
}

export interface MessageSent extends BaseEvent {
  type: "message_sent";
  round: number;
  supplier_id: string;
  subject?: string;
  body?: string;
  sheets?: Priced[];
  refs?: string[];
  claims?: { id: string; text: string }[];
}

export interface ClaimResult {
  index: number;
  result: string;
  ref?: string;
}

export interface Reply extends BaseEvent {
  type: "reply";
  round: number;
  supplier_id: string;
  from?: string;
  status?: string;
  subject?: string;
  body?: string;
  standing?: { offer_id?: string; priced?: Priced } | null;
  claim_results?: ClaimResult[];
  missing_fields?: string[];
  signals?: Record<string, unknown>;
  attachments?: { attachment_id: string; name: string; type: string }[];
  latency_s?: number | null;
  /** imported games: other sheets the supplier offered, and its reasons from the arena trace */
  alternatives?: { offer_id?: string; priced?: Priced }[];
  reasons?: string[] | null;
}

export interface BackofficeNote {
  round?: number;
  supplier_id?: string;
  supplier?: string;
  from?: string;
  to?: string;
  text?: string;
}

export interface ErrorEvent extends BaseEvent {
  type: "error";
  supplier_id?: string | null;
  status?: number;
  detail?: string;
}

export interface Result extends BaseEvent {
  type: "result";
  deal?: boolean;
  supplier_id?: string | null;
  offer_id?: string | null;
  terms?: Terms | null;
  c_open?: number | null;
  c_deal?: number | null;
  c_alt?: number | null;
  c_best?: number | null;
  score?: number | null;
  cost_breakdown?: Record<string, number> | null;
  end_reason?: string | null;
  replay_url?: string | null;
  must_haves_ok?: boolean | null;
}

export interface CaseSummary {
  case_id: string;
  real_case_id?: string;
  repeat?: number;
  file: string;
  events: number;
  status: "running" | "ended";
  title: string | null;
  type: string | null;
  suppliers: string[];
  rounds: number;
  deal: boolean | null;
  score: number | null;
  c_open: number | null;
  c_deal: number | null;
  c_best: number | null;
  c_alt: number | null;
  saved: number | null;
  end_reason: string | null;
  supplier_id: string | null;
  supplier_name: string | null;
  errors: number;
  first_ts: string | null;
  last_ts: string | null;
}

export interface RunMeta {
  run_id: string;
  agent: string | null;
  agent_version: string | null;
  set: string | null;
  started_at: string | null;
  ended_at: string | null;
  cases: string[];
  notes: string | null;
  source: string;
  folder?: string;
  dir: string;
  author?: string | null;
  variant?: string | null;
  agent_name?: string | null;
  commit?: string | null;
  case_summaries: CaseSummary[];
  mean_score: number | null;
  saved_total: number;
  running: boolean;
}

export const COST_KEYS = [
  "price",
  "uncovered_need",
  "fallback_risk",
  "payment_terms",
  "freight",
  "late_delivery",
  "quality",
  "tooling",
  "index_clause",
  "index_risk",
  "relationship",
] as const;

export const SPECIALIST_ORDER = ["price", "cash", "logistics", "quality", "volume", "index", "relationship"];
