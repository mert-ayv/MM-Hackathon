import { INITIAL_NODES } from "../../lib/agentSpec";
import { useState } from "react";
import { formatValue, studio, type Param, type StudioNode, type SubRule } from "../../lib/studio";
import { cx } from "../ui";
import { KIND, KindIcon } from "./kinds";

function defaultOf(nodeId: string, key: string) {
  return INITIAL_NODES.find((n) => n.id === nodeId)?.params.find((p) => p.key === key)?.value;
}

export function modifiedCount(node: StudioNode): number {
  if (node.custom) return 0;
  return node.params.filter((p) => defaultOf(node.id, p.key) !== undefined && defaultOf(node.id, p.key) !== p.value).length;
}

function Toggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      onClick={() => onChange(!on)}
      className={cx("relative h-5 w-9 shrink-0 rounded-full transition-colors", on ? "bg-ink" : "bg-line")}
      aria-pressed={on}
    >
      <span className={cx("absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all", on ? "left-[18px]" : "left-0.5")} />
    </button>
  );
}

function Control({ node, p }: { node: StudioNode; p: Param }) {
  const set = (v: Param["value"]) => studio.updateParam(node.id, p.key, v);
  const def = defaultOf(node.id, p.key);
  const changed = !node.custom && def !== undefined && def !== p.value;
  const head = (
    <div className="flex items-baseline justify-between gap-3">
      <span className="flex items-center gap-1.5 text-[0.8rem] font-medium text-ink">
        {p.label}
        {changed && <span className="h-1.5 w-1.5 rounded-full bg-accent" title="Changed from the shipped default" />}
      </span>
      {typeof p.value !== "boolean" && p.options === undefined && typeof p.value === "number" && (
        <span className="font-mono text-[0.78rem] font-semibold text-ink">{formatValue(p)}</span>
      )}
    </div>
  );
  const foot = (p.hint || changed) && (
    <div className="mt-1 text-[0.7rem] leading-snug text-ink-3">
      {p.hint}
      {changed && (
        <button onClick={() => set(def!)} className="ml-1.5 text-accent-deep underline-offset-2 hover:underline">
          reset to {formatValue({ ...p, value: def! })}
        </button>
      )}
    </div>
  );

  if (typeof p.value === "boolean")
    return (
      <div className="py-3">
        <div className="flex items-center justify-between gap-3">
          {head}
          <Toggle on={p.value} onChange={set} />
        </div>
        {foot}
      </div>
    );
  if (p.options)
    return (
      <div className="py-3">
        {head}
        <div className="mt-2 flex flex-wrap gap-1">
          {p.options.map((o) => (
            <button
              key={o}
              onClick={() => set(o)}
              className={cx(
                "rounded-full border px-2.5 py-1 text-[0.72rem] font-medium transition-colors",
                o === p.value ? "border-ink bg-ink text-white" : "border-line text-ink-2 hover:border-ink",
              )}
            >
              {o}
            </button>
          ))}
        </div>
        {foot}
      </div>
    );
  if (typeof p.value === "number")
    return (
      <div className="py-3">
        {head}
        <input
          type="range"
          className="studio-range mt-3 w-full"
          style={{ ["--fill" as string]: `${(((p.value - (p.min ?? 0)) / ((p.max ?? 1) - (p.min ?? 0))) * 100).toFixed(1)}%` }}
          min={p.min ?? 0}
          max={p.max ?? 1}
          step={p.step ?? 0.01}
          value={p.value}
          onChange={(e) => set(Number(e.target.value))}
        />
        {foot}
      </div>
    );
  return (
    <div className="py-3">
      {head}
      <textarea
        rows={2}
        value={p.value}
        onChange={(e) => set(e.target.value)}
        className="mt-1.5 w-full resize-none rounded-lg border border-line bg-paper-2 px-2.5 py-1.5 text-[0.8rem] text-ink outline-none focus:border-ink"
      />
      {foot}
    </div>
  );
}

