// The Agent Studio store: the agent's configuration as nodes, plus the change suggestions that the
// voice copilot and the analysis propose against it. Local-only (localStorage), synced across tabs.
import { useSyncExternalStore } from "react";
import { INITIAL_NODES, SEED_SUGGESTIONS } from "./agentSpec";

export type ParamValue = number | string | boolean;
export interface Param {
  key: string;
  label: string;
  value: ParamValue;
  unit?: string;
  hint?: string;
  min?: number;
  max?: number;
  step?: number;
  options?: string[];
}
export interface SubRule {
  id: string;
  when: string;
  then: string;
  enabled: boolean;
  from?: "manual" | "suggestion";
}
export type NodeKind = "trigger" | "router" | "intel" | "engine" | "check" | "llm" | "guard" | "rule" | "outcome";
export interface StudioNode {
  id: string;
  kind: NodeKind;
  title: string;
  subtitle: string;
  params: Param[];
  custom?: boolean;
  after?: string; // for standalone rule steps: id of the node it hooks after
  rules?: SubRule[]; // sub-rules that refine this step
}
export interface Suggestion {
  id: string;
  nodeId: string;
  paramKey?: string;
  title: string;
  rationale: string;
  before: string;
  after: string;
  evidence?: { runId: string; caseId: string; round?: number; quote?: string };
  // what the evidence rests on: this one negotiation, or comparable deals (same category / argument)
  evidenceKind?: "this_negotiation" | "comparable_deals";
  evidenceCount?: number;
  source: "voice" | "analysis";
  status: "pending" | "accepted" | "rejected";
  reason?: string;
  createdAt: string;
}
export interface StudioState {
  nodes: StudioNode[];
  suggestions: Suggestion[];
  // last change, for the "live in production" line and the node flash
  changedAt?: string;
  changedNode?: string;
}

const KEY = "studio.v3";
const listeners = new Set<() => void>();

function initial(): StudioState {
  return { nodes: structuredClone(INITIAL_NODES), suggestions: structuredClone(SEED_SUGGESTIONS) };
}

function load(): StudioState {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const s = JSON.parse(raw) as StudioState;
      if (Array.isArray(s.nodes) && Array.isArray(s.suggestions)) return s;
    }
  } catch {
    /* no storage */
  }
  return initial();
}

let state: StudioState = load();

function set(next: StudioState) {
  state = next;
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    /* private mode */
  }
  listeners.forEach((fn) => fn());
}

if (typeof window !== "undefined") {
  window.addEventListener("storage", (e) => {
    if (e.key !== KEY) return;
    state = load();
    listeners.forEach((fn) => fn());
  });
}

