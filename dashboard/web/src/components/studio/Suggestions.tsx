import { useState } from "react";
import { href } from "../../lib/router";
import { studio, type StudioNode, type Suggestion } from "../../lib/studio";
import { cx } from "../ui";

function ago(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

function Source({ s }: { s: Suggestion }) {
  return s.source === "voice" ? (
    <span className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 text-[0.64rem] font-semibold text-accent-deep">
      🎙 from voice debrief
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-full bg-paper-3 px-2 py-0.5 text-[0.64rem] font-semibold text-ink-2">
      ◆ from negotiation analysis
    </span>
  );
}

function Basis({ s }: { s: Suggestion }) {
  if (!s.evidenceKind) return null;
  const comparable = s.evidenceKind === "comparable_deals";
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[0.64rem] font-semibold",
        comparable ? "border-[#2F5FD0]/25 bg-[#EEF3FF] text-[#2F5FD0]" : "border-line bg-white text-ink-2",
      )}
      title={comparable ? "The same pattern across comparable negotiations" : "Found in this one negotiation's own e-mails and offers"}
    >
      {comparable ? `▦ ${s.evidenceCount ?? "Several"} comparable deals` : "◉ This negotiation"}
    </span>
  );
}

function Diff({ s, node }: { s: Suggestion; node?: StudioNode }) {
  const param = s.paramKey ? node?.params.find((p) => p.key === s.paramKey) : undefined;
  return (
    <div className="overflow-hidden rounded-lg border border-line font-mono text-[0.72rem] leading-relaxed">
      <div className="border-b border-line bg-paper-2 px-2.5 py-1 text-[0.64rem] text-ink-3">
        {node?.title ?? s.nodeId}
        {param ? ` › ${param.label}` : " › + rule"}
      </div>
      {param ? (
        <>
          <div className="flex gap-2 bg-[#FDECEC] px-2.5 py-1 text-[#9F1D1D]">
            <span className="select-none">−</span>
            <span>
              {param.label}: {s.before}
            </span>
          </div>
          <div className="flex gap-2 bg-[#E8F6EE] px-2.5 py-1 text-[#17663F]">
            <span className="select-none">+</span>
            <span>
              {param.label}: {s.after}
            </span>
          </div>
        </>
      ) : (
        // a new rule on the step: nothing is removed, WHEN / THEN are added
        <>
          <div className="flex gap-2 bg-[#E8F6EE] px-2.5 py-1 text-[#17663F]">
            <span className="select-none">+</span>
            <span>
              <b>WHEN</b> {s.before || "always"}
            </span>
          </div>
          <div className="flex gap-2 bg-[#E8F6EE] px-2.5 py-1 text-[#17663F]">
            <span className="select-none">+</span>
            <span>
              <b>THEN</b> {s.after}
            </span>
          </div>
        </>
      )}
    </div>
  );
}

function Card({ s, node, onHover }: { s: Suggestion; node?: StudioNode; onHover: (id: string | null) => void }) {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const ev = s.evidence;
  return (
    <div
      onMouseEnter={() => onHover(s.nodeId)}
      onMouseLeave={() => onHover(null)}
      className="animate-rise rounded-xl border border-line bg-white p-3.5 shadow-card"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex flex-wrap items-center gap-1">
          <Source s={s} />
          <Basis s={s} />
        </span>
        <span className="text-[0.66rem] text-ink-4">{ago(s.createdAt)}</span>
      </div>
      <div className="mt-2 text-[0.9rem] font-semibold leading-snug tracking-tight">{s.title}</div>
      <div className="mt-2">
        <Diff s={s} node={node} />
      </div>
      <p className="mt-2 text-[0.76rem] leading-snug text-ink-2">{s.rationale}</p>
      {ev && (
        <a
          href={href({ name: "negotiation", runId: ev.runId, caseId: ev.caseId, round: ev.round })}
          className="mt-2 block rounded-lg border-l-2 border-accent bg-paper-2 px-2.5 py-1.5 text-[0.72rem] text-ink-2 hover:bg-paper-3"
        >
          {ev.quote && <span className="italic">“{ev.quote}”</span>}
          <span className="mt-0.5 block font-medium text-accent-deep">
            Evidence: {ev.caseId.replace(/^case:/, "")}
            {ev.round ? ` · round ${ev.round}` : ""} →
          </span>
        </a>
      )}
      {rejecting ? (
        <div className="mt-3 space-y-2">
          <input
            autoFocus
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && studio.reject(s.id, reason.trim() || undefined)}
            placeholder="Why not? (optional, the agent learns from it)"
            className="w-full rounded-lg border border-line px-2.5 py-1.5 text-[0.8rem] outline-none focus:border-ink"
          />
          <div className="flex gap-2">
            <button
              onClick={() => studio.reject(s.id, reason.trim() || undefined)}
              className="flex-1 rounded-full bg-ink px-3 py-1.5 text-[0.78rem] font-semibold text-white"
            >
              Reject
            </button>
            <button onClick={() => setRejecting(false)} className="rounded-full border border-line px-3 py-1.5 text-[0.78rem] text-ink-2">
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-3 flex gap-2">
          <button
            onClick={() => studio.accept(s.id)}
            className="flex-1 rounded-full bg-accent px-3 py-1.5 text-[0.8rem] font-semibold text-white transition-colors hover:bg-accent-deep"
          >
            ✓ Accept
          </button>
          <button
            onClick={() => setRejecting(true)}
            className="rounded-full border border-line px-4 py-1.5 text-[0.8rem] font-medium text-ink-2 hover:border-ink"
          >
            Reject
          </button>
        </div>
      )}
    </div>
  );
}

export function Suggestions({ suggestions, nodes, onHover }: { suggestions: Suggestion[]; nodes: StudioNode[]; onHover: (id: string | null) => void }) {
  const pending = suggestions.filter((s) => s.status === "pending");
  const done = suggestions.filter((s) => s.status !== "pending");
  const byId = (id: string) => nodes.find((n) => n.id === id);
  return (
    <div className="space-y-3">
      {pending.length === 0 && (
        <div className="rounded-xl border border-dashed border-line px-4 py-6 text-center text-[0.8rem] text-ink-3">
          No open suggestions. Ask the copilot about a negotiation and it will propose changes here.
        </div>
      )}
      {pending.map((s) => (
        <Card key={s.id} s={s} node={byId(s.nodeId)} onHover={onHover} />
      ))}
      {done.length > 0 && (
        <div className="pt-2">
          <div className="mb-2 text-[0.66rem] font-medium uppercase tracking-[0.12em] text-ink-3">History</div>
          <div className="space-y-1.5">
            {done.map((s) => (
              <div key={s.id} className="flex items-start gap-2 rounded-lg bg-paper-2 px-2.5 py-2 text-[0.74rem]">
                <span
                  className={cx(
                    "mt-px shrink-0 rounded-full px-1.5 py-px text-[0.6rem] font-semibold",
                    s.status === "accepted" ? "bg-[#E8F6EE] text-[#17663F]" : "bg-paper-3 text-ink-3",
                  )}
                >
                  {s.status === "accepted" ? "MERGED" : "REJECTED"}
                </span>
                <span className="min-w-0">
                  <span className={cx("font-medium", s.status === "rejected" ? "text-ink-3 line-through decoration-ink-4" : "text-ink")}>
                    {s.title}
                  </span>
                  {s.reason && <span className="block text-ink-3">“{s.reason}”</span>}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