function RuleRow({ nodeId, r }: { nodeId: string; r: SubRule }) {
  return (
    <div className={cx("rounded-lg border border-accent/30 bg-accent-soft/40 px-2.5 py-2", !r.enabled && "opacity-50")}>
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1 space-y-1 text-[0.78rem] leading-snug">
          <div className="flex gap-1.5">
            <span className="mt-px shrink-0 rounded bg-white px-1 font-mono text-[0.62rem] font-semibold text-accent-deep">WHEN</span>
            <textarea
              rows={2}
              value={r.when}
              onChange={(e) => studio.updateSubRule(nodeId, r.id, { when: e.target.value })}
              className="w-full resize-none bg-transparent text-ink-2 outline-none focus:text-ink"
            />
          </div>
          <div className="flex gap-1.5">
            <span className="mt-px shrink-0 rounded bg-white px-1 font-mono text-[0.62rem] font-semibold text-accent-deep">THEN</span>
            <textarea
              rows={2}
              value={r.then}
              onChange={(e) => studio.updateSubRule(nodeId, r.id, { then: e.target.value })}
              className="w-full resize-none bg-transparent font-medium text-ink outline-none"
            />
          </div>
          {r.from === "suggestion" && <div className="text-[0.66rem] text-ink-3">from an accepted suggestion</div>}
        </div>
        <Toggle on={r.enabled} onChange={(v) => studio.updateSubRule(nodeId, r.id, { enabled: v })} />
      </div>
      <button onClick={() => studio.removeSubRule(nodeId, r.id)} className="mt-1 text-[0.68rem] text-ink-3 hover:text-accent-deep">
        Remove
      </button>
    </div>
  );
}

function AddSubRule({ nodeId }: { nodeId: string }) {
  const [open, setOpen] = useState(false);
  const [when, setWhen] = useState("");
  const [then, setThen] = useState("");
  if (!open)
    return (
      <button
        onClick={() => setOpen(true)}
        className="w-full rounded-lg border border-dashed border-accent/50 px-3 py-2 text-[0.78rem] font-medium text-accent-deep hover:bg-accent-soft/50"
      >
        + Add rule to this step
      </button>
    );
  const ok = when.trim() && then.trim();
  return (
    <div className="space-y-1.5 rounded-lg border border-line bg-paper-2 p-2.5">
      <input
        autoFocus
        value={when}
        onChange={(e) => setWhen(e.target.value)}
        placeholder="WHEN  e.g. supplier signals cash pressure"
        className="w-full rounded-md border border-line bg-white px-2 py-1.5 text-[0.78rem] outline-none focus:border-ink"
      />
      <input
        value={then}
        onChange={(e) => setThen(e.target.value)}
        placeholder="THEN  e.g. offer 14-day payment before conceding on price"
        className="w-full rounded-md border border-line bg-white px-2 py-1.5 text-[0.78rem] outline-none focus:border-ink"
      />
      <div className="flex gap-2">
        <button
          disabled={!ok}
          onClick={() => {
            studio.addSubRule(nodeId, { when: when.trim(), then: then.trim() });
            setWhen("");
            setThen("");
            setOpen(false);
          }}
          className={cx("flex-1 rounded-full px-3 py-1.5 text-[0.78rem] font-semibold", ok ? "bg-accent text-white hover:bg-accent-deep" : "bg-paper-3 text-ink-4")}
        >
          Add rule
        </button>
        <button onClick={() => setOpen(false)} className="rounded-full border border-line px-3 py-1.5 text-[0.78rem] text-ink-2">
          Cancel
        </button>
      </div>
    </div>
  );
}

export function Inspector({ node, onClose }: { node: StudioNode; onClose: () => void }) {
  const k = KIND[node.kind];
  return (
    <div>
      <div className="flex items-start gap-3">
        <span
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl"
          style={{ background: node.custom ? "#FF5A1F" : k.soft, color: node.custom ? "white" : k.color }}
        >
          <KindIcon kind={node.kind} className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[0.62rem] font-semibold uppercase tracking-[0.14em]" style={{ color: k.color }}>
            {k.label}
          </div>
          <div className="text-[1.05rem] font-semibold tracking-tight">{node.title}</div>
          <div className="text-[0.78rem] text-ink-3">{node.subtitle}</div>
        </div>
        <button onClick={onClose} className="rounded-full px-2 py-1 text-ink-3 hover:bg-paper-3 hover:text-ink" title="Close">
          ✕
        </button>
      </div>
      <div className="mt-3 divide-y divide-line-2">
        {node.params.map((p) => (
          <Control key={p.key} node={node} p={p} />
        ))}
      </div>
      {!node.custom && (
        <div className="mt-4 border-t border-line pt-4">
          <div className="mb-2 flex items-baseline justify-between">
            <span className="text-[0.66rem] font-medium uppercase tracking-[0.12em] text-ink-3">Rules for this step</span>
            <span className="text-[0.7rem] text-ink-4">{node.rules?.length ?? 0}</span>
          </div>
          <div className="space-y-2">
            {(node.rules ?? []).map((r) => (
              <RuleRow key={r.id} nodeId={node.id} r={r} />
            ))}
            <AddSubRule nodeId={node.id} />
          </div>
        </div>
      )}
      {node.custom && (
        <button
          onClick={() => {
            studio.removeNode(node.id);
            onClose();
          }}
          className="mt-3 text-[0.75rem] text-ink-3 hover:text-accent-deep"
        >
          Delete rule
        </button>
      )}
    </div>
  );
}
