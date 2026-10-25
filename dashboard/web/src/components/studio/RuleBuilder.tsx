import { useState } from "react";
import { go } from "../../lib/router";
import { studio, type StudioNode } from "../../lib/studio";
import { cx } from "../ui";

const WHEN = [
  "Supplier cites energy or raw-material costs",
  "Supplier says it is short of cash",
  "Supplier sends a final offer",
  "A rival quote is below this supplier's ask",
];
const THEN = [
  "Counter with the PPI index change (verified claim)",
  "Offer 14-day payment for a lower price",
  "Accept if within 0.5 % of our target",
  "Escalate to the category manager before replying",
];

function Field({ label, value, onChange, examples }: { label: string; value: string; onChange: (v: string) => void; examples: string[] }) {
  return (
    <div>
      <div className="mb-1 font-mono text-[0.62rem] font-semibold tracking-wider text-accent-deep">{label}</div>
      <textarea
        rows={2}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={examples[0]}
        className="w-full resize-none rounded-lg border border-line bg-white px-2.5 py-1.5 text-[0.82rem] outline-none focus:border-ink"
      />
      <div className="mt-1 flex flex-wrap gap-1">
        {examples.map((x) => (
          <button
            key={x}
            onClick={() => onChange(x)}
            className="rounded-full border border-line bg-paper-2 px-2 py-0.5 text-[0.66rem] text-ink-2 hover:border-ink"
          >
            {x}
          </button>
        ))}
      </div>
    </div>
  );
}

export function RuleBuilder({ nodes }: { nodes: StudioNode[] }) {
  const [title, setTitle] = useState("");
  const [when, setWhen] = useState("");
  const [then, setThen] = useState("");
  const [after, setAfter] = useState("planner");
  const [mode, setMode] = useState<"step" | "standalone">("step");
  const ok = when.trim() && then.trim();
  const stages = nodes.filter((n) => !n.custom && n.kind !== "outcome");

  return (
    <div className="space-y-3">
      <p className="text-[0.78rem] leading-snug text-ink-3">
        Teach the agent a house rule. The guardrails still check every number it produces.
      </p>
      <div className="flex gap-1 rounded-full bg-paper-3 p-1 text-[0.74rem] font-medium">
        {(
          [
            ["step", "Refine a step"],
            ["standalone", "New standalone step"],
          ] as const
        ).map(([m, label]) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={cx("flex-1 rounded-full px-2 py-1 transition-colors", mode === m ? "bg-white text-ink shadow-card" : "text-ink-3 hover:text-ink")}
          >
            {label}
          </button>
        ))}
      </div>
      {mode === "standalone" && (
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Step name, e.g. Energy-cost pushback"
          className="w-full rounded-lg border border-line bg-white px-2.5 py-1.5 text-[0.85rem] font-medium outline-none focus:border-ink"
        />
      )}
      <Field label="WHEN" value={when} onChange={setWhen} examples={WHEN} />
      <Field label="THEN" value={then} onChange={setThen} examples={THEN} />
      <div>
        <div className="mb-1 text-[0.7rem] font-medium text-ink-3">{mode === "step" ? "Applies to step" : "Runs after"}</div>
        <select
          value={after}
          onChange={(e) => setAfter(e.target.value)}
          className="w-full rounded-lg border border-line bg-white px-2 py-1.5 text-[0.82rem] outline-none focus:border-ink"
        >
          {stages.map((n) => (
            <option key={n.id} value={n.id}>
              {n.title}
            </option>
          ))}
        </select>
      </div>
      <button
        disabled={!ok}
        onClick={() => {
          if (mode === "step") {
            studio.addSubRule(after, { when: when.trim(), then: then.trim() });
            setWhen("");
            setThen("");
            go({ name: "studio", nodeId: after });
            return;
          }
          const id = studio.addRule({ title: title.trim() || when.trim().slice(0, 40), when: when.trim(), then: then.trim(), after });
          setTitle("");
          setWhen("");
          setThen("");
          go({ name: "studio", nodeId: id });
        }}
        className={cx(
          "w-full rounded-full px-4 py-2 text-[0.82rem] font-semibold transition-colors",
          ok ? "bg-accent text-white hover:bg-accent-deep" : "bg-paper-3 text-ink-4",
        )}
      >
        {mode === "step" ? "+ Add rule to this step" : "+ Add step to the agent"}
      </button>
    </div>
  );
}
