import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, type Edge, type EdgeProps } from "@xyflow/react";
import { cx } from "../ui";

export type PillEdgeType = Edge<{ label?: string; tone?: "accent"; offset?: number }, "pill">;

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
      <BaseEdge id={id} path={path} style={style} markerEnd={markerEnd} />
      {data?.label && (
        <EdgeLabelRenderer>
          <div
            className={cx(
              "nodrag nopan pointer-events-none absolute whitespace-nowrap rounded-full border px-2 py-0.5 text-[0.62rem] font-medium",
              data.tone === "accent" ? "border-accent/40 bg-accent-soft text-accent-deep" : "border-line bg-white text-ink-3",
            )}
            style={{ transform: `translate(-50%, -50%) translate(${x}px, ${y}px)` }}
          >
            {data.label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
