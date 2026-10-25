import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { formatValue, type StudioNode } from "../../lib/studio";
import { ROUTES } from "../../lib/agentSpec";
import { cx } from "../ui";
import { KIND, KindIcon } from "./kinds";

export type FlowNodeData = {
  node: StudioNode;
  pending: number;
  flash: string | null; // changedAt when this node just changed: restarts the animation
  highlight: boolean;
  modified: number; // params that differ from the shipped defaults
};
export type FlowNodeType = Node<FlowNodeData, "studio">;

const handle = "!h-2.5 !w-2.5 !border-2 !border-white !bg-ink-4";
const hidden = "!h-1.5 !w-1.5 !min-w-0 !border-0 !bg-transparent";
// side handles sit level with the title row, so a row of stages with different heights still joins in straight lines
const ROW = { top: 34 };

export function FlowNode({ data, selected }: NodeProps<FlowNodeType>) {
  const { node, pending, flash, highlight, modified } = data;
  const k = KIND[node.kind];
  const rule = node.kind === "rule";
  const chips = rule ? [] : node.params.slice(0, 2);
  const enabled = !rule || node.params.find((p) => p.key === "enabled")?.value !== false;

  return (
    <div
      className={cx(
        "group relative rounded-2xl border bg-white text-left transition-shadow",
        rule ? "border-2 border-dashed border-accent bg-accent-soft/40" : "border-line shadow-card",
        selected && !rule && "border-ink ring-2 ring-ink/10",
        selected && rule && "ring-2 ring-accent/25",
        highlight && "ring-4 ring-accent/30",
        !enabled && "opacity-50",
        node.id === "router" ? "w-[300px]" : "w-[262px]",
      )}
    >
      {flash && <div key={flash} className="pointer-events-none absolute inset-0 animate-flash rounded-2xl" />}
      <Handle id="tl" type="target" position={Position.Left} className={handle} style={ROW} />
      <Handle id="sr" type="source" position={Position.Right} className={handle} style={ROW} />
      <Handle id="tt" type="target" position={Position.Top} className={hidden} />
      <Handle id="sb" type="source" position={Position.Bottom} className={hidden} />
      {/* the round loop leaves the guard and re-enters the lever engine off-centre, clear of the accept edge */}
      <Handle id="sbl" type="source" position={Position.Bottom} className={hidden} style={{ left: "22%" }} />
      <Handle id="tbl" type="target" position={Position.Bottom} className={hidden} style={{ left: "22%" }} />

      <div className="flex items-start gap-3 p-3.5">
        <span
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl"
          style={{ background: rule ? "#FF5A1F" : k.soft, color: rule ? "white" : k.color }}
        >
          <KindIcon kind={node.kind} className="h-[1.15rem] w-[1.15rem]" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[0.7rem] font-semibold uppercase tracking-[0.14em]" style={{ color: k.color }}>
            {k.label}
          </div>
          <div className="truncate text-[1.08rem] font-semibold leading-tight tracking-tight text-ink">{node.title}</div>
          <div className="mt-0.5 line-clamp-2 text-[0.84rem] leading-snug text-ink-3">{node.subtitle}</div>
        </div>
      </div>

      {node.id === "router" && (
        <div className="mx-3.5 mb-3 overflow-hidden rounded-lg border border-line-2 bg-paper-2">
          {ROUTES.map((r, i) => (
            <div
              key={r.type}
              className={cx("grid grid-cols-[6rem_1fr] items-center gap-2 px-2.5 py-[5px] text-[0.8rem]", i > 0 && "border-t border-line-2")}
            >
              <span className="truncate font-medium text-ink">{r.label}</span>
              <span className="flex min-w-0 items-center justify-between gap-1.5">
                <span className="truncate text-ink-3">{r.approach}</span>
                <span className="shrink-0 rounded bg-white px-1.5 py-px text-[0.7rem] font-medium text-ink-2 ring-1 ring-line">{r.lever}</span>
              </span>
            </div>
          ))}
        </div>
      )}

      {rule && (
        <div className="mx-3.5 mb-3 space-y-1 text-[0.84rem] leading-snug">
          <div>
            <span className="mr-1 rounded bg-white px-1 py-px font-mono text-[0.7rem] font-semibold text-accent-deep">WHEN</span>
            <span className="text-ink-2">{String(node.params.find((p) => p.key === "when")?.value ?? "")}</span>
          </div>
          <div>
            <span className="mr-1 rounded bg-white px-1 py-px font-mono text-[0.7rem] font-semibold text-accent-deep">THEN</span>
            <span className="text-ink">{String(node.params.find((p) => p.key === "then")?.value ?? "")}</span>
          </div>
        </div>
      )}

      {chips.length > 0 && node.id !== "router" && (
        <div className="flex flex-wrap gap-1.5 border-t border-line-2 px-3.5 py-2.5">
          {chips.map((p) => (
            <span key={p.key} className="inline-flex max-w-full items-center gap-1 rounded-md bg-paper-3 px-1.5 py-0.5 text-[0.78rem] text-ink-3">
              <span className="truncate">{p.label}</span>
              <span className="font-mono font-semibold text-ink">{formatValue(p)}</span>
            </span>
          ))}
          {node.params.length > 2 && <span className="px-1 py-0.5 text-[0.78rem] text-ink-4">+{node.params.length - 2}</span>}
        </div>
      )}

      {!rule && (node.rules?.length ?? 0) > 0 && (
        <div className="border-t border-dashed border-accent/40 bg-accent-soft/40 px-3.5 py-2.5">
          <div className="mb-1 text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-accent-deep">
            Rules · {node.rules!.length}
          </div>
          <div className="space-y-1">
            {node.rules!.slice(0, 2).map((r) => (
              <div key={r.id} className={cx("flex gap-1.5 text-[0.76rem] leading-snug", !r.enabled && "opacity-40 line-through")}>
                <span className="mt-[5px] h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                <span className="line-clamp-1 text-ink-2">
                  <span className="font-medium text-ink">{r.when}</span> → {r.then}
                </span>
              </div>
            ))}
            {node.rules!.length > 2 && <div className="text-[0.72rem] text-ink-3">+{node.rules!.length - 2} more</div>}
          </div>
        </div>
      )}

      {(pending > 0 || modified > 0) && (
        <div className="absolute -top-3.5 right-3 flex gap-1">
          {modified > 0 && (
            <span className="rounded-full border border-line bg-white px-1.5 py-0.5 text-[0.72rem] font-medium text-ink-2 shadow-card">
              {modified} edited
            </span>
          )}
          {pending > 0 && (
            <span className="relative flex">
              <span className="absolute inset-0 animate-ping2 rounded-full bg-accent" />
              <span className="relative rounded-full bg-accent px-1.5 py-0.5 text-[0.72rem] font-semibold text-white shadow-card">
                {pending} suggestion{pending > 1 ? "s" : ""}
              </span>
            </span>
          )}
        </div>
      )}
    </div>
  );
}

export type LaneNodeType = Node<{ label: string; hint: string; w: number; h: number }, "lane">;

// a swim lane behind the stages: when they run
export function LaneNode({ data }: NodeProps<LaneNodeType>) {
  return (
    <div className="rounded-3xl border border-line" style={{ width: data.w, height: data.h }}>
      <div className="px-5 pt-3 text-right text-[0.8rem] font-semibold uppercase tracking-[0.14em] text-ink-3">
        {data.label} <span className="ml-1 font-normal normal-case tracking-normal text-ink-4">{data.hint}</span>
      </div>
    </div>
  );
}