function uid(prefix: string) {
  return `${prefix}-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

function parseValue(raw: string, like: ParamValue): ParamValue {
  const t = raw.trim();
  if (typeof like === "boolean") return /^(true|on|yes|1|enabled?)$/i.test(t);
  if (typeof like === "number") {
    const n = Number(t.replace(/[^0-9.+-]/g, ""));
    if (!Number.isFinite(n)) return like;
    // "28 %" for a share stored as 0.28
    return /%/.test(t) && Math.abs(like) <= 1 ? n / 100 : n;
  }
  return t;
}

function withRule(s: StudioState, r: { title: string; when: string; then: string; after?: string }): [StudioState, string] {
  const id = uid("rule");
  const node: StudioNode = {
    id,
    kind: "rule",
    title: r.title,
    subtitle: "Custom decision rule",
    custom: true,
    after: r.after ?? "planner",
    params: [
      { key: "when", label: "When", value: r.when },
      { key: "then", label: "Then", value: r.then },
      { key: "enabled", label: "Enabled", value: true },
    ],
  };
  return [{ ...s, nodes: [...s.nodes, node], changedAt: new Date().toISOString(), changedNode: id }, id];
}

function withSubRule(s: StudioState, nodeId: string, r: { when: string; then: string }, from: SubRule["from"]): StudioState {
  const rule: SubRule = { id: uid("sr"), when: r.when, then: r.then, enabled: true, from };
  return {
    ...s,
    nodes: s.nodes.map((n) => (n.id === nodeId ? { ...n, rules: [...(n.rules ?? []), rule] } : n)),
    changedAt: new Date().toISOString(),
    changedNode: nodeId,
  };
}

function mapRules(nodeId: string, fn: (rules: SubRule[]) => SubRule[]) {
  set({
    ...state,
    nodes: state.nodes.map((n) => (n.id === nodeId ? { ...n, rules: fn(n.rules ?? []) } : n)),
    changedAt: new Date().toISOString(),
    changedNode: nodeId,
  });
}

export const studio = {
  get: () => state,
  subscribe(fn: () => void) {
    listeners.add(fn);
    return () => {
      listeners.delete(fn);
    };
  },
  updateParam(nodeId: string, key: string, value: ParamValue) {
    set({
      ...state,
      nodes: state.nodes.map((n) =>
        n.id === nodeId ? { ...n, params: n.params.map((p) => (p.key === key ? { ...p, value } : p)) } : n,
      ),
      changedAt: new Date().toISOString(),
      changedNode: nodeId,
    });
  },
  addRule(r: { title: string; when: string; then: string; after?: string }) {
    const [next, id] = withRule(state, r);
    set(next);
    return id;
  },
  addSubRule(nodeId: string, r: { when: string; then: string }) {
    set(withSubRule(state, nodeId, r, "manual"));
  },
  updateSubRule(nodeId: string, id: string, patch: Partial<Omit<SubRule, "id">>) {
    mapRules(nodeId, (rules) => rules.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  },
  removeSubRule(nodeId: string, id: string) {
    mapRules(nodeId, (rules) => rules.filter((r) => r.id !== id));
  },
  removeNode(id: string) {
    // only custom rules can go; the pipeline's stages stay
    set({ ...state, nodes: state.nodes.filter((n) => !(n.id === id && n.custom)), changedAt: new Date().toISOString() });
  },
  propose(s: Omit<Suggestion, "id" | "status" | "createdAt">) {
    const id = uid("sug");
    set({ ...state, suggestions: [{ ...s, id, status: "pending", createdAt: new Date().toISOString() }, ...state.suggestions] });
    return id;
  },
  accept(id: string) {
    const sug = state.suggestions.find((x) => x.id === id);
    if (!sug) return;
    let next: StudioState = { ...state, suggestions: state.suggestions.map((x) => (x.id === id ? { ...x, status: "accepted" } : x)) };
    const node = next.nodes.find((n) => n.id === sug.nodeId);
    const param = sug.paramKey ? node?.params.find((p) => p.key === sug.paramKey) : undefined;
    if (node && param) {
      const value = parseValue(sug.after, param.value);
      next = {
        ...next,
        nodes: next.nodes.map((n) =>
          n.id === node.id ? { ...n, params: n.params.map((p) => (p.key === param.key ? { ...p, value } : p)) } : n,
        ),
        changedAt: new Date().toISOString(),
        changedNode: node.id,
      };
    } else {
      // no matching setting: the change becomes a rule on the step it targets
      next = withSubRule(next, node ? sug.nodeId : "planner", { when: sug.before || "Always", then: sug.after }, "suggestion");
    }
    set(next);
  },
  reject(id: string, reason?: string) {
    set({ ...state, suggestions: state.suggestions.map((x) => (x.id === id ? { ...x, status: "rejected", reason } : x)) });
  },
  reset() {
    set(initial());
  },
};

export function useStudio(): StudioState {
  return useSyncExternalStore(studio.subscribe, studio.get, studio.get);
}

export function formatValue(p: Param): string {
  const v = p.value;
  if (typeof v === "boolean") return v ? "on" : "off";
  if (typeof v === "number" && p.unit === "%") return `${+(v * 100).toFixed(2)} %`;
  if (typeof v === "number") return `${v}${p.unit ? ` ${p.unit}` : ""}`;
  return String(v);
}
