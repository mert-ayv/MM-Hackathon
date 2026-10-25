import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, type Edge, type EdgeProps } from "@xyflow/react";
import { cx } from "../ui";

// label: always shown; hint: shown only while the edge is hovered (keeps the canvas quiet)
type EdgeData = { label?: string; hint?: string; tone?: "accent"; offset?: number; viaY?: number; hovered?: boolean };
export type PillEdgeType = Edge<EdgeData, "pill">;
export type OrthoEdgeType = Edge<EdgeData, "ortho">;

function Pill({ x, y, data }: { x: number; y: number; data?: EdgeData }) {
  const text = data?.label ?? (data?.hovered ? data?.hint : undefined);
  if (!text) return null;
  return (
    <EdgeLabelRenderer>
      <div
        className={cx(
          "nodrag nopan pointer-events-none absolute z-10 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[0.78rem] font-medium shadow-card",
          data?.tone === "accent" ? "border-accent/40 bg-accent-soft text-accent-deep" : "border-line bg-white text-ink-2",
          !data?.label && "animate-rise",
        )}
        style={{ transform: `translate(-50%, -50%) translate(${x}px, ${y}px)` }}
      >
        {text}
      </div>
    </EdgeLabelRenderer>
  );
}

// smoothstep edge with an HTML pill label (crisper than SVG text, and it scales with presentation mode)
export function PillEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, style, markerEnd }: EdgeProps<PillEdgeType>) {
  const [path, x, y] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    borderRadius: 18,
    offset: data?.offset ?? 20,
  });
  return (
    <>
      <BaseEdge id={id} path={path} style={style} markerEnd={markerEnd} interactionWidth={24} />
      <Pill x={x} y={y} data={data} />
    </>
  );
}

// an orthogonal route through a fixed corridor (viaY, in canvas units): source → down/up to the corridor →
// across → into the target. Used for the long edges so they never cross the stages.
export function OrthoEdge({ id, sourceX, sourceY, targetX, targetY, data, style, markerEnd }: EdgeProps<OrthoEdgeType>) {
  const via = data?.viaY ?? (sourceY + targetY) / 2;
  const r = 14;
  const dx = Math.sign(targetX - sourceX) || 1;
  const d1 = Math.sign(via - sourceY) || 1;
  const d2 = Math.sign(targetY - via) || 1;
  const path = [
    `M ${sourceX} ${sourceY}`,
    `L ${sourceX} ${via - d1 * r}`,
    `Q ${sourceX} ${via} ${sourceX + dx * r} ${via}`,
    `L ${targetX - dx * r} ${via}`,
    `Q ${targetX} ${via} ${targetX} ${via + d2 * r}`,
    `L ${targetX} ${targetY}`,
  ].join(" ");
  return (
    <>
      <BaseEdge id={id} path={path} style={style} markerEnd={markerEnd} interactionWidth={24} />
      <Pill x={(sourceX + targetX) / 2} y={via} data={data} />
    </>
  );
}
