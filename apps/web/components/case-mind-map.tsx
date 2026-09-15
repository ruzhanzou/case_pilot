"use client";

import type {
  CaseCollectionDto,
  ConversationTarget,
  TestCaseDto,
} from "@/lib/casepilot-api";
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
import {
  Bot,
  Boxes,
  ClipboardCheck,
  Edit3,
  Eye,
  EyeOff,
  FolderTree,
  Fullscreen,
  Maximize2,
  Minus,
  Minimize2,
  Plus,
  PlusCircle,
  RotateCcw,
} from "lucide-react";
import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

type MindMapNodeData = {
  kind: "collection" | "module" | "case" | "detail";
  detailKind?: "setup" | "procedure" | "validation";
  title: string;
  eyebrow: string;
  caseId?: string;
  module?: string;
  priority?: TestCaseDto["priority"];
  tags?: string[];
  automationType?: TestCaseDto["automation_type"];
  leavesHidden?: boolean;
  onCreateCase: (module?: string) => void;
  onEditCase: (caseId: string) => void;
  onToggleLeaves?: () => void;
};

type MindMapNode = Node<MindMapNodeData, "casePilotNode">;

const MindMapCard = memo(function MindMapCard({
  data,
  selected,
}: NodeProps<MindMapNode>) {
  const KindIcon =
    data.kind === "collection"
      ? FolderTree
      : data.kind === "module"
        ? Boxes
        : data.kind === "detail"
          ? ClipboardCheck
          : null;

  return (
    <article
      className={[
        "case-map-node",
        `case-map-node--${data.kind}`,
        data.detailKind ? `case-map-node--${data.detailKind}` : "",
        selected ? "is-selected" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <Handle type="target" position={Position.Left} />
      <div className="case-map-node__meta">
        <span>
          {KindIcon && <KindIcon size={13} />}
          {data.eyebrow}
        </span>
        {data.kind === "case" && data.caseId ? (
          <div className="case-map-node__actions">
            {data.onToggleLeaves && (
              <button
                type="button"
                aria-label={`${data.leavesHidden ? "展开" : "收起"}${data.title}的结构节点`}
                title={data.leavesHidden ? "展开用例结构" : "收起用例结构"}
                onClick={(event) => {
                  event.stopPropagation();
                  data.onToggleLeaves?.();
                }}
              >
                {data.leavesHidden ? <Eye size={14} /> : <EyeOff size={14} />}
              </button>
            )}
            <button
              type="button"
              aria-label={`修改用例标题 ${data.title}`}
              title="修改用例"
              onClick={(event) => {
                event.stopPropagation();
                data.onEditCase(data.caseId!);
              }}
            >
              <Edit3 size={14} />
            </button>
          </div>
        ) : data.kind === "detail" && data.caseId ? (
          <button
            type="button"
            aria-label={`修改${data.eyebrow} ${data.title}`}
            title="修改此节点"
            onClick={(event) => {
              event.stopPropagation();
              data.onEditCase(data.caseId!);
            }}
          >
            <Edit3 size={14} />
          </button>
        ) : (
          <div className="case-map-node__actions">
            {data.onToggleLeaves && (
              <button
                type="button"
                aria-label={`${data.leavesHidden ? "显示" : "隐藏"}${data.title}下的叶子用例`}
                title={data.leavesHidden ? "显示叶子用例" : "隐藏叶子用例"}
                onClick={(event) => {
                  event.stopPropagation();
                  data.onToggleLeaves?.();
                }}
              >
                {data.leavesHidden ? <Eye size={14} /> : <EyeOff size={14} />}
              </button>
            )}
            <button
              type="button"
              aria-label={`在${data.title}下新增用例`}
              title="新增用例"
              onClick={(event) => {
                event.stopPropagation();
                data.onCreateCase(data.module);
              }}
            >
              <PlusCircle size={15} />
            </button>
          </div>
        )}
      </div>
      <strong title={data.title}>{data.title}</strong>
      {data.kind === "case" && (
        <footer>
          {data.priority && (
            <span className={`priority-badge priority-badge--${data.priority.toLowerCase()}`}>
              {data.priority}
            </span>
          )}
          {data.tags?.slice(0, 2).map((tag) => <span key={tag}>{tag}</span>)}
          {data.automationType === "automated" && (
            <span className="automation-badge" title="该用例已绑定自动化用例">
              <Bot size={11} /> 已绑定自动化
            </span>
          )}
        </footer>
      )}
      <Handle type="source" position={Position.Right} />
    </article>
  );
});

const nodeTypes = { casePilotNode: MindMapCard };

function createEdge(id: string, source: string, target: string): Edge {
  return {
    id,
    source,
    target,
    type: "smoothstep",
    markerEnd: {
      type: MarkerType.ArrowClosed,
      width: 14,
      height: 14,
      color: "#9db2cc",
    },
    style: { stroke: "#b8c8dc", strokeWidth: 1.4 },
  };
}

function MapControls({
  allLeavesHidden,
  onToggleAllLeaves,
}: {
  allLeavesHidden: boolean;
  onToggleAllLeaves: () => void;
}) {
  const { fitView, zoomIn, zoomOut, zoomTo } = useReactFlow();
  const { zoom } = useViewport();

  return (
    <div className="case-map-controls" aria-label="脑图缩放工具">
      <button type="button" aria-label="缩小脑图" onClick={() => void zoomOut({ duration: 160 })}>
        <Minus size={17} />
      </button>
      <span>{Math.round(zoom * 100)}%</span>
      <button type="button" aria-label="放大脑图" onClick={() => void zoomIn({ duration: 160 })}>
        <Plus size={17} />
      </button>
      <i />
      <button type="button" aria-label="适应画布" onClick={() => void fitView({ padding: 0.18, duration: 220 })}>
        <Maximize2 size={16} />
      </button>
      <button type="button" aria-label="恢复百分之百" onClick={() => void zoomTo(1, { duration: 180 })}>
        <RotateCcw size={16} />
      </button>
      <i />
      <button
        type="button"
        aria-label={allLeavesHidden ? "显示全部叶子用例" : "一键隐藏全部叶子用例"}
        title={allLeavesHidden ? "显示全部叶子" : "一键隐藏全部叶子"}
        onClick={onToggleAllLeaves}
      >
        {allLeavesHidden ? <Eye size={16} /> : <EyeOff size={16} />}
      </button>
    </div>
  );
}

function FullscreenControl({
  isFullscreen,
  onToggleFullscreen,
}: {
  isFullscreen: boolean;
  onToggleFullscreen: () => Promise<void>;
}) {
  const { fitView } = useReactFlow();

  return (
    <button
      type="button"
      className="case-map-fullscreen-button"
      aria-label={isFullscreen ? "退出脑图全屏" : "进入脑图全屏"}
      title={isFullscreen ? "退出全屏" : "全屏查看脑图"}
      onClick={() => {
        void onToggleFullscreen().then(() => {
          window.requestAnimationFrame(() => {
            void fitView({ padding: 0.12, duration: 220 });
          });
        });
      }}
    >
      {isFullscreen ? <Minimize2 size={16} /> : <Fullscreen size={16} />}
      {isFullscreen ? "退出全屏" : "全屏查看"}
    </button>
  );
}

type CaseMindMapProps = {
  collection: CaseCollectionDto;
  cases: TestCaseDto[];
  selectedCaseId: string;
  onSelectCase: (caseId: string) => void;
  onCreateCase: (module?: string) => void;
  onEditCase: (testCase: TestCaseDto) => void;
  onSelectTarget?: (target: ConversationTarget, label: string) => void;
};

export function CaseMindMap({
  collection,
  cases,
  selectedCaseId,
  onSelectCase,
  onCreateCase,
  onEditCase,
  onSelectTarget,
}: CaseMindMapProps) {
  const mapRef = useRef<HTMLDivElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [hiddenLeafModules, setHiddenLeafModules] = useState<Set<string>>(
    () => new Set(),
  );
  const [hiddenCaseDetails, setHiddenCaseDetails] = useState<Set<string>>(
    () => new Set(),
  );
  const moduleNames = useMemo(
    () => [...new Set(cases.map((testCase) => testCase.module.trim() || "未分类"))],
    [cases],
  );
  const allLeavesHidden =
    moduleNames.length > 0 &&
    moduleNames.every((moduleName) => hiddenLeafModules.has(moduleName));

  const toggleModuleLeaves = useCallback((moduleName: string) => {
    setHiddenLeafModules((current) => {
      const next = new Set(current);
      if (next.has(moduleName)) next.delete(moduleName);
      else next.add(moduleName);
      return next;
    });
  }, []);

  const toggleCaseDetails = useCallback((caseId: string) => {
    setHiddenCaseDetails((current) => {
      const next = new Set(current);
      if (next.has(caseId)) next.delete(caseId);
      else next.add(caseId);
      return next;
    });
  }, []);

  const toggleAllLeaves = useCallback(() => {
    setHiddenLeafModules((current) => {
      const currentlyAllHidden =
        moduleNames.length > 0 &&
        moduleNames.every((moduleName) => current.has(moduleName));
      return currentlyAllHidden ? new Set() : new Set(moduleNames);
    });
    setHiddenCaseDetails(new Set());
  }, [moduleNames]);

  useEffect(() => {
    const syncFullscreenState = () => {
      setIsFullscreen(document.fullscreenElement === mapRef.current);
    };
    const exitFallbackFullscreen = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !document.fullscreenElement) {
        setIsFullscreen(false);
      }
    };
    document.addEventListener("fullscreenchange", syncFullscreenState);
    document.addEventListener("keydown", exitFallbackFullscreen);
    return () => {
      document.removeEventListener("fullscreenchange", syncFullscreenState);
      document.removeEventListener("keydown", exitFallbackFullscreen);
    };
  }, []);

  const toggleFullscreen = useCallback(async () => {
    if (document.fullscreenElement === mapRef.current) {
      await document.exitFullscreen();
      return;
    }
    if (isFullscreen && !document.fullscreenElement) {
      setIsFullscreen(false);
      return;
    }
    if (mapRef.current?.requestFullscreen) {
      try {
        await mapRef.current.requestFullscreen();
        return;
      } catch {
        setIsFullscreen(true);
        return;
      }
    }
    setIsFullscreen(true);
  }, [isFullscreen]);

  const graph = useMemo(() => {
    const grouped = new Map<string, TestCaseDto[]>();
    cases.forEach((testCase) => {
      const moduleName = testCase.module.trim() || "未分类";
      grouped.set(moduleName, [...(grouped.get(moduleName) ?? []), testCase]);
    });

    const nodes: MindMapNode[] = [];
    const edges: Edge[] = [];
    const rowHeight = 118;
    let row = 0;
    const moduleEntries = [...grouped.entries()];
    const moduleStructures = moduleEntries.map(([moduleName, moduleCases]) => ({
      moduleName,
      moduleCases,
    }));
    const totalRows = Math.max(
      moduleStructures.reduce((total, structure) => {
        return total + structure.moduleCases.reduce(
          (rows, testCase) =>
            rows +
            (hiddenLeafModules.has(structure.moduleName) ||
            hiddenCaseDetails.has(testCase.id)
              ? 1
              : 3),
          0,
        );
      }, 0),
      1,
    );
    const rootY = Math.max(40, ((totalRows - 1) * rowHeight) / 2);

    nodes.push({
      id: "collection-root",
      type: "casePilotNode",
      position: { x: 40, y: rootY },
      data: {
        kind: "collection",
        title: collection.name,
        eyebrow: `${cases.length} 条用例`,
        leavesHidden: allLeavesHidden,
        onCreateCase,
        onEditCase: (caseId) => {
          const testCase = cases.find((item) => item.id === caseId);
          if (testCase) onEditCase(testCase);
        },
        onToggleLeaves: cases.length ? toggleAllLeaves : undefined,
      },
    });

    if (!moduleEntries.length) {
      nodes.push({
        id: "empty-module",
        type: "casePilotNode",
        position: { x: 360, y: 40 },
        data: {
          kind: "module",
          title: "创建第一个模块",
          eyebrow: "暂无用例",
          onCreateCase,
          onEditCase: () => undefined,
        },
      });
      edges.push(createEdge("root-empty", "collection-root", "empty-module"));
    }

    moduleStructures.forEach((structure, moduleIndex) => {
      const { moduleName, moduleCases } = structure;
      const moduleId = `module-${moduleIndex}`;
      const leavesHidden = hiddenLeafModules.has(moduleName);
      const moduleStartRow = row;
      const visibleRows = leavesHidden
        ? moduleCases.length
        : moduleCases.reduce(
            (rows, testCase) =>
              rows + (hiddenCaseDetails.has(testCase.id) ? 1 : 3),
            0,
          );
      const moduleCenterRow = moduleStartRow + (visibleRows - 1) / 2;
      nodes.push({
        id: moduleId,
        type: "casePilotNode",
        position: { x: 360, y: moduleCenterRow * rowHeight },
        data: {
          kind: "module",
          title: moduleName,
          eyebrow: `${moduleCases.length} 条用例`,
          module: moduleName === "未分类" ? "" : moduleName,
          leavesHidden,
          onCreateCase,
          onEditCase: () => undefined,
          onToggleLeaves: () => toggleModuleLeaves(moduleName),
        },
      });
      edges.push(createEdge(`root-${moduleId}`, "collection-root", moduleId));

      const addCaseNode = (testCase: TestCaseDto) => {
        const nodeId = `case-${testCase.id}`;
        const detailsHidden = leavesHidden || hiddenCaseDetails.has(testCase.id);
        const detailRows = detailsHidden ? 1 : 3;
        const caseStartRow = row;
        nodes.push({
          id: nodeId,
          type: "casePilotNode",
          position: {
            x: 700,
            y: (caseStartRow + (detailRows - 1) / 2) * rowHeight,
          },
          selected: testCase.id === selectedCaseId,
          data: {
            kind: "case",
            title: testCase.title,
            eyebrow: `title · ${testCase.case_key} · V${testCase.revision_number}`,
            caseId: testCase.id,
            priority: testCase.priority,
            tags: testCase.tags,
            automationType: testCase.automation_type,
            leavesHidden: detailsHidden,
            onCreateCase,
            onEditCase: (caseId) => {
              const current = cases.find((item) => item.id === caseId);
              if (current) onEditCase(current);
            },
            onToggleLeaves: () => toggleCaseDetails(testCase.id),
          },
        });
        edges.push(createEdge(`${moduleId}-${nodeId}`, moduleId, nodeId));

        if (detailsHidden) {
          row += 1;
          return;
        }

        const details = [
          {
            kind: "setup" as const,
            eyebrow: "test_setup",
            title: testCase.preconditions.length
              ? testCase.preconditions
                  .map((item, index) => `${index + 1}. ${item}`)
                  .join("\n")
              : "无前置条件",
          },
          {
            kind: "procedure" as const,
            eyebrow: "test_procedure",
            title: testCase.steps
              .map((step, index) => `${index + 1}. ${step.action}`)
              .join("\n"),
          },
          {
            kind: "validation" as const,
            eyebrow: "test_validation",
            title: testCase.steps
              .map((step, index) => `${index + 1}. ${step.expected}`)
              .join("\n"),
          },
        ];
        details.forEach((detail, detailIndex) => {
          const detailId = `${nodeId}-${detail.kind}`;
          nodes.push({
            id: detailId,
            type: "casePilotNode",
            position: {
              x: 1040,
              y: (caseStartRow + detailIndex) * rowHeight,
            },
            data: {
              kind: "detail",
              detailKind: detail.kind,
              title: detail.title,
              eyebrow: detail.eyebrow,
              caseId: testCase.id,
              module: testCase.module,
              onCreateCase,
              onEditCase: (caseId) => {
                const current = cases.find((item) => item.id === caseId);
                if (current) onEditCase(current);
              },
            },
          });
          edges.push(createEdge(`${nodeId}-${detail.kind}`, nodeId, detailId));
        });
        row += 3;
      };

      moduleCases.forEach(addCaseNode);
    });

    return {
      nodes,
      edges,
      viewport: {
        x: 42,
        y: Math.min(180, 210 - rootY * 0.78),
        zoom: 0.78,
      },
    };
  }, [
    cases,
    collection.name,
    allLeavesHidden,
    hiddenLeafModules,
    hiddenCaseDetails,
    onCreateCase,
    onEditCase,
    selectedCaseId,
    toggleAllLeaves,
    toggleCaseDetails,
    toggleModuleLeaves,
  ]);

  return (
    <div
      ref={mapRef}
      className={isFullscreen ? "case-mind-map is-fullscreen" : "case-mind-map"}
      aria-label={`${collection.name} 用例脑图`}
    >
      <ReactFlow
        nodes={graph.nodes}
        edges={graph.edges}
        nodeTypes={nodeTypes}
        defaultViewport={graph.viewport}
        minZoom={0.35}
        maxZoom={1.8}
        nodesConnectable={false}
        nodesDraggable
        zoomOnScroll={false}
        zoomOnPinch
        panOnScroll
        panOnDrag
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, node) => {
          if (node.data.caseId) {
            onSelectCase(node.data.caseId);
            onSelectTarget?.(
              { kind: "case", case_ids: [node.data.caseId] },
              node.data.title,
            );
          } else if (node.data.kind === "module") {
            onSelectTarget?.(
              { kind: "module", module: node.data.module ?? "" },
              `模块：${node.data.title}`,
            );
          }
        }}
        onNodeDoubleClick={(_, node) => {
          if (!node.data.caseId) return;
          const testCase = cases.find((item) => item.id === node.data.caseId);
          if (testCase) onEditCase(testCase);
        }}
      >
        <Background color="#cfdaea" gap={22} size={1} />
        <MapControls
          allLeavesHidden={allLeavesHidden}
          onToggleAllLeaves={toggleAllLeaves}
        />
        <FullscreenControl
          isFullscreen={isFullscreen}
          onToggleFullscreen={toggleFullscreen}
        />
      </ReactFlow>
    </div>
  );
}
