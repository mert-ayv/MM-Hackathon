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
import { PillEdge, type PillEdgeType } from "../components/studio/PillEdge";
import { RuleBuilder } from "../components/studio/RuleBuilder";
import { Suggestions } from "../components/studio/Suggestions";
import { cx } from "../components/ui";

// the pipeline, left to right: intel before the first message, then per round levers → planner → writer → guard
const LAYOUT: Record<string, { x: number; y: number }> = {
  intake: { x: 0, y: 0 },
  router: { x: 0, y: 190 },
  dossier: { x: 310, y: 0 },
  evidence: { x: 310, y: 270 },
  levers: { x: 620, y: 0 },
  planner: { x: 620, y: 270 },
  writer: { x: 930, y: 135 },
  guard: { x: 1240, y: 0 },
  outcome: { x: 1240, y: 270 },
};
// [source, target, label?, sourceHandle, targetHandle]
const FLOW: [string, string, string | undefined, string, string][] = [
  ["intake", "router", undefined, "sb", "tt"],
  ["router", "dossier", "persona · floor", "sr", "tl"],
  ["router", "evidence", "verified facts", "sr", "tl"],
  ["dossier", "levers", undefined, "sr", "tl"],
  ["evidence", "planner", undefined, "sr", "tl"],
  ["levers", "planner", "term sheets", "sb", "tt"],
  ["levers", "writer", undefined, "sr", "tl"],
  ["planner", "writer", "price + claims", "sr", "tl"],
  ["writer", "guard", undefined, "sr", "tl"],
  ["guard", "outcome", "accept", "sb", "tt"],
];

const nodeTypes = { studio: FlowNode, lane: LaneNode };
const edgeTypes = { pill: PillEdge };
const LANES: LaneNodeType[] = [
  { id: "lane-prep", type: "lane", position: { x: -30, y: -100 }, data: { label: "Before the first e-mail", hint: "once per case", w: 590, h: 560 } },
  { id: "lane-round", type: "lane", position: { x: 590, y: -100 }, data: { label: "Every round", hint: "per supplier, all threads in parallel", w: 920, h: 560 } },
].map((n) => ({ ...n, type: "lane" as const, selectable: false, draggable: false, focusable: false }));
const edgeStyle = { stroke: "#A1A1A6", strokeWidth: 1.5 };
const arrow = { type: MarkerType.ArrowClosed, color: "#A1A1A6", width: 16, height: 16 };

function rulePosition(rule: StudioNode, rules: StudioNode[]) {
  // custom rules hang in a row below the pipeline, under the stage they follow
  const base = LAYOUT[rule.after ?? "planner"] ?? LAYOUT.planner;
  const siblings = rules.filter((r) => (r.after ?? "planner") === (rule.after ?? "planner"));
  const i = siblings.indexOf(rule);
  return { x: base.x + i * 24, y: 510 + i * 170 };
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
    routes: Object.fromEntries(ROUTES.map((r) => [r.type, r.strategy])),
    stages: Object.fromEntries(nodes.filter((n) => !n.custom).map((n) => [n.id, Object.fromEntries(n.params.map((p) => [p.key, p.value]))])),
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

  const edges: PillEdgeType[] = useMemo(() => {
    const main: PillEdgeType[] = FLOW.map(([s, t, label, sh, th]) => ({
      id: `${s}-${t}`,
      source: s,
      target: t,
      sourceHandle: sh,
      targetHandle: th,
      type: "pill",
      animated: true,
      data: { label },
      style: edgeStyle,
      markerEnd: arrow,
    }));
    main.push({
      id: "loop",
      source: "guard",
      sourceHandle: "st",
      target: "intake",
      targetHandle: "tt",
      type: "pill",
      data: { label: "counter-offer · next round", tone: "accent", offset: 44 },
      style: { stroke: "#FF5A1F", strokeWidth: 1.5, strokeDasharray: "5 4" },
      markerEnd: { ...arrow, color: "#FF5A1F" },
    });
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
  }, [rules]);

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
      <div className="relative flex-1 bg-paper-2">
        <ReactFlow
          nodes={flowNodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={onNodesChange}
          onNodeClick={(_, n) => n.type === "studio" && go({ name: "studio", nodeId: n.id })}
          onPaneClick={() => nodeId && go({ name: "studio" })}
          fitView
          fitViewOptions={{ padding: { top: 0.28, left: 0.06, right: 0.06, bottom: 0.12 } }}
          minZoom={0.3}
          maxZoom={1.6}
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} color="#D6D6D2" />
          <Controls showInteractive={false} position="bottom-left" />
        </ReactFlow>

        <div className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between gap-4 p-5">
          <div className="pointer-events-auto rounded-2xl border border-line bg-white/95 px-4 py-3 shadow-card backdrop-blur">
            <div className="text-[0.66rem] font-medium uppercase tracking-[0.12em] text-ink-3">Purchasing agent</div>
            <div className="mt-0.5 text-[1.15rem] font-semibold tracking-tight">Hollerau buyer · indirect & direct spend</div>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.74rem] text-ink-3">
              <span className="inline-flex items-center gap-1.5 font-medium text-ink">
                <span className="h-1.5 w-1.5 animate-pulsedot rounded-full bg-[#2F8A5B]" /> Live
              </span>
              <span className="font-mono">{AGENT_VERSION}</span>
              <span>{ago(changedAt)}</span>
              <span>
                {nodes.length - rules.length} stages · {ROUTES.length} case types · {rules.length} custom rule{rules.length === 1 ? "" : "s"}
              </span>
            </div>
          </div>
          <div className="pointer-events-auto flex gap-2">
            <button
              onClick={() => {
                studio.reset();
                setMoved({});
              }}
              className="rounded-full border border-line bg-white px-3.5 py-1.5 text-[0.78rem] font-medium text-ink-2 shadow-card hover:border-ink"
              title="Back to the shipped configuration"
            >
              Reset
            </button>
            <button
              onClick={() => exportConfig(nodes)}
              className="rounded-full bg-ink px-3.5 py-1.5 text-[0.78rem] font-semibold text-white shadow-card hover:bg-ink-2"
            >
              Export config
            </button>
          </div>
        </div>

        <div className="pointer-events-none absolute bottom-5 right-5 flex items-center gap-3 rounded-full border border-line bg-white/95 px-3.5 py-1.5 text-[0.7rem] text-ink-3 shadow-card">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-0.5 w-5 rounded bg-ink-4" /> every round
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-0 w-5 border-t-2 border-dashed border-accent" /> loop / custom rule
          </span>
          <span className="font-medium text-ink-2">Code sets every number · the LLM only words it</span>
        </div>
      </div>

      <aside className="flex w-[400px] shrink-0 flex-col border-l border-line bg-white">
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
