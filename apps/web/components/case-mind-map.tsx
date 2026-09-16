"use client";

import type {
  CaseCollectionDto,
  ConversationTarget,
  TestCaseDto,
  TestCaseInput,
} from "@/lib/casepilot-api";
import { useI18n } from "@/lib/i18n";
import {
  Background,
  Handle,
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
  Sparkles,
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
  isRewriteTarget?: boolean;
  showRewriteBadge?: boolean;
  rewriteStatus?: "selected" | "running" | "review" | "applied";
  onCreateCase: (module?: string) => void;
  onEditCase: (caseId: string) => void;
  onSaveText?: (value: string) => Promise<void>;
  onToggleLeaves?: () => void;
};

type MindMapNode = Node<MindMapNodeData, "casePilotNode">;
const emptyRewriteTargets: ConversationTarget[] = [];

const MindMapCard = memo(function MindMapCard({
  data,
  selected,
}: NodeProps<MindMapNode>) {
  const { pick } = useI18n();
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const cancelingRef = useRef(false);
  const KindIcon =
    data.kind === "collection"
      ? FolderTree
      : data.kind === "module"
        ? Boxes
        : data.kind === "detail"
          ? ClipboardCheck
          : null;

  const cancelEditing = (editor: HTMLTextAreaElement) => {
    cancelingRef.current = true;
    editor.value = data.title;
    setSaveError("");
    editor.blur();
    window.requestAnimationFrame(() => {
      cancelingRef.current = false;
    });
  };

  const saveText = async (draft: string) => {
    if (saving || cancelingRef.current) return;
    const value = draft.trim();
    if (!value) {
      setSaveError(pick("Content cannot be empty", "内容不能为空"));
      window.requestAnimationFrame(() => editorRef.current?.focus());
      return;
    }
    if (value === data.title.trim()) {
      return;
    }
    setSaving(true);
    setSaveError("");
    try {
      await data.onSaveText?.(value);
    } catch (caught) {
      setSaveError(caught instanceof Error ? caught.message : pick("Save failed. Try again.", "保存失败，请重试"));
      window.requestAnimationFrame(() => editorRef.current?.focus());
    } finally {
      setSaving(false);
    }
  };

  const canQuickAdd = data.kind !== "detail";
  const quickAddLabel =
    data.kind === "case"
      ? pick(`Add a test case after ${data.title}`, `在${data.title}后新增同模块用例`)
      : pick(`Add a test case under ${data.title}`, `在${data.title}下新增用例`);
  const rewriteLabel =
    data.rewriteStatus === "running"
      ? pick("AI rewriting", "AI 改写中")
      : data.rewriteStatus === "review"
        ? pick("Awaiting review", "等待审阅")
        : data.rewriteStatus === "applied"
          ? pick("Updated", "已更新")
          : pick("Selected", "已选目标");

  return (
    <article
      className={[
        "case-map-node",
        `case-map-node--${data.kind}`,
        data.detailKind ? `case-map-node--${data.detailKind}` : "",
        selected ? "is-selected" : "",
        data.isRewriteTarget ? "is-ai-target" : "",
        data.rewriteStatus ? `is-ai-${data.rewriteStatus}` : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <Handle type="target" position={Position.Left} />
      <div className="case-map-node__meta">
        <span>
          {KindIcon && <KindIcon size={13} />}
          {data.eyebrow}
          {data.showRewriteBadge && (
            <em className="case-map-node__rewrite-state">
              <Sparkles size={10} /> {rewriteLabel}
            </em>
          )}
        </span>
        {data.kind === "case" && data.caseId ? (
          <div className="case-map-node__actions">
            {data.onToggleLeaves && (
              <button
                type="button"
                aria-label={pick(`${data.leavesHidden ? "Expand" : "Collapse"} the structure for ${data.title}`, `${data.leavesHidden ? "展开" : "收起"}${data.title}的结构节点`)}
                title={data.leavesHidden ? pick("Expand case structure", "展开用例结构") : pick("Collapse case structure", "收起用例结构")}
                onClick={(event) => {
                  event.stopPropagation();
                  data.onToggleLeaves?.();
                }}
              >
                {data.leavesHidden ? <Eye size={14} /> : <EyeOff size={14} />}
              </button>
            )}
          </div>
        ) : data.kind !== "detail" ? (
          <div className="case-map-node__actions">
            {data.onToggleLeaves && (
              <button
                type="button"
                aria-label={pick(`${data.leavesHidden ? "Show" : "Hide"} leaf cases under ${data.title}`, `${data.leavesHidden ? "显示" : "隐藏"}${data.title}下的叶子用例`)}
                title={data.leavesHidden ? pick("Show leaf cases", "显示叶子用例") : pick("Hide leaf cases", "隐藏叶子用例")}
                onClick={(event) => {
                  event.stopPropagation();
                  data.onToggleLeaves?.();
                }}
              >
                {data.leavesHidden ? <Eye size={14} /> : <EyeOff size={14} />}
              </button>
            )}
          </div>
        ) : null}
      </div>
      {data.onSaveText ? (
        <div className="case-map-node__inline-editor nodrag nowheel">
          <textarea
            key={`${data.caseId}-${data.eyebrow}-${data.title}`}
            ref={editorRef}
            aria-label={pick(`Edit ${data.eyebrow} inline`, `直接编辑${data.eyebrow}`)}
            defaultValue={data.title}
            rows={data.kind === "detail" ? 3 : 1}
            disabled={saving}
            onClick={(event) => event.stopPropagation()}
            onPointerDown={(event) => event.stopPropagation()}
            onKeyDown={(event) => {
              event.stopPropagation();
              if (event.key === "Escape") {
                event.preventDefault();
                cancelEditing(event.currentTarget);
              } else if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.blur();
              }
            }}
            onBlur={(event) => void saveText(event.currentTarget.value)}
          />
          {saveError && <span role="alert">{saveError}</span>}
          <small>{saving ? pick("Saving…", "正在保存…") : pick("Type directly · Enter to save · Esc to cancel", "直接输入 · Enter 保存 · Esc 取消")}</small>
        </div>
      ) : data.caseId ? (
        <button
          type="button"
          className="case-map-node__text nodrag"
          aria-label={pick(`Open the full editor for ${data.title}`, `打开${data.title}的完整编辑器`)}
          title={pick("Open full editor", "打开完整编辑器")}
          onClick={(event) => {
            event.stopPropagation();
            data.onEditCase(data.caseId!);
          }}
        >
          {data.title}
        </button>
      ) : (
        <strong className="case-map-node__static-text" title={data.title}>
          {data.title}
        </strong>
      )}
      {data.kind === "case" && (
        <footer>
          {data.priority && (
            <span className={`priority-badge priority-badge--${data.priority.toLowerCase()}`}>
              {data.priority}
            </span>
          )}
          {data.tags?.slice(0, 2).map((tag) => <span key={tag}>{tag}</span>)}
          {data.automationType === "automated" && (
            <span className="automation-badge" title={pick("This case is linked to automation", "该用例已绑定自动化用例")}>
              <Bot size={11} /> {pick("Automated", "已绑定自动化")}
            </span>
          )}
        </footer>
      )}
      {canQuickAdd && (
        <button
          type="button"
          className="case-map-node__quick-add nodrag"
          aria-label={quickAddLabel}
          title={data.kind === "case" ? pick("Add sibling test case", "新增同级用例") : pick("Add test case", "新增用例")}
          onClick={(event) => {
            event.stopPropagation();
            data.onCreateCase(data.module);
          }}
        >
          <PlusCircle size={17} />
        </button>
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
    style: { stroke: "#aebfd4", strokeWidth: 1.6 },
  };
}

function MapControls({
  allLeavesHidden,
  onToggleAllLeaves,
}: {
  allLeavesHidden: boolean;
  onToggleAllLeaves: () => void;
}) {
  const { pick } = useI18n();
  const { fitView, zoomIn, zoomOut, zoomTo } = useReactFlow();
  const { zoom } = useViewport();

  return (
    <div className="case-map-controls" aria-label={pick("Mind map zoom controls", "脑图缩放工具")}>
      <button type="button" aria-label={pick("Zoom out", "缩小脑图")} onClick={() => void zoomOut({ duration: 160 })}>
        <Minus size={17} />
      </button>
      <span>{Math.round(zoom * 100)}%</span>
      <button type="button" aria-label={pick("Zoom in", "放大脑图")} onClick={() => void zoomIn({ duration: 160 })}>
        <Plus size={17} />
      </button>
      <i />
      <button type="button" aria-label={pick("Fit to canvas", "适应画布")} onClick={() => void fitView({ padding: 0.18, duration: 220 })}>
        <Maximize2 size={16} />
      </button>
      <button type="button" aria-label={pick("Reset to 100 percent", "恢复百分之百")} onClick={() => void zoomTo(1, { duration: 180 })}>
        <RotateCcw size={16} />
      </button>
      <i />
      <button
        type="button"
        aria-label={allLeavesHidden ? pick("Show all leaf cases", "显示全部叶子用例") : pick("Hide all leaf cases", "一键隐藏全部叶子用例")}
        title={allLeavesHidden ? pick("Show all leaves", "显示全部叶子") : pick("Hide all leaves", "一键隐藏全部叶子")}
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
  const { pick } = useI18n();
  const { fitView } = useReactFlow();

  return (
    <button
      type="button"
      className="case-map-fullscreen-button"
      aria-label={isFullscreen ? pick("Exit mind map fullscreen", "退出脑图全屏") : pick("Enter mind map fullscreen", "进入脑图全屏")}
      title={isFullscreen ? pick("Exit fullscreen", "退出全屏") : pick("View mind map fullscreen", "全屏查看脑图")}
      onClick={() => {
        void onToggleFullscreen().then(() => {
          window.requestAnimationFrame(() => {
            void fitView({ padding: 0.12, duration: 220 });
          });
        });
      }}
    >
      {isFullscreen ? <Minimize2 size={16} /> : <Fullscreen size={16} />}
      {isFullscreen ? pick("Exit fullscreen", "退出全屏") : pick("Fullscreen", "全屏查看")}
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
  onSaveCase?: (testCase: TestCaseDto, input: TestCaseInput) => Promise<void>;
  onSelectTarget?: (target: ConversationTarget, label: string) => void;
  rewriteTargets?: ConversationTarget[];
  rewriteStatus?: "idle" | "selected" | "running" | "review" | "applied";
};

export function CaseMindMap({
  collection,
  cases,
  selectedCaseId,
  onSelectCase,
  onCreateCase,
  onEditCase,
  onSaveCase,
  onSelectTarget,
  rewriteTargets = emptyRewriteTargets,
  rewriteStatus = "idle",
}: CaseMindMapProps) {
  const { pick } = useI18n();
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
  const isModuleRewriteTarget = useCallback(
    (moduleName: string) =>
      rewriteTargets.some(
        (target) =>
          target.kind === "module" &&
          (target.module ?? "") === (moduleName === "未分类" ? "" : moduleName),
      ),
    [rewriteTargets],
  );
  const isCaseRewriteTarget = useCallback(
    (testCase: TestCaseDto) =>
      rewriteTargets.some(
        (target) =>
          (target.kind === "case" && target.case_ids?.includes(testCase.id)) ||
          (target.kind === "module" &&
            (target.module ?? "") === (testCase.module.trim() || "")),
      ),
    [rewriteTargets],
  );

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

  const saveNodeText = useCallback(
    async (
      testCase: TestCaseDto,
      field: "title" | "setup" | "procedure" | "validation",
      value: string,
    ) => {
      if (!onSaveCase) return;
      const lines = value
        .split("\n")
        .map((line) => line.replace(/^\s*\d+[.、]\s*/, "").trim())
        .filter(Boolean);
      if (field !== "title" && !lines.length) {
        throw new Error(pick("Keep at least one item", "至少保留一条内容"));
      }
      if (
        (field === "procedure" || field === "validation") &&
        lines.length !== testCase.steps.length
      ) {
        throw new Error(pick("The step count must stay the same. Use the full editor to add or remove steps.", "步骤数量需保持不变；增删步骤请打开完整编辑器"));
      }
      await onSaveCase(testCase, {
        case_key: testCase.case_key,
        title: field === "title" ? value : testCase.title,
        module: testCase.module,
        priority: testCase.priority,
        case_type: testCase.case_type,
        tags: testCase.tags,
        preconditions: field === "setup" ? lines : testCase.preconditions,
        steps: testCase.steps.map((step, index) => ({
          id: step.id,
          action: field === "procedure" ? lines[index] : step.action,
          expected: field === "validation" ? lines[index] : step.expected,
        })),
        source: testCase.source,
        source_refs: testCase.source_refs,
      });
    },
    [onSaveCase, pick],
  );

  const graph = useMemo(() => {
    const grouped = new Map<string, TestCaseDto[]>();
    cases.forEach((testCase) => {
      const moduleName = testCase.module.trim() || "未分类";
      grouped.set(moduleName, [...(grouped.get(moduleName) ?? []), testCase]);
    });

    const nodes: MindMapNode[] = [];
    const edges: Edge[] = [];
    const rowHeight = 144;
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
        eyebrow: pick(`${cases.length} test cases`, `${cases.length} 条用例`),
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
          title: pick("Create the first module", "创建第一个模块"),
          eyebrow: pick("No test cases", "暂无用例"),
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
      const moduleTargeted = isModuleRewriteTarget(moduleName);
      nodes.push({
        id: moduleId,
        type: "casePilotNode",
        position: { x: 360, y: moduleCenterRow * rowHeight },
        data: {
          kind: "module",
          title: moduleName,
          eyebrow: pick(`${moduleCases.length} test cases`, `${moduleCases.length} 条用例`),
          module: moduleName === "未分类" ? "" : moduleName,
          leavesHidden,
          isRewriteTarget: moduleTargeted,
          showRewriteBadge: moduleTargeted,
          rewriteStatus:
            moduleTargeted && rewriteStatus !== "idle" ? rewriteStatus : undefined,
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
        const caseTargeted = isCaseRewriteTarget(testCase);
        const directCaseTargeted = rewriteTargets.some(
          (target) =>
            target.kind === "case" && target.case_ids?.includes(testCase.id),
        );
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
            module: testCase.module,
            leavesHidden: detailsHidden,
            isRewriteTarget: caseTargeted,
            showRewriteBadge: directCaseTargeted,
            rewriteStatus:
              caseTargeted && rewriteStatus !== "idle" ? rewriteStatus : undefined,
            onCreateCase,
            onEditCase: (caseId) => {
              const current = cases.find((item) => item.id === caseId);
              if (current) onEditCase(current);
            },
            onToggleLeaves: () => toggleCaseDetails(testCase.id),
            onSaveText: onSaveCase
              ? (value) => saveNodeText(testCase, "title", value)
              : undefined,
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
              : pick("No preconditions", "无前置条件"),
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
              isRewriteTarget: caseTargeted,
              rewriteStatus:
                caseTargeted && rewriteStatus !== "idle"
                  ? rewriteStatus
                  : undefined,
              onCreateCase,
              onEditCase: (caseId) => {
                const current = cases.find((item) => item.id === caseId);
                if (current) onEditCase(current);
              },
              onSaveText: onSaveCase
                ? (value) => saveNodeText(testCase, detail.kind, value)
                : undefined,
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
    isCaseRewriteTarget,
    isModuleRewriteTarget,
    onCreateCase,
    onEditCase,
    onSaveCase,
    pick,
    rewriteStatus,
    rewriteTargets,
    saveNodeText,
    selectedCaseId,
    toggleAllLeaves,
    toggleCaseDetails,
    toggleModuleLeaves,
  ]);

  return (
    <div
      ref={mapRef}
      className={[
        "case-mind-map",
        isFullscreen ? "is-fullscreen" : "",
        rewriteStatus === "running" ? "is-ai-rewriting" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      aria-label={pick(`${collection.name} test case mind map`, `${collection.name} 用例脑图`)}
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
            const selectedCase = cases.find(
              (item) => item.id === node.data.caseId,
            );
            onSelectTarget?.(
              { kind: "case", case_ids: [node.data.caseId] },
              selectedCase?.title ?? node.data.title,
            );
          } else if (node.data.kind === "module") {
            onSelectTarget?.(
              { kind: "module", module: node.data.module ?? "" },
              pick(`Module: ${node.data.title}`, `模块：${node.data.title}`),
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
