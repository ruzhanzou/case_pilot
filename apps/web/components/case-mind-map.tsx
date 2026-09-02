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
  kind: "collection" | "module" | "condition" | "case";
  title: string;
  eyebrow: string;
  caseId?: string;
  module?: string;
  condition?: string;
  priority?: TestCaseDto["priority"];
  tags?: string[];
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
        : data.kind === "condition"
          ? ClipboardCheck
          : null;

  return (
    <article
      className={[
        "case-map-node",
        `case-map-node--${data.kind}`,
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
          <button
            type="button"
            aria-label={`编辑用例 ${data.title}`}
            title="编辑用例"
            onClick={(event) => {
              event.stopPropagation();
              data.onEditCase(data.caseId!);
            }}
          >
            <Edit3 size={14} />
          </button>
        ) : data.kind !== "condition" ? (
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
        ) : data.onToggleLeaves ? (
          <button
            type="button"
            aria-label={`${data.leavesHidden ? "显示" : "隐藏"}此前置条件下的叶子用例`}
            title={data.leavesHidden ? "显示叶子用例" : "隐藏叶子用例"}
            onClick={(event) => {
              event.stopPropagation();
              data.onToggleLeaves?.();
            }}
          >
            {data.leavesHidden ? <Eye size={14} /> : <EyeOff size={14} />}
          </button>
        ) : null}
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
  const [hiddenConditionGroups, setHiddenConditionGroups] = useState<Set<string>>(
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

  const toggleConditionLeaves = useCallback((conditionKey: string) => {
    setHiddenConditionGroups((current) => {
      const next = new Set(current);
      if (next.has(conditionKey)) next.delete(conditionKey);
      else next.add(conditionKey);
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
    setHiddenConditionGroups(new Set());
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
    const rowHeight = 132;
    let row = 0;
    const moduleEntries = [...grouped.entries()];
    const getSharedConditionGroups = (moduleCases: TestCaseDto[]) => {
      const counts = new Map<string, number>();
      moduleCases.forEach((testCase) => {
        new Set(testCase.preconditions.map((item) => item.trim()).filter(Boolean))
          .forEach((condition) => counts.set(condition, (counts.get(condition) ?? 0) + 1));
      });
      const sharedConditions = [...counts.entries()]
        .filter(([, count]) => count >= 2)
        .sort((a, b) => b[1] - a[1]);
      const groups = new Map<string, TestCaseDto[]>();
      const ungrouped: TestCaseDto[] = [];
      moduleCases.forEach((testCase) => {
        const matched = sharedConditions.find(([condition]) =>
          testCase.preconditions.some((item) => item.trim() === condition),
        );
        if (!matched) {
          ungrouped.push(testCase);
          return;
        }
        groups.set(matched[0], [...(groups.get(matched[0]) ?? []), testCase]);
      });
      return { groups: [...groups.entries()], ungrouped };
    };
    const moduleStructures = moduleEntries.map(([moduleName, moduleCases]) => ({
      moduleName,
      moduleCases,
      ...getSharedConditionGroups(moduleCases),
    }));
    const totalRows = Math.max(
      moduleStructures.reduce((total, structure) => {
        if (hiddenLeafModules.has(structure.moduleName)) {
          return total + Math.max(structure.groups.length, 1);
        }
        const groupRows = structure.groups.reduce((rows, [condition, groupCases]) => {
          const key = `${structure.moduleName}::${condition}`;
          return rows + (hiddenConditionGroups.has(key) ? 1 : groupCases.length);
        }, 0);
        return total + groupRows + structure.ungrouped.length;
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
      const { moduleName, moduleCases, groups, ungrouped } = structure;
      const moduleId = `module-${moduleIndex}`;
      const leavesHidden = hiddenLeafModules.has(moduleName);
      const moduleStartRow = row;
      const visibleRows = leavesHidden
        ? Math.max(groups.length, 1)
        : groups.reduce((rows, [condition, groupCases]) => {
            const key = `${moduleName}::${condition}`;
            return rows + (hiddenConditionGroups.has(key) ? 1 : groupCases.length);
          }, 0) + ungrouped.length;
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

      const addCaseNode = (testCase: TestCaseDto, parentId: string) => {
        const nodeId = `case-${testCase.id}`;
        nodes.push({
          id: nodeId,
          type: "casePilotNode",
          position: { x: 1040, y: row * rowHeight },
          selected: testCase.id === selectedCaseId,
          data: {
            kind: "case",
            title: testCase.title,
            eyebrow: `${testCase.case_key} · V${testCase.revision_number}`,
            caseId: testCase.id,
            priority: testCase.priority,
            tags: testCase.tags,
            onCreateCase,
            onEditCase: (caseId) => {
              const current = cases.find((item) => item.id === caseId);
              if (current) onEditCase(current);
            },
          },
        });
        edges.push(createEdge(`${parentId}-${nodeId}`, parentId, nodeId));
        row += 1;
      };

      groups.forEach(([condition, groupCases], groupIndex) => {
        const conditionKey = `${moduleName}::${condition}`;
        const conditionId = `${moduleId}-condition-${groupIndex}`;
        const conditionLeavesHidden =
          leavesHidden || hiddenConditionGroups.has(conditionKey);
        const conditionStartRow = row;
        const conditionRows = conditionLeavesHidden ? 1 : groupCases.length;
        nodes.push({
          id: conditionId,
          type: "casePilotNode",
          position: {
            x: 700,
            y: (conditionStartRow + (conditionRows - 1) / 2) * rowHeight,
          },
          data: {
            kind: "condition",
            title: condition,
            module: moduleName === "未分类" ? "" : moduleName,
            condition,
            eyebrow: `${groupCases.length} 条用例共同前置`,
            leavesHidden: conditionLeavesHidden,
            onCreateCase,
            onEditCase: () => undefined,
            onToggleLeaves: () => toggleConditionLeaves(conditionKey),
          },
        });
        edges.push(createEdge(`${moduleId}-${conditionId}`, moduleId, conditionId));
        if (conditionLeavesHidden) row += 1;
        else groupCases.forEach((testCase) => addCaseNode(testCase, conditionId));
      });
      if (!leavesHidden) {
        ungrouped.forEach((testCase) => addCaseNode(testCase, moduleId));
      } else if (!groups.length) {
        row += 1;
      }
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
    hiddenConditionGroups,
    onCreateCase,
    onEditCase,
    selectedCaseId,
    toggleAllLeaves,
    toggleConditionLeaves,
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
          } else if (node.data.kind === "condition") {
            onSelectTarget?.(
              {
                kind: "condition",
                module: node.data.module ?? "",
                condition: node.data.condition ?? node.data.title,
              },
              `前置条件：${node.data.title}`,
            );
          }
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
