import type { NodeKind } from "../../lib/studio";

export const KIND: Record<NodeKind, { label: string; color: string; soft: string }> = {
  trigger: { label: "Trigger", color: "#0B0B0C", soft: "#F4F4F1" },
  router: { label: "Router", color: "#8C93A3", soft: "#F2F3F6" },
  intel: { label: "Intelligence", color: "#3B6EA8", soft: "#EEF3FA" },
  check: { label: "Verification", color: "#2F8A5B", soft: "#ECF6F0" },
  engine: { label: "Decision engine", color: "#0B0B0C", soft: "#F4F4F1" },
  llm: { label: "Language model", color: "#7A5AF8", soft: "#F3F0FF" },
  guard: { label: "Guardrail", color: "#D9430E", soft: "#FFF1EB" },
  rule: { label: "Custom rule", color: "#FF5A1F", soft: "#FFF1EB" },
  outcome: { label: "Outcome", color: "#0B0B0C", soft: "#F4F4F1" },
};

const PATHS: Record<NodeKind, string> = {
  trigger: "M3 6.5h18v11H3z M3 7l9 6 9-6",
  router: "M6 4v5a3 3 0 0 0 3 3h6a3 3 0 0 1 3 3v5 M6 9v11 M3 17l3 3 3-3 M15 17l3 3 3-3",
  intel: "M12 3a6 6 0 0 0-6 6c0 2.2 1.2 3.5 2 4.5.6.8 1 1.5 1 2.5h6c0-1 .4-1.7 1-2.5.8-1 2-2.3 2-4.5a6 6 0 0 0-6-6z M9.5 19h5 M10.5 21.5h3",
  check: "M12 3l7 3v5c0 4.5-3 8.5-7 10-4-1.5-7-5.5-7-10V6z M8.5 12l2.5 2.5 4.5-5",
  engine: "M4 20V10 M10 20V4 M16 20v-7 M22 20H2",
  llm: "M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z M18.5 15.5l.9 2.1 2.1.9-2.1.9-.9 2.1-.9-2.1-2.1-.9 2.1-.9z",
  guard: "M5 11V8a7 7 0 0 1 14 0v3 M4 11h16v10H4z M12 15v2.5",
  rule: "M12 2v4 M12 18v4 M2 12h4 M18 12h4 M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z",
  outcome: "M5 12.5l4.5 4.5L19 7.5",
};

export function KindIcon({ kind, className }: { kind: NodeKind; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d={PATHS[kind]} />
    </svg>
  );
}
