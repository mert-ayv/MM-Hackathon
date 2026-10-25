import { useEffect, useMemo, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  ReactFlow,
  type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { AGENT_VERSION, ROUTES } from "../lib/agentSpec";
import { go } from "../lib/router";
import { studio, useStudio, type StudioNode } from "../lib/studio";
import { FlowNode, LaneNode, type FlowNodeType, type LaneNodeType } from "../components/studio/FlowNode";
import { Inspector, modifiedCount } from "../components/studio/Inspector";
import { OrthoEdge, PillEdge, type OrthoEdgeType, type PillEdgeType } from "../components/studio/PillEdge";
import { RuleBuilder } from "../components/studio/RuleBuilder";
import { Suggestions } from "../components/studio/Suggestions";
import { cx } from "../components/ui";

// two rows: the case is prepared once (top), then every round runs left to right (bottom) and loops back
// through a corridor below the round row; the long edges run in corridors so they never cross a stage
const X = [0, 352, 742, 1094];
const ROW1 = 0;
const ROW2 = 400;
const PREP_CORRIDOR = 352; // between the two lanes
const LOOP_CORRIDOR = 728; // below the round row (clears a stage with a few rules)
const LAYOUT: Record<string, { x: number; y: number }> = {
  intake: { x: X[0], y: ROW1 },
  router: { x: X[1], y: ROW1 },
  dossier: { x: X[2], y: ROW1 },
  evidence: { x: X[3], y: ROW1 },
  levers: { x: X[0], y: ROW2 },
  planner: { x: 365, y: ROW2 },
  writer: { x: 730, y: ROW2 },
  guard: { x: X[3], y: ROW2 },
  outcome: { x: X[3], y: 768 },
};
// [source, target, hover hint]: straight joins within a row; their hints show on hover only
const FLOW: [string, string, string][] = [
  ["intake", "router", "e-mail parsed"],
  ["router", "dossier", "case type → strategy"],
  ["dossier", "evidence", "persona · cost floor"],
  ["levers", "planner", "term sheets"],
  ["planner", "writer", "price + claims"],
  ["writer", "guard", "draft e-mail"],
];

const nodeTypes = { studio: FlowNode, lane: LaneNode };
const edgeTypes = { pill: PillEdge, ortho: OrthoEdge };
const LANES: LaneNodeType[] = [
  { id: "lane-prep", type: "lane", position: { x: -30, y: -58 }, data: { label: "Before the first e-mail", hint: "once per case", w: 1436, h: 392 } },
  { id: "lane-round", type: "lane", position: { x: -30, y: 370 }, data: { label: "Every round", hint: "per supplier, all threads in parallel", w: 1436, h: 580 } },
].map((n) => ({ ...n, type: "lane" as const, selectable: false, draggable: false, focusable: false }));
const edgeStyle = { stroke: "#A1A1A6", strokeWidth: 1.5 };
const arrow = { type: MarkerType.ArrowClosed, color: "#A1A1A6", width: 16, height: 16 };

function rulePosition(rule: StudioNode, rules: StudioNode[]) {
  // standalone rule steps sit in a row below the round lane, left of the outcome
  const i = rules.indexOf(rule);
  return { x: (i % 3) * 365, y: 960 + Math.floor(i / 3) * 200 };
}

function ago(iso?: string) {
  if (!iso) return "shipped Sun 07:50";
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  return m < 1 ? "changed just now" : m < 60 ? `changed ${m} min ago` : `changed ${new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}

function exportConfig(nodes: StudioNode[]) {
  const config = {
    agent: AGENT_VERSION,
    exported: new Date().toISOString(),
    routes: Object.fromEntries(ROUTES.map((r) => [r.type, { approach: r.approach, lever: r.lever }])),
    stages: Object.fromEntries(
      nodes
        .filter((n) => !n.custom)
        .map((n) => [
          n.id,
          { ...Object.fromEntries(n.params.map((p) => [p.key, p.value])), rules: (n.rules ?? []).map(({ when, then, enabled }) => ({ when, then, enabled })) },
        ]),
    ),
    rules: nodes
      .filter((n) => n.custom)
      .map((n) => ({ title: n.title, after: n.after, ...Object.fromEntries(n.params.map((p) => [p.key, p.value])) })),
  };
  const url = URL.createObjectURL(new Blob([JSON.stringify(config, null, 2)], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "agent-config.json";
  a.click();
  URL.revokeObjectURL(url);
}

type Tab = "inbox" | "node" | "rule";

export function StudioView({ nodeId }: { nodeId?: string }) {
  const { nodes, suggestions, changedAt, changedNode } = useStudio();
  const [moved, setMoved] = useState<Record<string, { x: number; y: number }>>({});
  const [hover, setHover] = useState<string | null>(null);
  const [hoverEdge, setHoverEdge] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>(nodeId ? "node" : "inbox");
  const [now, setNow] = useState(Date.now());
  const selected = nodes.find((n) => n.id === nodeId);
  const pending = suggestions.filter((s) => s.status === "pending");

  useEffect(() => setTab(nodeId ? "node" : (t) => (t === "node" ? "inbox" : t)), [nodeId]);
  // the flash lasts a few seconds after a change; re-render once it is over
  useEffect(() => {
    setNow(Date.now());
    const t = setTimeout(() => setNow(Date.now()), 4000);
    return () => clearTimeout(t);
  }, [changedAt]);

  const rules = nodes.filter((n) => n.custom);
  const ruleCount = rules.length + nodes.reduce((k, n) => k + (n.rules?.length ?? 0), 0);
  const flowNodes: (FlowNodeType | LaneNodeType)[] = useMemo(
    () => [
      ...LANES,
      ...nodes.map((n) => ({
        id: n.id,
        type: "studio" as const,
        position: moved[n.id] ?? (n.custom ? rulePosition(n, rules) : LAYOUT[n.id] ?? { x: 0, y: 500 }),
        selected: n.id === nodeId,
        data: {
          node: n,
          pending: pending.filter((s) => s.nodeId === n.id).length,
          flash: changedNode === n.id && changedAt && now - new Date(changedAt).getTime() < 3500 ? changedAt : null,
          highlight: hover === n.id,
          modified: modifiedCount(n),
        },
      })),
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [nodes, moved, nodeId, suggestions, changedAt, changedNode, hover, now],
  );

  const edges: (PillEdgeType | OrthoEdgeType)[] = useMemo(() => {
    const main: (PillEdgeType | OrthoEdgeType)[] = FLOW.map(([s, t, hint]) => ({
      id: `${s}-${t}`,
      source: s,
      target: t,
      sourceHandle: "sr",
      targetHandle: "tl",
      type: "pill",
      animated: true,
      data: { hint, hovered: hoverEdge === `${s}-${t}` },
      style: edgeStyle,
      markerEnd: arrow,
    }));
    main.push(
      {
        id: "evidence-levers",
        source: "evidence",
        sourceHandle: "sb",
        target: "levers",
        targetHandle: "tt",
        type: "ortho",
        animated: true,
        data: { label: "case prepared → round 1", viaY: PREP_CORRIDOR },
        style: edgeStyle,
        markerEnd: arrow,
      },
      {
        id: "guard-outcome",
        source: "guard",
        sourceHandle: "sb",
        target: "outcome",
        targetHandle: "tt",
        type: "pill",
        data: { label: "accept" },
        style: edgeStyle,
        markerEnd: arrow,
      },
      {
        id: "loop",
        source: "guard",
        sourceHandle: "sbl",
        target: "levers",
        targetHandle: "tbl",
        type: "ortho",
        data: { label: "counter-offer · next round", tone: "accent", viaY: LOOP_CORRIDOR },
        style: { stroke: "#FF5A1F", strokeWidth: 1.5, strokeDasharray: "5 4" },
        markerEnd: { ...arrow, color: "#FF5A1F" },
      },
    );
    for (const r of rules)
      main.push({
        id: `rule-${r.id}`,
        source: r.after ?? "planner",
        sourceHandle: "sb",
        target: r.id,
        targetHandle: "tt",
        type: "pill",
        animated: true,
        style: { stroke: "#FF5A1F", strokeWidth: 1.5, strokeDasharray: "4 4" },
        markerEnd: { ...arrow, color: "#FF5A1F" },
      });
    return main;
  }, [rules, hoverEdge]);

  const onNodesChange = (changes: NodeChange<FlowNodeType | LaneNodeType>[]) => {
    const next = { ...moved };
    let any = false;
    for (const c of changes)
      if (c.type === "position" && c.position) {
        next[c.id] = c.position;
        any = true;
      }
    if (any) setMoved(next);
  };

  return (
    <div className="flex h-[calc(100vh-3.5rem)]">
      <div className="flex min-w-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-line bg-white px-5 py-3">
        <div className="min-w-0">
          <div className="flex items-baseline gap-2">
            <span className="text-[0.66rem] font-medium uppercase tracking-[0.12em] text-ink-3">Purchasing agent</span>
            <span className="truncate text-[1.05rem] font-semibold tracking-tight">Hollerau buyer · indirect & direct spend</span>
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.74rem] text-ink-3">
            <span className="inline-flex items-center gap-1.5 font-medium text-ink">
              <span className="h-1.5 w-1.5 animate-pulsedot rounded-full bg-[#2F8A5B]" /> Live
            </span>
            <span className="font-mono">{AGENT_VERSION}</span>
            <span>{ago(changedAt)}</span>
            <span>
              {nodes.length - rules.length} stages · {ROUTES.length} case types · {ruleCount} rule{ruleCount === 1 ? "" : "s"}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="hidden items-center gap-3 text-[0.7rem] text-ink-3 xl:flex">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-0.5 w-5 rounded bg-ink-4" /> flow
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-0 w-5 border-t-2 border-dashed border-accent" /> next round · rules
            </span>
            <span className="font-medium text-ink-2">Code sets every number · the LLM only words it</span>
          </div>
          <button
            onClick={() => {
              studio.reset();
              setMoved({});
            }}
            className="rounded-full border border-line bg-white px-3.5 py-1.5 text-[0.78rem] font-medium text-ink-2 hover:border-ink"
            title="Back to the shipped configuration"
          >
            Reset
          </button>
          <button onClick={() => exportConfig(nodes)} className="rounded-full bg-ink px-3.5 py-1.5 text-[0.78rem] font-semibold text-white hover:bg-ink-2">
            Export config
          </button>
        </div>
      </div>
      <div className="relative flex-1 bg-paper-2">
        <ReactFlow
          nodes={flowNodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={onNodesChange}
          onNodeClick={(_, n) => n.type === "studio" && go({ name: "studio", nodeId: n.id })}
          onPaneClick={() => nodeId && go({ name: "studio" })}
          onEdgeMouseEnter={(_, e) => setHoverEdge(e.id)}
          onEdgeMouseLeave={() => setHoverEdge(null)}
          fitView
          fitViewOptions={{ padding: { top: "16px", left: "16px", right: "16px", bottom: "84px" } }} // bottom: room for the voice dock
          minZoom={0.3}
          maxZoom={1.6}
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} color="#D6D6D2" />
          <Controls showInteractive={false} position="bottom-left" />
        </ReactFlow>

      </div>
    </div>
      <aside className="flex w-[360px] shrink-0 flex-col border-l border-line bg-white">
        <div className="flex gap-1 border-b border-line p-2">
          {(
            [
              ["inbox", `Suggestions${pending.length ? ` · ${pending.length}` : ""}`],
              ["node", "Configure"],
              ["rule", "+ Rule"],
            ] as [Tab, string][]
          ).map(([t, label]) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cx(
                "flex-1 rounded-full px-3 py-1.5 text-[0.78rem] font-medium transition-colors",
                tab === t ? "bg-ink text-white" : "text-ink-2 hover:bg-paper-3",
                t === "inbox" && pending.length > 0 && tab !== t && "text-accent-deep",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          {tab === "inbox" && <Suggestions suggestions={suggestions} nodes={nodes} onHover={setHover} />}
          {tab === "node" &&
            (selected ? (
              <>
                <Inspector node={selected} onClose={() => go({ name: "studio" })} />
                {pending.some((s) => s.nodeId === selected.id) && (
                  <div className="mt-6 border-t border-line pt-4">
                    <div className="mb-2 text-[0.66rem] font-medium uppercase tracking-[0.12em] text-accent-deep">Suggested changes for this step</div>
                    <Suggestions suggestions={pending.filter((s) => s.nodeId === selected.id)} nodes={nodes} onHover={setHover} />
                  </div>
                )}
              </>
            ) : (
              <div className="rounded-xl border border-dashed border-line px-4 py-6 text-center text-[0.8rem] text-ink-3">
                Click a step on the canvas to configure it.
              </div>
            ))}
          {tab === "rule" && <RuleBuilder nodes={nodes} />}
        </div>
      </aside>
    </div>
  );
}
