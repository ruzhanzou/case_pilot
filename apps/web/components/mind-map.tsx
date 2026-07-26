"use client";

import {
  Background,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  useReactFlow,
  useViewport,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { TestCase } from "@/lib/mock-data";
import { Ban, Check, FileText, Maximize2, Minus, Plus, RotateCcw, SkipForward, Sparkles, Workflow, XCircle } from "lucide-react";
import { memo, useMemo } from "react";

type MapNodeData = {
  label: string;
  eyebrow: string;
  kind: "root" | "module" | "point" | "case";
  state?: "pending" | "passed" | "failed" | "skipped" | "blocked";
  caseId?: string;
  priority?: TestCase["priority"];
  tags?: string[];
  automated?: boolean;
};

type MapNode = Node<MapNodeData, "caseMap">;

const CaseMapNode = memo(function CaseMapNode({ data, selected }: NodeProps<MapNode>) {
  const StateIcon =
    data.state === "passed"
      ? Check
      : data.state === "failed"
        ? XCircle
        : data.state === "skipped"
          ? SkipForward
          : data.state === "blocked"
            ? Ban
            : Sparkles;

  return (
    <div className={`map-node map-node--${data.kind} ${data.state ? `map-node--status-${data.state}` : ""} ${selected ? "is-selected" : ""}`}>
      <Handle type="target" position={Position.Left} className="map-handle" />
      <div className="map-node__topline">
        {data.kind === "root" ? <FileText size={13} /> : data.state ? <StateIcon size={12} /> : null}
        <span>{data.eyebrow}</span>
      </div>
      <strong>{data.label}</strong>
      {data.kind === "case" && (
        <div className="map-node__badges">
          {data.priority && <span className={`priority priority--${data.priority.toLowerCase()}`}>{data.priority}</span>}
          {data.tags?.slice(0, 2).map((tag) => <span className="case-tag" key={tag}>{tag}</span>)}
          {data.automated && <span className="automation-badge" title="已绑定自动化用例"><Workflow size={11} />自动化</span>}
        </div>
      )}
      <Handle type="source" position={Position.Right} className="map-handle" />
    </div>
  );
});

const nodeTypes = { caseMap: CaseMapNode };

const edge = (id: string, source: string, target: string): Edge => ({
  id,
  source,
  target,
  type: "smoothstep",
  markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
  style: { stroke: "rgba(171, 186, 181, .34)", strokeWidth: 1.4 },
});

function stateForCase(testCase: TestCase): MapNodeData["state"] {
  if (testCase.status === "通过") return "passed";
  if (testCase.status === "不通过") return "failed";
  if (testCase.status === "跳过") return "skipped";
  if (testCase.status === "堵塞") return "blocked";
  return "pending";
}

function buildGraph(rootLabel: string, testCases: TestCase[]) {
  const grouped = new Map<string, TestCase[]>();
  for (const testCase of testCases) {
    grouped.set(testCase.module, [...(grouped.get(testCase.module) ?? []), testCase]);
  }

  const nodes: MapNode[] = [];
  const edges: Edge[] = [];
  const rowGap = 150;
  let row = 0;

  nodes.push({
    id: "root",
    type: "caseMap",
    position: { x: 30, y: Math.max(40, ((testCases.length - 1) * rowGap) / 2) },
    data: { label: rootLabel, eyebrow: "用例集", kind: "root" },
  });

  [...grouped.entries()].forEach(([moduleName, moduleCases], moduleIndex) => {
    const moduleId = `module-${moduleIndex}`;
    const moduleStartRow = row;
    const moduleCenterRow = moduleStartRow + (moduleCases.length - 1) / 2;
    nodes.push({
      id: moduleId,
      type: "caseMap",
      position: { x: 310, y: moduleCenterRow * rowGap },
      data: {
        label: moduleName,
        eyebrow: `模块 · ${moduleCases.length} 条`,
        kind: "module",
      },
    });
    edges.push(edge(`root-${moduleId}`, "root", moduleId));

    moduleCases.forEach((testCase) => {
      const pointId = `point-${testCase.id}`;
      const caseId = `case-${testCase.id}`;
      const state = stateForCase(testCase);
      nodes.push({
        id: pointId,
        type: "caseMap",
        position: { x: 590, y: row * rowGap },
        data: {
          label: `${testCase.type}场景与校验`,
          eyebrow:
            state === "failed" || state === "blocked"
              ? "测试点 · 需关注"
              : state === "skipped"
                ? "测试点 · 已跳过"
                : "测试点",
          kind: "point",
          state,
        },
      });
      nodes.push({
        id: caseId,
        type: "caseMap",
        position: { x: 890, y: row * rowGap },
        data: {
          label: testCase.title,
          eyebrow: `${testCase.id} · ${testCase.status}`,
          kind: "case",
          state,
          caseId: testCase.id,
          priority: testCase.priority,
          tags: testCase.tags,
          automated: testCase.automated,
        },
      });
      edges.push(
        edge(`${moduleId}-${pointId}`, moduleId, pointId),
        edge(`${pointId}-${caseId}`, pointId, caseId),
      );
      row += 1;
    });
  });

  return { nodes, edges };
}

function MapZoomToolbar() {
  const { fitView, zoomIn, zoomOut, zoomTo } = useReactFlow();
  const { zoom } = useViewport();

  return (
    <div className="map-zoom-toolbar" aria-label="脑图缩放工具">
      <button type="button" aria-label="缩小脑图" title="缩小" onClick={() => void zoomOut({ duration: 180 })}>
        <Minus size={17} />
      </button>
      <span aria-live="polite">{Math.round(zoom * 100)}%</span>
      <button type="button" aria-label="放大脑图" title="放大" onClick={() => void zoomIn({ duration: 180 })}>
        <Plus size={17} />
      </button>
      <i />
      <button type="button" aria-label="适应屏幕" title="适应屏幕" onClick={() => void fitView({ padding: 0.16, duration: 240 })}>
        <Maximize2 size={16} />
      </button>
      <button type="button" aria-label="恢复百分之百" title="恢复 100%" onClick={() => void zoomTo(1, { duration: 200 })}>
        <RotateCcw size={16} />
      </button>
    </div>
  );
}

type MindMapProps = {
  rootLabel: string;
  testCases: TestCase[];
  selectedCaseId: string;
  layoutRevision: number;
  onSelectCase: (id: string) => void;
};

export function MindMap({
  rootLabel,
  testCases,
  selectedCaseId,
  layoutRevision,
  onSelectCase,
}: MindMapProps) {
  const graph = useMemo(() => buildGraph(rootLabel, testCases), [rootLabel, testCases]);
  const nodes = useMemo(
    () => graph.nodes.map((node) => ({ ...node, selected: node.data.caseId === selectedCaseId })),
    [graph.nodes, selectedCaseId],
  );

  return (
    <div className="mind-map" aria-label="用例脑图">
      <ReactFlow
        key={`${rootLabel}-${testCases.length}-${layoutRevision}`}
        nodes={nodes}
        edges={graph.edges}
        nodeTypes={nodeTypes}
        minZoom={0.25}
        maxZoom={2}
        fitView
        fitViewOptions={{ padding: 0.16, minZoom: 0.25, maxZoom: 1 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        zoomOnScroll
        zoomOnPinch
        panOnDrag
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, node) => node.data.caseId && onSelectCase(node.data.caseId)}
      >
        <Background color="rgba(255,255,255,.09)" gap={24} size={1} />
        <MapZoomToolbar />
      </ReactFlow>
    </div>
  );
}
