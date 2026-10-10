"use client";

import { ConversationAttachments } from "@/components/conversation-attachments";
import { planningModuleAliases } from "@/lib/case-module-tree";

import { summarizeWorkflowStages } from "@/lib/workflow-stages";
import { CaseContentFields } from "@/components/case-content-fields";
import { CaseTaskArtifacts } from "@/components/case-task-artifacts";
import { ConversationTaskFlow } from "@/components/conversation-task-flow";
import { CaseTaskWorkspace } from "@/components/case-task-workspace";
import { candidatesForTask, workspaceTasks, workspaceIsRunning, shouldResumePendingTask, taskScopeChanged, nextWorkspaceOperation, type WorkspaceTask } from "@/lib/workspace-tasks";
import { TestPlanningMap } from "@/components/test-planning-map";
import { CaseMindMap } from "@/components/case-mind-map";
import { CaseCollectionChanges } from "@/components/case-collection-changes";
import { CaseEditorDialog } from "@/components/case-editor-dialog";
import { CaseReviewPlan, type CaseReviewReport, type CaseReviewFinding } from "@/components/case-review-plan";
import {
  CollectionStatusBadge,
  collectionStatusFromPhase,
} from "@/components/collection-status-badge";
import {
  applyCaseChangeSet,
  cancelGeneration,
  commitWorkspaceCandidates,
  confirmConversationIntent,
  confirmTestBrief,
  saveTestBrief,
  downloadTestBrief,
  getCaseChangeSet,
  getConversation,
  getOrCreateWorkspace,
  listGenerationModels,
  rejectCaseChangeSet,
  retryConversationMessage,
  retryGeneration,
  resumeConversationOperation,
  sendConversationMessage,
  saveTaskReview,
  type TaskReviewDecisions,
  updateWorkspaceCandidate,
  updateWorkspaceState,
  uploadConversationAttachments,
  waitForKnowledgeSource,
  watchGeneration,
  type AgentModelId,
  type CaseChangeSetDto,
  type CaseCollectionDto,
  type ConversationDto,
  type ConversationIntent,
  type ConversationTarget,
  type GenerationStage,
  type TestCaseDto,
  type TestCaseInput,
  type WorkspaceCandidateDto,
} from "@/lib/casepilot-api";
import { useI18n } from "@/lib/i18n";
import {
  Bot,
  Check,
  CheckCircle2,
  CircleAlert,
  Copy,
  Download,
  FileUp,
  GitFork,
  History,
  List,
  LoaderCircle,
  MessageSquarePlus,
  PanelRight,
  Paperclip,
  Pencil,
  Save,
  Send,
  Sparkles,
  Square,
  X,
} from "lucide-react";
import {
  Activity,
  type CSSProperties,
  type ChangeEvent,
  type FormEvent,
  type PointerEvent as ReactPointerEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Streamdown } from "streamdown";
import { useStickToBottom } from "use-stick-to-bottom";

type CaseWorkbenchProps = {
  spaceId: string;
  spaceName: string;
  selectedCollection: CaseCollectionDto | null;
  cases: TestCaseDto[];
  loading: boolean;
  conversationId?: string;
  pendingOperationId?: string;
  onSelectCase: (caseId: string) => void;
  onCreateCase: (module?: string) => void;
  onCreateCaseInline: (input: TestCaseInput) => Promise<void>;
  onEditCase: (testCase: TestCaseDto) => void;
  onSaveCase: (testCase: TestCaseDto, input: TestCaseInput) => Promise<void>;
  onCasesChanged: () => Promise<void>;
  onImportCases: (
    collectionId: string,
    inputs: TestCaseInput[],
  ) => Promise<TestCaseDto[]>;
  onOpenLibrary: () => void;
  onNewConversation: () => void;
  onContinueInNewConversation: (
    operationId: string,
    collectionId: string,
  ) => Promise<void>;
  onCancelOperation: (operationId: string) => Promise<void>;
  onOpenHistory: () => void;
  onDirtyChange?: (dirty: boolean) => void;
};

const intentLabels: Record<ConversationIntent, string> = {
  CASE_GENERATE: "生成用例",
  CASE_MODIFY: "修改用例",
  CASE_DELETE: "删除用例",
  CASE_QUERY: "查询用例",
  CASE_REVIEW: "评审用例",
  CASE_DEDUP: "检查冗余",
  COVERAGE_ANALYZE: "分析覆盖缺口",
  KNOWLEDGE_QA: "知识问答",
  SMALL_TALK: "CasePilot",
  UNRESOLVED: "补充说明",
};

const intentActionLabels: Record<ConversationIntent, string> = {
  ...intentLabels,
  SMALL_TALK: "日常对话",
};
const actionableIntents = Object.keys(intentLabels).filter((intent) => intent !== "UNRESOLVED") as ConversationIntent[];

const phaseLabels: Record<string, string> = {
  idle: "等待需求",
  brief_drafting: "正在整理测试说明",
  brief_review: "测试说明待确认",
  generating: "正在生成候选",
  candidate_review: "候选待审阅",
  maintenance: "正式用例维护",
};

const workflowStageLabels: Record<string, string> = {
  queued: "任务已排队",
  "context.prepared": "检索并整理上下文",
  "requirement.analyzed": "分析测试需求",
  "generation.awaiting_input": "等待补充信息",
  "feature.generated": "整理功能点",
  "test_point.generated": "规划测试点",
  "test_case.generated": "生成候选用例",
  "test_case.grounded": "核对预期与需求来源",
  "generation.batch_completed": "本批候选已更新",
  "rewrite.batch_completed": "本批改写已更新",
  "enhancement.completed": "补充边界与异常场景",
  "quality.completed": "执行质量检查",
  "knowledge.answered": "结合知识生成回答",
  completed: "处理完成",
  failed: "处理失败",
  cancelled: "已停止",
};

const operationStatusLabels: Record<string, string> = {
  queued: "等待执行",
  running: "正在执行",
  awaiting_confirmation: "等待确认",
  awaiting_intent: "等待选择操作",
  awaiting_target: "待确认或补充",
  completed: "已完成",
  skipped: "已跳过",
  failed: "执行失败",
  cancelled: "已取消",
};

const englishIntentLabels: Record<ConversationIntent, string> = {
  CASE_GENERATE: "Generate test cases",
  CASE_MODIFY: "Modify test cases",
  CASE_DELETE: "Delete test cases",
  CASE_QUERY: "Query test cases",
  CASE_REVIEW: "Review cases",
  CASE_DEDUP: "Find duplicate cases",
  COVERAGE_ANALYZE: "Analyze coverage",
  KNOWLEDGE_QA: "Knowledge Q&A",
  SMALL_TALK: "CasePilot",
  UNRESOLVED: "More details needed",
};
const englishPhaseLabels: Record<string, string> = {
  idle: "Waiting for requirements",
  brief_drafting: "Drafting test brief",
  brief_review: "Test brief awaiting confirmation",
  generating: "Generating candidates",
  candidate_review: "Candidates awaiting review",
  maintenance: "Maintaining official test cases",
};
const englishWorkflowStageLabels: Record<string, string> = {
  queued: "Task queued", "context.prepared": "Preparing context",
  "requirement.analyzed": "Analyzing requirements",
  "generation.awaiting_input": "Waiting for more details",
  "feature.generated": "Organizing features",
  "test_point.generated": "Planning test points",
  "test_case.generated": "Generating candidate cases",
  "test_case.grounded": "Checking expectations against requirements",
  "generation.batch_completed": "Batch preview updated",
  "rewrite.batch_completed": "Rewrite preview updated",
  "enhancement.completed": "Adding boundary and negative scenarios",
  "quality.completed": "Running quality checks",
  "knowledge.answered": "Answering with workspace knowledge",
  completed: "Completed", failed: "Failed", cancelled: "Stopped",
};
const englishOperationStatusLabels: Record<string, string> = {
  queued: "Queued", running: "Running", awaiting_confirmation: "Awaiting confirmation",
  awaiting_target: "Confirm or clarify",
  awaiting_intent: "Choose an action", completed: "Completed", skipped: "Skipped",
  failed: "Failed", cancelled: "Cancelled",
};

const terminalWorkflowStatuses = new Set(["completed", "failed", "cancelled"]);
function clampPanelWidth(
  panel: "chat" | "inspector",
  value: number,
): number {
  const [minimum, maximum] = panel === "chat" ? [420, 720] : [280, 480];
  return Math.min(maximum, Math.max(minimum, Math.round(value)));
}

function candidateToCase(candidate: WorkspaceCandidateDto): TestCaseDto {
  const snapshot = candidate.snapshot;
  return {
    id: candidate.id,
    case_key: candidate.ref,
    collection_ids: [],
    current_revision_id: `candidate-${candidate.id}-v${candidate.version}`,
    revision_number: candidate.version,
    title: snapshot.title,
    module: snapshot.module,
    priority: snapshot.priority,
    case_type: snapshot.case_type,
    tags: snapshot.tags,
    preconditions: snapshot.preconditions,
    steps: snapshot.steps.map((step, index) => ({
      id: `candidate-${candidate.id}-step-${index}`,
      action: step.action,
      expected: step.expected,
    })),
    source: snapshot.source_refs[0]?.label ?? "CasePilot 候选",
    source_refs: snapshot.source_refs,
    created_at: candidate.updated_at,
  };
}

function messageLabel(
  role: "user" | "assistant",
  intent: ConversationIntent | null,
  metadata: Record<string, unknown>,
  labels: Record<ConversationIntent, string>,
  userLabel: string,
  briefLabel: string,
): string {
  if (role === "user") return userLabel;
  if (
    intent === "CASE_GENERATE" &&
    ["draft", "update"].includes(String(metadata.brief_operation ?? ""))
  ) {
    return briefLabel;
  }
  return intent ? labels[intent] : "CasePilot";
}

export function CaseWorkbench({
  spaceId,
  spaceName,
  selectedCollection,
  cases,
  loading,
  conversationId,
  pendingOperationId,
  onSelectCase,
  onCreateCaseInline,
  onSaveCase,
  onCasesChanged,
  onNewConversation,
  onContinueInNewConversation,
  onCancelOperation,
  onOpenHistory,
  onDirtyChange,
}: CaseWorkbenchProps) {
  const { locale, pick } = useI18n();
  const localizedIntentLabels = locale === "en" ? englishIntentLabels : intentLabels;
  const localizedIntentActionLabels = locale === "en"
    ? { ...englishIntentLabels, SMALL_TALK: "Conversation" }
    : intentActionLabels;
  const localizedPhaseLabels = locale === "en" ? englishPhaseLabels : phaseLabels;
  const localizedWorkflowStageLabels = locale === "en" ? englishWorkflowStageLabels : workflowStageLabels;
  const localizedOperationStatusLabels = locale === "en" ? englishOperationStatusLabels : operationStatusLabels;
  const changeAppliedNotice = pick("Changes applied and recorded in the audit log", "变更已应用并记录审计");
  const [workspace, setWorkspace] = useState<ConversationDto | null>(null);
  const [prompt, setPrompt] = useState("");
  const pendingDraftEdit = useRef<{ workspaceId: string; text: string } | null>(null);
  const editPrompt = (text: string) => {
    pendingDraftEdit.current = workspace ? { workspaceId: workspace.id, text } : null;
    setPrompt(text);
  };
  const restoredDraftConversationRef = useRef("");
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const [modelId, setModelId] = useState<AgentModelId>("auto");
  const [models, setModels] = useState<{ id: string; label: string }[]>([]);
  const [viewMode, setViewMode] = useState<"list" | "map" | "plan">("plan");
  // Mount the graph on first use, then retain layout, zoom and measured nodes.
  // Activity pauses its effects while another result view is visible.
  const [mapVisited, setMapVisited] = useState(false);
  if (viewMode === "map" && !mapVisited) setMapVisited(true);
  const restoredViewCollectionIdRef = useRef("");
  const viewTouchedRef = useRef(false);
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [mapFocusVersion, setMapFocusVersion] = useState(0);
  const [resumeTaskId, setResumeTaskId] = useState("");
  const [refineSourceId, setRefineSourceId] = useState("");
  const [reviewVersion, setReviewVersion] = useState({ taskId: "", latestId: "", operationId: "" });
  const [historicalChangeSet, setHistoricalChangeSet] = useState<CaseChangeSetDto | null>(null);
  const [resultLoadError, setResultLoadError] = useState("");
  const [planMessageId, setPlanMessageId] = useState("");
  const [editingCaseId, setEditingCaseId] = useState("");
  const [creatingInWorkspace, setCreatingInWorkspace] = useState(false);
  const [savingInWorkspace, setSavingInWorkspace] = useState(false);
  const [selectedTargets, setSelectedTargets] = useState<
    { key: string; label: string; target: ConversationTarget }[]
  >([]);
  const [rewriteTargets, setRewriteTargets] = useState<
    { key: string; label: string; target: ConversationTarget }[]
  >([]);
  const [queueRunning, setQueueRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pendingMessage, setPendingMessage] = useState<string | null>(null);
  const [runningSeconds, setRunningSeconds] = useState(0);
  const [currentJobId, setCurrentJobId] = useState("");
  const [progress, setProgress] = useState<GenerationStage | null>(null);
  const [liveStages, setLiveStages] = useState<GenerationStage[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedBriefVersion, setSelectedBriefVersion] = useState(0);
  const [artifactOpen, setArtifactOpen] = useState(false);
  const [briefView, setBriefView] = useState<"map" | "text">("map");
  const [chatWidth, setChatWidth] = useState(520);
  const [inspectorWidth, setInspectorWidth] = useState(300);
  const [inspectorHidden, setInspectorHidden] = useState(false);
  const [activeChangeSet, setActiveChangeSet] =
    useState<CaseChangeSetDto | null>(null);
  const [acceptedFields, setAcceptedFields] = useState<
    Record<string, string[]>
  >({});
  const reviewSelections = useRef<Record<string, Record<string, string[]>>>({});
  const [candidateDraft, setCandidateDraft] =
    useState<WorkspaceCandidateDto | null>(null);
  const [candidateSaving, setCandidateSaving] = useState(false);
  const [candidateSaveMessage, setCandidateSaveMessage] = useState("");
  const [uploading, setUploading] = useState(false);
  const [attachments, setAttachments] = useState<{ id: string; name: string; size: number; percent: number; status: "uploading" | "processing" | "ready" | "failed" }[]>([]);
  const [sourceIds, setSourceIds] = useState<string[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);
  const promptSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const streamScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const watchedJobRef = useRef("");
  const queueDispatchRef = useRef(false);
  const queueFailureRef = useRef("");
  const reviewSaveQueueRef = useRef<Promise<unknown>>(Promise.resolve());
  const lastWorkspacePhaseRef = useRef("");
  const {
    scrollRef: messagesScrollRef,
    contentRef: messagesContentRef,
    scrollToBottom,
  } = useStickToBottom({ initial: "instant", resize: "smooth" });

  const phase = String(workspace?.context.phase ?? "idle");
  const collectionStatus = collectionStatusFromPhase(phase, cases.length);
  const activeWorkspaceJobId = String(
    workspace?.context.active_job_id ?? "",
  );
  const planningPreview = phase === "brief_drafting" ? progress?.planning_preview : null;
  const planningProgress = progress?.planning_progress;
  const latestBrief = workspace?.test_briefs.at(-1) ?? null;
  const activeBrief =
    workspace?.test_briefs.find((item) => item.status === "draft") ??
    latestBrief;
  const selectedBrief =
    workspace?.test_briefs.find(
      (item) => item.version === selectedBriefVersion,
    ) ?? latestBrief;
  const blockingQuestions =
    activeBrief?.content.open_questions.filter((item) => item.blocking) ?? [];
  const candidates = useMemo(
    () => workspace?.candidates ?? [],
    [workspace?.candidates],
  );
  const candidateCases = useMemo(
    () => candidates.map(candidateToCase),
    [candidates],
  );
  const visibleCases = useMemo(
    () => phase === "candidate_review" && candidateCases.length
      ? candidateCases
      : cases,
    [phase, candidateCases, cases],
  );
  const selectedCase =
    visibleCases.find((item) => item.id === selectedCaseId) ??
    visibleCases[0] ??
    null;
  const pendingWorkspaceOperation = workspace?.operation_plan?.operations.find((item) => item.status === "awaiting_target");
  const effectivePendingOperationId = resumeTaskId || (workspace
    ? pendingWorkspaceOperation && shouldResumePendingTask(pendingWorkspaceOperation.intent, prompt)
      ? pendingWorkspaceOperation.id
      : undefined
    : pendingOperationId);
  const activeOperation = workspace?.operation_plan?.operations.find((item) =>
    ["running", "awaiting_confirmation"].includes(item.status));
  const activeRewriteOperation = activeOperation?.intent === "CASE_MODIFY"
    ? activeOperation
    : undefined;
  const activeRewriteTargets = useMemo(() => {
    if (!activeRewriteOperation?.target.resolved) return rewriteTargets.length ? rewriteTargets : selectedTargets;
    const ids = new Set([
      ...(activeRewriteOperation.target.case_ids as string[] ?? []),
      ...candidates.filter((candidate) =>
        (activeRewriteOperation.target.candidate_refs as string[] ?? []).includes(candidate.ref)
      ).map((candidate) => candidate.id),
    ]);
    return visibleCases.filter((item) => ids.has(item.id)).map((item) => ({
      key: item.id, label: item.title,
      target: { kind: "case", case_ids: [item.id] } as ConversationTarget,
    }));
  }, [activeRewriteOperation, candidates, visibleCases, rewriteTargets, selectedTargets]);
  const rewriteStatus: "idle" | "selected" | "running" | "review" | "applied" =
    !activeRewriteTargets.length || pendingWorkspaceOperation?.intent === "CASE_MODIFY"
      ? "idle"
      : activeRewriteOperation?.status === "running" || activeChangeSet?.status === "generating"
        ? "running"
        : activeChangeSet?.status === "ready"
          ? "review"
          : notice === changeAppliedNotice
            ? "applied"
            : "selected";
  const selectedRewriteTargets = useMemo(
    () => activeRewriteTargets.map((item) => item.target),
    [activeRewriteTargets],
  );
  const displayedTargets = selectedTargets.length
    ? selectedTargets
    : rewriteTargets;
  const workflowByMessageId = useMemo(
    () =>
      new Map(
        (workspace?.workflow_runs ?? []).map((run) => [run.message_id, run]),
      ),
    [workspace?.workflow_runs],
  );
  const messages =
    workspace?.messages.filter(
      (message) =>
        message.content.trim() || workflowByMessageId.has(message.id) ||
        (Array.isArray(message.metadata.attachments) && message.metadata.attachments.length > 0),
    ) ?? [];
  const tasks = useMemo(() => workspaceTasks(workspace), [workspace]);
  const activeMutationTask = tasks.find(task => task.id === String(workspace?.context.active_mutation_task_id ?? ""));
  const resultTasks = tasks.filter((task) => !["KNOWLEDGE_QA", "UNRESOLVED"].includes(task.message.intent ?? ""));
  const selectedTask = resultTasks.find((task) => task.id === planMessageId || task.messageIds.includes(planMessageId) || task.versions?.some(version => version.id === planMessageId))
    ?? resultTasks.find((task) => task.status === "running")
    ?? resultTasks.find((task) => task.status.startsWith("awaiting_")) ?? resultTasks[0];
  const activePlanMessage = selectedTask?.message;
  const conversationRunning = busy || queueRunning || workspaceIsRunning(workspace);
  const runningLabel = pendingMessage !== null
    ? pick("Thinking — understanding your request and selecting cases", "正在思考 · 理解需求并筛选用例")
    : planningProgress?.total_batches
      ? pick(`Planning · ${planningProgress.completed_batches ?? 0}/${planningProgress.total_batches} batches · ${planningProgress.test_point_count ?? 0} test points ready`, `规划中 · ${planningProgress.completed_batches ?? 0}/${planningProgress.total_batches} 批 · ${planningProgress.test_point_count ?? 0} 个测试点已就绪`)
    : progress?.total_count
      ? `${localizedWorkflowStageLabels[progress.name] ?? pick("Processing your request", "正在处理请求")} · ${pick(`${progress.generated_count ?? 0}/${progress.total_count ?? "?"} cases ready`, `${progress.generated_count ?? 0}/${progress.total_count ?? "?"} 条已就绪`)}`
      : progress
      ? localizedWorkflowStageLabels[progress.name] ?? pick("Processing your request", "正在处理请求")
      : pick("Preparing the next step", "正在准备下一步");

  useEffect(() => {
    if (!conversationRunning) return;
    const parsedStart = Date.parse(progress?.started_at ?? "");
    const startedAt = Number.isFinite(parsedStart) ? parsedStart : Date.now();
    const timer = window.setInterval(() => {
      setRunningSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [conversationRunning, progress?.started_at]);
  const taskVersions = selectedTask?.versions ?? (selectedTask ? [selectedTask] : []);
  const chosenVersion = reviewVersion.taskId === selectedTask?.id && reviewVersion.latestId === selectedTask?.operation?.id
    ? taskVersions.find(version => version.operation?.id === reviewVersion.operationId) : undefined;
  const hasLiveRewritePreview = activeChangeSet?.id === selectedTask?.operation?.related_change_set_id && activeChangeSet?.status === "generating" && activeChangeSet.items.length > 0;
  const hasLiveGenerationPreview = candidatesForTask(selectedTask, workspace).some(item => item.status === "generating");
  const generatingRevision = !hasLiveRewritePreview && !hasLiveGenerationPreview && taskVersions.length > 1 && ["running", "queued"].includes(selectedTask?.status ?? "");
  const resultVersion = chosenVersion ?? (generatingRevision ? taskVersions[taskVersions.length - 2] : selectedTask);
  const historicalVersion = resultVersion?.operation?.id !== selectedTask?.operation?.id;
  const selectedChangeSetId = String(resultVersion?.message.metadata.change_set_id ?? "");
  const loadedTaskChangeSet = activeChangeSet?.id === selectedChangeSetId ? activeChangeSet
    : historicalChangeSet?.id === selectedChangeSetId ? historicalChangeSet : null;
  const selectedTaskChangeSet = loadedTaskChangeSet && historicalVersion && loadedTaskChangeSet.status === "ready"
    ? { ...loadedTaskChangeSet, status: "superseded" as const } : loadedTaskChangeSet;
  const pendingCandidateRefs = [...new Set([activeChangeSet, historicalChangeSet].flatMap(change =>
    change?.status === "ready" && workspace?.operation_history?.some(op => op.related_change_set_id === change.id && op.status === "awaiting_confirmation")
      ? change.items.filter(item => item.target_type === "candidate" && !["applied", "rejected"].includes(item.status ?? "")).map(item => item.ref) : []))];
  const selectedCandidatesNeedReview = candidates.some(candidate => candidate.included && pendingCandidateRefs.includes(candidate.ref));
  const selectedScopeChanged = taskScopeChanged(selectedTask, cases);
  useEffect(() => {
    if (!selectedChangeSetId) return;
    let cancelled = false;
    void getCaseChangeSet(selectedChangeSetId).then((result) => {
      if (cancelled) return;
      setHistoricalChangeSet(result);
      setResultLoadError("");
      if (result.status === "ready") setAcceptedFields(reviewSelections.current[result.id] ?? Object.fromEntries(result.items.map((item) => [item.ref, item.field_diff.map((diff) => diff.field)])));
    }, () => { if (!cancelled) setResultLoadError(pick("Unable to load this task result. Select the task again to retry.", "任务结果加载失败，请切换任务后重试。")); });
    return () => { cancelled = true; };
  }, [selectedChangeSetId, selectedTask?.status, selectedTask?.operation?.status, pick]);
  const activePlanReport = activePlanMessage?.metadata.analysis_report as CaseReviewReport | undefined;
  const changedSinceReview = selectedScopeChanged || Boolean(activePlanMessage && messages.slice(messages.findIndex((item) => item.id === activePlanMessage.id) + 1).some(
    (message) => ["applied", "candidates_committed"].includes(String(message.metadata.action)),
  ));
  const openReviewPlan = (messageId?: string) => {
    if (messageId) {
      setPlanMessageId(messageId);
      setReviewVersion({ taskId: "", latestId: "", operationId: "" });
    }
    viewTouchedRef.current = true;
    setArtifactOpen(false);
    setViewMode("plan");
    if (workspace) void updateWorkspaceState(workspace.id, { active_view: "plan" });
  };
  const openCaseEditor = (testCase: TestCaseDto) => {
    setSelectedCaseId(testCase.id);
    setEditingCaseId(testCase.id);
    setCreatingInWorkspace(false);
    openReviewPlan();
  };
  useEffect(() => {
    if (viewMode !== "plan" || (!editingCaseId && !creatingInWorkspace)) return;
    document.querySelector(".case-workspace-editor")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [creatingInWorkspace, editingCaseId, viewMode]);
  const operationPlan = workspace?.operation_plan ?? null;
  const pendingIntentOperations = operationPlan?.operations.filter((operation) =>
    operation.status === "awaiting_intent" && !messages.some((message) =>
      message.status === "awaiting_intent" && (message.metadata.operation_id === operation.id || message.id === operation.source_message_id))) ?? [];
  const showOperationPlan = pendingIntentOperations.length > 0;
  const singleRewriteTarget = displayedTargets.length === 1 &&
    displayedTargets[0].target.kind === "case" &&
    (displayedTargets[0].target.case_ids?.length ?? 0) +
      (displayedTargets[0].target.candidate_refs?.length ?? 0) === 1;
  const latestMessage = messages.at(-1);
  const inspectorCollapsed =
    inspectorHidden ||
    viewMode === "plan" ||
    artifactOpen ||
    !visibleCases.length;

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (active) setInspectorHidden(window.innerWidth <= 1500);
    });
    return () => { active = false; };
  }, []);

  const toggleTarget = useCallback(
    (target: ConversationTarget, label: string) => {
      const key = JSON.stringify(target);
      setSelectedTargets((current) => {
        const next = current.some((item) => item.key === key)
          ? current.filter((item) => item.key !== key)
          : [...current, { key, label, target }];
        setRewriteTargets(next);
        if (workspace) {
          void updateWorkspaceState(workspace.id, {
            selected_targets: next.map((item) => ({
              label: item.label,
              target: item.target,
            })),
          });
        }
        return next;
      });
    },
    [workspace],
  );

  const selectTarget = useCallback(
    (target: ConversationTarget, label: string) => {
      const next = [{ key: JSON.stringify(target), label, target }];
      setSelectedTargets(next);
      setRewriteTargets(next);
      if (workspace) {
        void updateWorkspaceState(workspace.id, {
          selected_targets: [{ label, target }],
        });
      }
    },
    [workspace],
  );

  const caseTarget = useCallback((testCase: TestCaseDto): ConversationTarget => {
    const candidate = candidates.find((item) => item.id === testCase.id);
    return candidate
      ? { kind: "case", candidate_refs: [candidate.ref] }
      : { kind: "case", case_ids: [testCase.id] };
  }, [candidates]);

  const selectedCollectionId = selectedCollection?.id ?? "";
  const applyWorkspaceResult = useCallback((result: ConversationDto) => {
    setWorkspace(result);
    if (restoredDraftConversationRef.current !== result.id) {
      restoredDraftConversationRef.current = result.id;
      setPrompt(String(result.context.draft_text ?? ""));
    }
    const restoredModelId = String(result.context.model_id ?? "");
    if (restoredModelId) setModelId(restoredModelId);
    if (!viewTouchedRef.current && restoredViewCollectionIdRef.current !== selectedCollectionId) {
      restoredViewCollectionIdRef.current = selectedCollectionId;
      setViewMode(result.context.active_view === "map" ? "map" : result.context.active_view === "list" ? "list" : "plan");
    }
    const restoredBriefVersion = Number(
      result.context.selected_brief_version ??
        result.test_briefs.at(-1)?.version ??
        0,
    );
    setSelectedBriefVersion(restoredBriefVersion);
    const workspacePhase = `${result.id}:${String(result.context.phase ?? "idle")}`;
    if (workspacePhase !== lastWorkspacePhaseRef.current) {
      lastWorkspacePhaseRef.current = workspacePhase;
      setArtifactOpen(result.context.phase === "brief_review");
    }
    const savedChatWidth = Number(result.context.chat_width ?? 520);
    setChatWidth(savedChatWidth < 420 ? 520 : clampPanelWidth("chat", savedChatWidth));
    setInspectorWidth(
      clampPanelWidth("inspector", Number(result.context.inspector_width ?? 300)),
    );
    const restoredCaseId = String(result.context.selected_case_id ?? "");
    setSelectedCaseId(restoredCaseId);
    const restoredTargets = Array.isArray(result.context.selected_targets)
      ? (result.context.selected_targets as {
          label: string;
          target: ConversationTarget;
        }[])
      : [];
    const normalizedTargets = restoredTargets.map((item) => ({
      ...item,
      key: JSON.stringify(item.target),
    }));
    setSelectedTargets(normalizedTargets);
    setRewriteTargets(normalizedTargets);
    const activeJobId = String(result.context.active_job_id ?? "");
    const jobIsRunning = Boolean(activeJobId) && !result.workflow_runs.some((run) =>
      run.job_id === activeJobId && terminalWorkflowStatuses.has(run.status));
    setCurrentJobId(jobIsRunning ? activeJobId : "");
    setBusy(jobIsRunning);
    const restoredCandidate =
      result.candidates.find((item) => item.id === restoredCaseId) ??
      result.candidates[0] ??
      null;
    setCandidateDraft(
      restoredCandidate ? structuredClone(restoredCandidate) : null,
    );
  }, [selectedCollectionId, setCandidateDraft]);
  const refreshWorkspace = useCallback(async () => {
    if (!selectedCollectionId) return null;
    const result = conversationId
      ? await getConversation(conversationId)
      : await getOrCreateWorkspace(selectedCollectionId);
    applyWorkspaceResult(result);
    const review = result.operation_plan?.operations.find(
      (item) => item.status === "awaiting_confirmation" && item.related_change_set_id,
    );
    if (review?.related_change_set_id) {
      const changeSet = await getCaseChangeSet(review.related_change_set_id);
      if (changeSet.status === "ready") {
        setActiveChangeSet(changeSet);
        setAcceptedFields(reviewSelections.current[changeSet.id] ?? Object.fromEntries(changeSet.items.map((item) => [
          item.ref,
          item.field_diff.map((diff) => diff.field),
        ])));
      }
    }
    return result;
  }, [applyWorkspaceResult, conversationId, selectedCollectionId]);
  const waitAndRefresh = useCallback(
    async (jobId: string, conversationId = workspace?.id ?? "") => {
      if (!conversationId || watchedJobRef.current === jobId) return;
      watchedJobRef.current = jobId;
      viewTouchedRef.current = true;
      setViewMode("plan");
      setArtifactOpen(false);
      setPlanMessageId(workspace?.workflow_runs.find(run => run.job_id === jobId)?.message_id
        ?? workspace?.messages.find(message => message.role === "assistant" && message.related_job_id === jobId)?.id ?? "");
      setBusy(true);
      setCurrentJobId(jobId);
      setProgress({ name: "queued", progress: 0 });
      let previewRefresh: Promise<void> | null = null;
      let lastPreviewCount = 0;
      try {
        const job = await watchGeneration(
          jobId,
          (stage) => {
            if (stage.generated_count && stage.generated_count > lastPreviewCount && !previewRefresh) {
              const count = stage.generated_count;
              previewRefresh = getConversation(conversationId).then(async (result) => {
                setWorkspace((current) => current?.id === result.id ? result : current);
                const operation = result.operation_history?.find(item => item.related_job_id === jobId);
                if (operation?.related_change_set_id && watchedJobRef.current === jobId) {
                  const preview = await getCaseChangeSet(operation.related_change_set_id);
                  if (watchedJobRef.current === jobId) setActiveChangeSet(preview);
                }
                lastPreviewCount = count;
              }).catch(() => undefined).finally(() => { previewRefresh = null; });
            }
            setProgress((current) => ({
              ...stage,
              planning_preview: (stage.planning_progress?.completed_batches ?? 0) < (current?.planning_progress?.completed_batches ?? 0)
                ? current?.planning_preview : stage.planning_preview ?? current?.planning_preview,
              planning_progress: (stage.planning_progress?.completed_batches ?? 0) < (current?.planning_progress?.completed_batches ?? 0)
                ? current?.planning_progress : stage.planning_progress ?? current?.planning_progress,
              progress: Math.max(stage.progress, current?.progress ?? 0),
              started_at: stage.started_at ?? current?.started_at,
              retry_attempt: stage.retry_attempt ?? current?.retry_attempt,
              batch_start_index: stage.batch_start_index ?? current?.batch_start_index,
              batch_count: stage.batch_count ?? current?.batch_count,
              active_batches: stage.active_batches ?? current?.active_batches,
              generated_count: stage.generated_count === undefined ? current?.generated_count : Math.max(stage.generated_count, current?.generated_count ?? 0),
              total_count: stage.total_count ?? current?.total_count,
            }));
            setLiveStages((current) => {
              const existingIndex = current.findIndex(
                (item) => item.name === stage.name,
              );
              if (existingIndex === -1) return [...current, stage];
              return current.map((item, index) =>
                index === existingIndex ? stage : item,
              );
            });
          },
          (content) => {
            setWorkspace((current) =>
              current
                ? {
                    ...current,
                    messages: current.messages.map((message) =>
                      message.role === "assistant" &&
                      message.related_job_id === jobId
                        ? { ...message, content, status: "running" }
                        : message,
                    ),
                  }
                : current,
            );
          },
        );
        await previewRefresh;
        if (job.status === "failed") {
          throw new Error(job.error_code ?? pick("Task failed. Try again later.", "任务处理失败，请稍后重试"));
        }
        await refreshWorkspace();
      } catch (caught) {
        await previewRefresh;
        await refreshWorkspace().catch(() => undefined);
        throw caught;
      } finally {
        if (watchedJobRef.current === jobId) {
          watchedJobRef.current = "";
        }
        setBusy(false);
        setCurrentJobId("");
        setProgress(null);
        setLiveStages([]);
      }
    },
    [pick, refreshWorkspace, workspace],
  );

  const retryFailedMessage = async (messageId: string) => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const failedWorkflow = workflowByMessageId.get(messageId);
      openReviewPlan(messageId);
      if (failedWorkflow?.operation === "generate") {
        await retryGeneration(failedWorkflow.job_id);
        await refreshWorkspace();
        await waitAndRefresh(failedWorkflow.job_id);
      } else {
        const turn = await retryConversationMessage(messageId);
        await refreshWorkspace();
        if (turn.action.job_id) await waitAndRefresh(turn.action.job_id);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : pick("Retry failed", "重试失败"));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    void listGenerationModels()
      .then((result) => {
        setModels(
          result.models.map((item) => ({ id: item.id, label: item.label })),
        );
        setModelId((current) =>
          current === "auto" ? result.default_model_id : current,
        );
      })
      .catch(() => {
        setModels([{ id: "auto", label: pick("Default model", "默认模型") }]);
      });
  }, [pick]);

  useEffect(() => {
    if (!selectedCollectionId) return;
    viewTouchedRef.current = false;
    let ignored = false;
    void (conversationId
      ? getConversation(conversationId)
      : getOrCreateWorkspace(selectedCollectionId))
      .then(async (result) => {
        if (ignored) return;
        applyWorkspaceResult(result);
        const review = result.operation_plan?.operations.find(
          (item) => item.status === "awaiting_confirmation" && item.related_change_set_id,
        );
        if (review?.related_change_set_id) {
          const changeSet = await getCaseChangeSet(review.related_change_set_id);
          if (!ignored && changeSet.status === "ready") {
            setActiveChangeSet(changeSet);
            setAcceptedFields(Object.fromEntries(changeSet.items.map((item) => [
              item.ref,
              item.field_diff.map((diff) => diff.field),
            ])));
          }
        }
        setError("");
        setNotice("");
      })
      .catch((caught) => {
        setError(caught instanceof Error ? caught.message : pick("Failed to restore workspace", "工作区恢复失败"));
      });
    return () => {
      ignored = true;
    };
  }, [applyWorkspaceResult, conversationId, pick, selectedCollectionId]);

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      setSelectedTargets([]);
      setRewriteTargets([]);
    });
    return () => {
      active = false;
    };
  }, [selectedCollectionId]);

  useEffect(() => {
    if (
      !workspace ||
      !activeWorkspaceJobId ||
      workspace.workflow_runs.some((run) => run.job_id === activeWorkspaceJobId && terminalWorkflowStatuses.has(run.status))
    ) {
      return;
    }
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      void waitAndRefresh(activeWorkspaceJobId, workspace.id).catch((caught) => {
        setError(caught instanceof Error ? caught.message : pick("Failed to restore task", "任务恢复失败"));
      });
    });
    return () => { active = false; };
  }, [activeWorkspaceJobId, phase, pick, waitAndRefresh, workspace]);

  useEffect(() => {
    onDirtyChange?.(false);
    return () => onDirtyChange?.(false);
  }, [onDirtyChange]);

  useEffect(() => {
    if (!latestMessage && pendingMessage === null) return;
    if (currentJobId) {
      if (streamScrollTimerRef.current) return;
      streamScrollTimerRef.current = setTimeout(() => {
        streamScrollTimerRef.current = null;
        void scrollToBottom({ animation: "instant", ignoreEscapes: true });
      }, 96);
      return;
    }
    void scrollToBottom({
      animation: "smooth",
      ignoreEscapes: true,
    });
  }, [currentJobId, latestMessage, pendingMessage, scrollToBottom]);

  useEffect(
    () => () => {
      if (streamScrollTimerRef.current) {
        clearTimeout(streamScrollTimerRef.current);
      }
    },
    [],
  );

  useEffect(() => {
    const edit = pendingDraftEdit.current;
    if (!workspace || !edit || edit.workspaceId !== workspace.id || edit.text !== prompt ||
        prompt === String(workspace.context.draft_text ?? "")) {
      return;
    }
    if (promptSaveTimer.current) clearTimeout(promptSaveTimer.current);
    promptSaveTimer.current = setTimeout(() => {
      void updateWorkspaceState(workspace.id, { draft_text: prompt }).then(
        (saved) => {
          if (pendingDraftEdit.current !== edit) return;
          pendingDraftEdit.current = null;
          setWorkspace((current) => current?.id === saved.id
            ? { ...current, context: { ...current.context, draft_text: saved.context.draft_text } }
            : current);
        },
        () => undefined,
      );
    }, 500);
    return () => {
      if (promptSaveTimer.current) clearTimeout(promptSaveTimer.current);
    };
  }, [prompt, workspace]);

  const handleFiles = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (!files.length || !spaceId || !workspace) return;
    setUploading(true);
    setError("");
    const entries = files.map((file) => ({ id: crypto.randomUUID(), name: file.name, size: file.size, percent: 0, status: "uploading" as const }));
    const ids = new Set(entries.map((entry) => entry.id));
    setAttachments((current) => [...current, ...entries]);
    const update = (values: Partial<(typeof attachments)[number]>) => setAttachments((current) => current.map((item) => ids.has(item.id) ? { ...item, ...values } : item));
    try {
      const result = await uploadConversationAttachments(
        workspace.id,
        files,
        (percent) => update({ percent, status: percent === 100 ? "processing" : "uploading" }),
      );
      update({ percent: 100, status: "processing" });
      setWorkspace(await getConversation(workspace.id));
      await waitForKnowledgeSource(spaceId, result.source.id);
      setSourceIds((current) => [...new Set([...current, result.source.id])]);
      setWorkspace(await getConversation(workspace.id));
      setAttachments(current => current.filter(file => !ids.has(file.id)));
      setNotice(pick("Attachment saved to the current workspace", "附件已自动保存到当前工作区"));
    } catch (caught) {
      update({ status: "failed" });
      setError(caught instanceof Error ? caught.message : pick("Failed to save attachment", "附件保存失败"));
    } finally {
      setUploading(false);
    }
  };

  const continueTaskQueue = useCallback(async (initial: ConversationDto | null) => {
    if (queueDispatchRef.current) return initial;
    queueDispatchRef.current = true;
    setQueueRunning(true);
    let attemptingId = "";
    try {
    let result = initial;
    for (let index = 0; index < 8; index += 1) {
      const next = nextWorkspaceOperation(result);
      if (!next) break;
      attemptingId = next.id;
      const turn = await resumeConversationOperation(next.id);
      setPlanMessageId(next.id);
      setViewMode("plan");
      setArtifactOpen(false);
      await refreshWorkspace();
      if (turn.action.job_id) await waitAndRefresh(turn.action.job_id);
      result = await refreshWorkspace();
    }
    return result;
    } catch (caught) {
      queueFailureRef.current = attemptingId;
      throw caught;
    } finally { queueDispatchRef.current = false; setQueueRunning(false); }
  }, [refreshWorkspace, waitAndRefresh]);

  useEffect(() => {
    const next = nextWorkspaceOperation(workspace);
    if (conversationRunning || !next || queueDispatchRef.current || queueFailureRef.current === next.id) return;
    void continueTaskQueue(workspace).catch((caught) => setError(caught instanceof Error ? caught.message : pick("Could not continue task queue", "后续任务启动失败")));
  }, [conversationRunning, workspace, continueTaskQueue, pick]);

  const persistReviewDecisions = (operationId: string, decisions: TaskReviewDecisions) => {
    setWorkspace((current) => current ? { ...current, operation_history: current.operation_history?.map((operation) => operation.id === operationId ? { ...operation, result: { ...operation.result, review_decisions: decisions } } : operation) } : current);
    reviewSaveQueueRef.current = reviewSaveQueueRef.current.catch(() => undefined)
      .then(() => saveTaskReview(operationId, decisions))
      .catch((caught) => setError(caught instanceof Error ? caught.message : pick("Could not save review choices", "审阅选择保存失败")));
  };

  const runFollowup = async (action: "generate" | "rewrite" | "merge", findings: CaseReviewFinding[], keepIds?: string[]) => {
    if (!workspace || conversationRunning || !selectedTask) return;
    const refs = new Set(findings.flatMap((item) => item.case_refs));
    const selectedIds = keepIds ?? cases.filter((item) => refs.has(item.id)).map((item) => item.id);
    const intent: ConversationIntent = action === "generate" ? "CASE_GENERATE" : "CASE_MODIFY";
    const instruction = action === "generate"
      ? pick("Generate additional candidate cases for the selected gaps; use verified requirements and flag assumptions.", "为选中的覆盖缺口生成补充候选用例，依据已验证需求并标注待核实假设。")
      : action === "merge"
        ? pick("Merge all unique checks into the selected kept case. Prepare a rewrite for review; preserve every distinct scenario.", "将分组中所有独有验证点合并到选中的保留用例，生成改写审阅方案，保留各自独立场景。")
        : pick("Prepare case rewrites for the selected findings, with clear steps and verifiable expectations.", "针对选中的质量问题生成用例改写方案，明确操作步骤和可验证的预期结果。");
    const content = `${instruction}\n\n${findings.map((finding, index) => [
      `${index + 1}. ${finding.title}`,
      `${pick("Evidence", "依据")}：${finding.evidence}`,
      `${pick("Recommendation", "建议")}：${finding.recommendation}`,
      ...(finding.unique_coverage?.length ? [`${pick("Unique checks", "独有验证点")}：${finding.unique_coverage.join("；")}`] : []),
    ].join("\n")).join("\n\n")}`;
    if (content.length > 8000) { setError(pick("Select fewer findings and process them in batches.", "所选发现内容较多，请分批处理。")); return; }
    setBusy(true);
    setError("");
    setPlanMessageId("");
    try {
      const turn = await sendConversationMessage(workspace.id, {
        content,
        modelId, scope: "current", intentOverride: intent,
        sourceOperationId: selectedTask.operation?.id,
        targets: selectedIds.length ? Array.from({ length: Math.ceil(selectedIds.length / 100) }, (_, index) => ({ kind: "case" as const, case_ids: selectedIds.slice(index * 100, (index + 1) * 100) }))
          : selectedTask.operation ? [{ kind: "previous_result", source_operation_id: selectedTask.operation.id }] : [],
      });
      await refreshWorkspace();
      if (turn.action.job_id) await waitAndRefresh(turn.action.job_id);
      await continueTaskQueue(await refreshWorkspace());
    } catch (caught) { setError(caught instanceof Error ? caught.message : pick("Could not start follow-up task", "后续任务启动失败")); }
    finally { setBusy(false); }
  };

  const discardTask = async (task: WorkspaceTask) => {
    if (!task.operation || conversationRunning) return;
    setBusy(true);
    setError("");
    try { await onCancelOperation(task.operation.id); await refreshWorkspace(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : pick("Could not discard proposal", "放弃方案失败")); }
    finally { setBusy(false); }
  };

  const resumeTask = async (task: WorkspaceTask) => {
    if (!task.operation || conversationRunning) return;
    if (task.status === "awaiting_target") {
      setResumeTaskId(task.operation.id);
      promptRef.current?.focus();
      return;
    }
    setBusy(true);
    setError("");
    try {
      if (task.status === "failed" && task.workflow?.operation === "generate") {
        await retryGeneration(task.workflow.job_id);
        await refreshWorkspace();
        await waitAndRefresh(task.workflow.job_id);
      } else {
        const turn = await resumeConversationOperation(task.operation.id);
        await refreshWorkspace();
        if (turn.action.job_id) await waitAndRefresh(turn.action.job_id);
      }
      await continueTaskQueue(await refreshWorkspace());
    } catch (caught) { setError(caught instanceof Error ? caught.message : pick("Task retry failed", "任务重试失败")); }
    finally { setBusy(false); }
  };

  const submitMessage = async (event: FormEvent) => {
    event.preventDefault();
    if (
      !workspace ||
      conversationRunning ||
      (!effectivePendingOperationId && !prompt.trim()) ||
      (effectivePendingOperationId && !selectedTargets.length && !prompt.trim())
    ) return;
    setPlanMessageId("");
    const content = prompt.trim();
    // Explicit UI selections are context; the server model resolves the request.
    const structuredTargets = selectedTargets.map((item) => item.target);
    const refinementSourceId = refineSourceId;
    let resolvedCaseId = selectedCaseId;
    let resolvedSelections = selectedTargets;
    setBusy(true);
    setPendingMessage(content);
    setRunningSeconds(0);
    setCurrentJobId("");
    setProgress(null);
    pendingDraftEdit.current = null;
    setPrompt("");
    setError("");
    setNotice("");
    try {
      const turn = effectivePendingOperationId
        ? await resumeConversationOperation(effectivePendingOperationId, {
            targets: structuredTargets,
            content: content || undefined,
          })
        : await sendConversationMessage(workspace.id, {
            content,
            modelId,
            scope: "current",
            knowledgeSourceIds: sourceIds,
            useSpaceKnowledge: true,
            sourceOperationId: refinementSourceId || undefined,
            targets: structuredTargets,
          });
      // Replace the optimistic echo with the server's messages before any
      // follow-up requests, so slow state saves do not hide the accepted turn.
      setWorkspace((current) => {
        if (!current || current.id !== turn.conversation_id) return current;
        const incoming = [turn.user_message, ...(turn.assistant_message ? [turn.assistant_message] : [])];
        const ids = new Set(incoming.map((message) => message.id));
        return { ...current, messages: [...current.messages.filter((message) => !ids.has(message.id)), ...incoming] };
      });
      setPendingMessage(null);
      setRefineSourceId("");
      if (turn.intent !== "SMALL_TALK") {
        viewTouchedRef.current = true;
        setPlanMessageId(turn.operation_plan?.current_operation_id ?? turn.operation_plan?.operations[0]?.id ?? "");
        setViewMode(turn.action.type === "module_created" ? "map" : "plan");
        setArtifactOpen(false);
      }
      if (turn.action.type === "module_created") await onCasesChanged();
      const resolvedOperation = turn.operation_plan?.operations.find((item) => item.target.resolved);
      if (resolvedOperation) {
        const ids = new Set(resolvedOperation.target.case_ids as string[] ?? []);
        const refs = new Set(resolvedOperation.target.candidate_refs as string[] ?? []);
        const candidateIds = new Set(candidates.filter((item) => refs.has(item.ref)).map((item) => item.id));
        const matched = visibleCases.filter((item) => ids.has(item.id) || candidateIds.has(item.id));
        resolvedSelections = [];
        for (let offset = 0; offset < matched.length; offset += 100) {
          const group = matched.slice(offset, offset + 100);
          const targets = group.map(caseTarget);
          const target: ConversationTarget = {
            kind: "case",
            case_ids: targets.flatMap((item) => item.case_ids ?? []),
            candidate_refs: targets.flatMap((item) => item.candidate_refs ?? []),
          };
          resolvedSelections.push({
            key: JSON.stringify(target), target,
            label: group.length === 1 ? group[0].title : pick(`${group.length} cases`, `${group.length} 条用例`),
          });
        }
        setSelectedTargets(resolvedSelections);
        setRewriteTargets(resolvedSelections);
        if (matched[0]) {
          resolvedCaseId = matched[0].id;
          setSelectedCaseId(resolvedCaseId);
          setMapFocusVersion((version) => version + 1);
          onSelectCase(resolvedCaseId);
        }
      }
      const retainedSelections = resolvedSelections.length === 1 &&
        ["CASE_MODIFY", "CASE_DELETE"].includes(turn.intent)
          ? resolvedSelections
          : [];
      setSelectedTargets(retainedSelections);
      setRewriteTargets(retainedSelections);
      setWorkspace(
        await updateWorkspaceState(workspace.id, {
          draft_text: "",
          active_view: turn.intent === "SMALL_TALK" ? viewMode : "plan",
          selected_case_id: resolvedCaseId,
          selected_targets: retainedSelections.map((item) => ({
            label: item.label,
            target: item.target,
          })),
        }),
      );
      const jobId = turn.action.job_id;
      if (jobId) {
        await waitAndRefresh(jobId);
      }
      if (turn.action.change_set_id) {
        const changeSet = await getCaseChangeSet(turn.action.change_set_id);
        setActiveChangeSet(changeSet);
        setAcceptedFields(
          Object.fromEntries(
            changeSet.items.map((item) => [
              item.ref,
              item.field_diff.map((diff) => diff.field),
            ]),
          ),
        );
      }
      if (effectivePendingOperationId) { setSelectedTargets([]); setResumeTaskId(""); }
      if (!turn.action.change_set_id) {
        await continueTaskQueue(await refreshWorkspace());
      }
    } catch (caught) {
      editPrompt(content);
      setError(caught instanceof Error ? caught.message : pick("Failed to process message", "消息处理失败"));
    } finally {
      setPendingMessage(null);
      setBusy(false);
    }
  };

  const confirmModification = async (operationId: string) => {
    setBusy(true);
    setError("");
    try {
      const turn = await resumeConversationOperation(operationId, { confirmModification: true });
      if (turn.action.job_id) {
        openReviewPlan(operationId);
        await waitAndRefresh(turn.action.job_id);
      } else await refreshWorkspace();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : pick("Confirmation failed", "修改确认失败"));
    } finally {
      setBusy(false);
    }
  };

  const confirmOperation = async (
    operationId: string,
    intent: ConversationIntent,
  ) => {
    setBusy(true);
    setError("");
    try {
      const turn = await resumeConversationOperation(operationId, { intent });
      if (intent !== "SMALL_TALK") openReviewPlan(operationId);
      if (turn.action.job_id) await waitAndRefresh(turn.action.job_id);
      else await refreshWorkspace();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : pick("Failed to confirm action", "意图确认失败"));
    } finally {
      setBusy(false);
    }
  };

  const stopGeneration = async () => {
    if (!currentJobId) return;
    const jobId = currentJobId;
    setError("");
    try {
      await cancelGeneration(jobId);
      await refreshWorkspace();
      setNotice(pick("Task ended. You can continue the conversation.", "任务已结束，可继续对话。"));
    } catch (caught) {
      const refreshed = await refreshWorkspace().catch(() => null);
      if (refreshed?.workflow_runs.some((run) =>
        run.job_id === jobId && terminalWorkflowStatuses.has(run.status)
      )) {
        setNotice(pick("This task has already finished.", "本次任务已结束。"));
      } else {
        setError(caught instanceof Error ? caught.message : pick("Failed to end task", "结束任务失败"));
      }
    } finally {
      setBusy(false);
      setCurrentJobId("");
      setProgress(null);
    }
  };

  const confirmBriefAndGenerate = async (selectedPointIds: string[] = []) => {
    if (!workspace) return;
    setBusy(true);
    setProgress({ name: "queued", progress: 0 });
    setLiveStages([]);
    setError("");
    setNotice(pick("Generation requested. Starting the CasePilot workflow…", "已提交生成请求，正在启动 CasePilot 工作流…"));
    try {
      if (!activeBrief) throw new Error(pick("Generate a structured test brief first", "请先生成结构化测试说明"));
      const turn = await confirmTestBrief(
        workspace.id,
        activeBrief.version,
        modelId,
        selectedPointIds,
      );
      await refreshWorkspace();
      if (turn.action.job_id) {
        await waitAndRefresh(turn.action.job_id);
      } else {
        setBusy(false);
        setProgress(null);
      }
      await continueTaskQueue(await refreshWorkspace());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : pick("Failed to confirm test brief", "测试说明确认失败"));
      setNotice("");
      setBusy(false);
      setProgress(null);
      setLiveStages([]);
    }
  };

  const confirmPendingIntent = async (
    messageId: string,
    intent: ConversationIntent,
  ) => {
    if (!workspace || busy) return;
    setBusy(true);
    setError("");
    setNotice(pick("Action confirmed. Continuing…", "已确认意图，正在继续处理…"));
    try {
      const turn = await confirmConversationIntent(messageId, intent);
      if (intent !== "SMALL_TALK") openReviewPlan(messageId);
      await refreshWorkspace();
      if (turn.action.job_id) {
        await waitAndRefresh(turn.action.job_id);
      }
      if (turn.action.change_set_id) {
        const changeSet = await getCaseChangeSet(turn.action.change_set_id);
        setActiveChangeSet(changeSet);
        setAcceptedFields(
          Object.fromEntries(
            changeSet.items.map((item) => [
              item.ref,
              item.field_diff.map((diff) => diff.field),
            ]),
          ),
        );
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : pick("Failed to confirm action", "意图确认失败"));
    } finally {
      setBusy(false);
    }
  };

  const toggleCandidate = async (
    candidate: WorkspaceCandidateDto,
    included: boolean,
  ) => {
    const updateSelection = (value: boolean) => setWorkspace(current => current ? {
      ...current,
      candidates: current.candidates.map(item => item.id === candidate.id ? { ...item, included: value } : item),
      candidate_history: current.candidate_history?.map(item => item.id === candidate.id ? { ...item, included: value } : item),
    } : current);
    setBusy(true);
    updateSelection(included);
    try {
      await updateWorkspaceCandidate(candidate.id, {
        baseVersion: candidate.version,
        included,
      });
      await refreshWorkspace();
    } catch (caught) {
      updateSelection(candidate.included);
      setError(caught instanceof Error ? caught.message : pick("Failed to save candidate status", "候选状态保存失败"));
    } finally {
      setBusy(false);
    }
  };

  const saveCandidate = async () => {
    if (!candidateDraft || candidateSaving) return;
    setCandidateSaving(true);
    setCandidateSaveMessage("");
    try {
      const saved = await updateWorkspaceCandidate(candidateDraft.id, {
        baseVersion: candidateDraft.version,
        snapshot: candidateDraft.snapshot as unknown as Record<string, unknown>,
      });
      await refreshWorkspace();
      setSelectedCaseId(saved.id);
      setCandidateDraft(structuredClone(saved));
      setCandidateSaveMessage(pick("Changes saved", "修改已保存"));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : pick("Failed to save candidate", "候选保存失败"));
    } finally {
      setCandidateSaving(false);
    }
  };

  const commitCandidates = async () => {
    if (!workspace) return;
    setBusy(true);
    try {
      const committed = await commitWorkspaceCandidates(workspace.id);
      await onCasesChanged();
      setSelectedCaseId(committed[0]?.id ?? "");
      setSelectedTargets([]);
      setRewriteTargets([]);
      await updateWorkspaceState(workspace.id, {
        selected_case_id: committed[0]?.id ?? "",
        selected_targets: [],
      });
      setNotice(pick(`${committed.length} cases added to the official collection`, `已纳入 ${committed.length} 条正式用例`));
      setArtifactOpen(false);
      const refreshed = await refreshWorkspace();
      setViewMode(refreshed?.context.active_mutation_task_id ? "plan" : "list");
      await continueTaskQueue(refreshed);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : pick("Failed to add candidates", "候选纳入失败"));
    } finally {
      setBusy(false);
    }
  };

  const applyChangeSet = async (selection = acceptedFields, reviewRefs?: string[]) => {
    if (!selectedTaskChangeSet) return;
    setBusy(true);
    setError("");
    try {
      await applyCaseChangeSet(selectedTaskChangeSet.id, selection, reviewRefs);
      setHistoricalChangeSet(null);
      setActiveChangeSet(null);
      await onCasesChanged();
      await continueTaskQueue(await refreshWorkspace());
      setNotice(reviewRefs ? pick("Review decision saved", "本条审阅决定已保存，其余建议可继续审阅") : changeAppliedNotice);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : pick("Failed to apply changes", "变更应用失败"));
      if (selectedChangeSetId) {
        const result = await getCaseChangeSet(selectedChangeSetId).catch(() => null);
        if (result) setHistoricalChangeSet(result);
        if (result?.status === "applied" || (reviewRefs?.length && result?.items.some((item) => reviewRefs.includes(item.ref) && ["applied", "rejected"].includes(item.status ?? "")))) {
          setActiveChangeSet(null);
          setError("");
          try {
            await onCasesChanged();
            await continueTaskQueue(await refreshWorkspace());
            setNotice(reviewRefs ? pick("Review decision saved", "本条审阅决定已保存，其余建议可继续审阅") : changeAppliedNotice);
          } catch {
            setError(pick("Changes were saved, but the latest view could not be loaded. Reopen this conversation when the connection recovers.", "变更已保存，但最新结果暂未加载。网络恢复后请重新打开此会话查看。"));
          }
        } else if (result?.status === "conflict") {
          setActiveChangeSet(null);
          await refreshWorkspace();
        }
      }
    } finally {
      setBusy(false);
    }
  };

  const rejectChangeSet = async () => {
    if (!selectedTaskChangeSet) return;
    setBusy(true);
    setError("");
    try {
      await rejectCaseChangeSet(selectedTaskChangeSet.id);
      setHistoricalChangeSet(null);
      setActiveChangeSet(null);
      await refreshWorkspace();
      setNotice(pick("Remaining suggestions discarded. Previously accepted changes are kept.", "未采纳的建议已丢弃，已采纳的变更保留。"));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : pick("Failed to reject changes", "拒绝变更失败"));
    } finally {
      setBusy(false);
    }
  };

  const prepareReviewDeletion = async (caseIds: string[], duplicate = true) => {
    if (!workspace || !caseIds.length || activeChangeSet) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const turn = await sendConversationMessage(workspace.id, {
        content: duplicate
          ? "删除选中的重复用例；保留用例已在检查计划中指定。"
          : "删除选中的用例。",
        modelId,
        scope: "current",
        targetCaseIds: caseIds,
        intentOverride: "CASE_DELETE",
        sourceOperationId: selectedTask?.operation?.id,
      });
      setPlanMessageId("");
      if (!turn.action.change_set_id) throw new Error(pick("Could not prepare deletion review", "未能生成删除审阅单"));
      const changeSet = await getCaseChangeSet(turn.action.change_set_id);
      setActiveChangeSet(changeSet);
      setAcceptedFields(Object.fromEntries(changeSet.items.map((item) => [item.ref, ["delete"]])));
      await refreshWorkspace();
      setNotice(pick("Deletion review is ready. Confirm the affected cases in the workspace.", "删除审阅单已生成，请在工作区核对受影响用例。"));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : pick("Could not prepare deletion review", "未能生成删除审阅单"));
    } finally {
      setBusy(false);
    }
  };

  const persistPanelWidth = (
    panel: "chat" | "inspector",
    value: number,
  ) => {
    if (!workspace) return;
    void updateWorkspaceState(
      workspace.id,
      panel === "chat"
        ? { chat_width: value }
        : { inspector_width: value },
    ).then(setWorkspace, () => undefined);
  };

  const startPanelResize = (
    panel: "chat" | "inspector",
    event: ReactPointerEvent<HTMLDivElement>,
  ) => {
    event.preventDefault();
    const separator = event.currentTarget;
    const pointerId = event.pointerId;
    separator.setPointerCapture(pointerId);
    const startX = event.clientX;
    const startWidth = panel === "chat" ? chatWidth : inspectorWidth;
    let latestWidth = startWidth;
    let frameId: number | null = null;
    const renderPreview = () => {
      frameId = null;
      if (panel === "chat") setChatWidth(latestWidth);
      else setInspectorWidth(latestWidth);
    };
    const move = (pointerEvent: PointerEvent) => {
      const delta =
        panel === "chat"
          ? pointerEvent.clientX - startX
          : startX - pointerEvent.clientX;
      const next = clampPanelWidth(panel, startWidth + delta);
      latestWidth = next;
      if (frameId === null) {
        frameId = window.requestAnimationFrame(renderPreview);
      }
    };
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
      window.removeEventListener("blur", stop);
      if (separator.hasPointerCapture(pointerId)) {
        separator.releasePointerCapture(pointerId);
      }
      if (frameId !== null) {
        window.cancelAnimationFrame(frameId);
        frameId = null;
      }
      separator.style.transform = "";
      if (panel === "chat") setChatWidth(latestWidth);
      else setInspectorWidth(latestWidth);
      persistPanelWidth(panel, latestWidth);
      document.documentElement.classList.remove("is-resizing-workbench");
    };
    document.documentElement.classList.add("is-resizing-workbench");
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop, { once: true });
    window.addEventListener("pointercancel", stop, { once: true });
    window.addEventListener("blur", stop, { once: true });
  };

  const resizeWithKeyboard = (
    panel: "chat" | "inspector",
    key: string,
  ) => {
    if (!["ArrowLeft", "ArrowRight"].includes(key)) return;
    const direction = key === "ArrowRight" ? 1 : -1;
    const delta = panel === "chat" ? direction * 16 : direction * -16;
    const current = panel === "chat" ? chatWidth : inspectorWidth;
    const next = clampPanelWidth(panel, current + delta);
    if (panel === "chat") setChatWidth(next);
    else setInspectorWidth(next);
    persistPanelWidth(panel, next);
  };

  const resetPanelWidth = (panel: "chat" | "inspector") => {
    const defaultWidth = panel === "chat" ? 400 : 300;
    if (panel === "chat") setChatWidth(defaultWidth);
    else setInspectorWidth(defaultWidth);
    persistPanelWidth(panel, defaultWidth);
  };

  const selectBriefVersion = (version: number) => {
    setSelectedBriefVersion(version);
    setArtifactOpen(true);
    if (workspace) {
      void updateWorkspaceState(workspace.id, {
        selected_brief_version: version,
      }).then(setWorkspace, () => undefined);
    }
  };

  const copyBrief = async () => {
    if (!selectedBrief) return;
    try {
      await navigator.clipboard.writeText(selectedBrief.markdown_content);
      setNotice(pick(`Copied structured test brief V${selectedBrief.version}`, `已复制结构化测试说明 V${selectedBrief.version}`));
    } catch {
      setError(pick("Copy failed. Check browser clipboard permissions.", "复制失败，请检查浏览器剪贴板权限。"));
    }
  };

  const saveBriefFile = async () => {
    if (!workspace || !selectedBrief || !selectedCollection) return;
    try {
      const blob = await downloadTestBrief(workspace.id, selectedBrief.version);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      const safeName =
        selectedCollection.name.replace(/[\\/:*?"<>|]/g, "").trim() ||
        "CasePilot";
      anchor.href = url;
      anchor.download = `${safeName}-${pick("structured-test-brief", "结构化测试说明")}-V${selectedBrief.version}.md`;
      anchor.click();
      URL.revokeObjectURL(url);
      setNotice(pick(`Downloaded structured test brief V${selectedBrief.version}`, `已下载结构化测试说明 V${selectedBrief.version}`));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : pick("Failed to download test brief", "下载测试说明失败"));
    }
  };

  if (!selectedCollection) {
    return <div className="principle-empty">{pick("Select a test case collection first", "请先选择一个用例集合")}</div>;
  }

  return (
    <section
      className="principle-workbench"
      aria-busy={busy}
      data-inspector-collapsed={inspectorCollapsed}
      style={
        {
          "--chat-width": `${chatWidth}px`,
          "--inspector-width": `${inspectorWidth}px`,
        } as CSSProperties
      }
    >
      <aside className="principle-chat">
        <div className="principle-context-card" title={spaceName}>
          <span>{pick("Current workspace", "当前工作区")}</span>
          <strong>{selectedCollection.name}</strong>
        </div>

        <div
          className="principle-messages"
          aria-live="polite"
          ref={messagesScrollRef}
        >
          <div className="principle-messages-content" ref={messagesContentRef}>
            {!messages.length && pendingMessage === null && (
              <div className="principle-agent-intro">
                <Bot size={20} />
                <div>
                  <strong>CasePilot</strong>
                  <p>
                    {pick(
                      "Describe what you want to test. CasePilot will analyze the remaining context and organize it into a structured test brief.",
                      "请先说明测试对象；其他测试内容由 CasePilot 分析并整理为结构化测试说明。",
                    )}
                  </p>
                </div>
              </div>
            )}
            <ConversationTaskFlow tasks={tasks} labels={localizedIntentLabels} statusLabels={localizedOperationStatusLabels} busy={conversationRunning} onResume={(task) => void resumeTask(task)} onResult={openReviewPlan} />
            {messages.map((message) => {
            const workflow = workflowByMessageId.get(message.id);
            const isLiveWorkflow = Boolean(currentJobId) &&
              !(workflow && terminalWorkflowStatuses.has(workflow.status)) &&
              (workflow?.job_id === currentJobId || message.related_job_id === currentJobId);
            const persistedStages = workflow?.stages ?? [];
            const renderedStages = summarizeWorkflowStages(
              isLiveWorkflow && liveStages.length
                ? liveStages
                    .filter((stage) => stage.name !== progress?.name)
                    .map((stage) => ({
                      stage: stage.name,
                      progress: stage.progress,
                      status: "completed",
                    }))
                : persistedStages).filter(stage => !isLiveWorkflow || stage.stage !== progress?.name);
            const report = message.metadata.analysis_report as CaseReviewReport | undefined;
            const conversationTask = tasks.find((task) => task.messageIds.includes(message.id));
            const querySnapshots = message.intent === "CASE_QUERY" && conversationTask?.message.id === message.id ? conversationTask.operation?.result.query_cases as TestCaseDto[] | undefined : undefined;
            const artifactVersion = Number(message.metadata.brief_version ?? 0);
            const analysisCount = Number(
              message.metadata.target_count ?? message.metadata.checked_case_count ?? 0,
            );
            const hasAnalysisReport = Boolean(report);
            const showAnalysisDetails = !hasAnalysisReport;
            const affectedCaseCount = report ? new Set(report.findings.flatMap((finding) => finding.case_refs)).size : 0;
            const highFindingCount = report?.findings.filter((finding) => finding.severity === "high").length ?? 0;
            const isMutationSummary = message.role === "assistant" &&
              ["CASE_GENERATE", "CASE_MODIFY", "CASE_DELETE"].includes(message.intent ?? "") &&
              (Boolean(message.metadata.change_set_id) || artifactVersion > 0 || Boolean(workflow));
            const resolvedChange = message.metadata.change_set_id ? messages.findLast((item) =>
              item.metadata.change_set_id === message.metadata.change_set_id && ["applied", "rejected"].includes(String(item.metadata.action)),
            ) : undefined;
            const mutationSummary = resolvedChange && resolvedChange.id !== message.id
              ? resolvedChange.metadata.action === "applied" ? pick("This change has been applied.", "此变更已应用。") : pick("This change was cancelled.", "此变更已取消。")
              : ["applied", "partially_reviewed", "rejected", "candidates_committed"].includes(String(message.metadata.action)) || message.status === "failed" || message.status === "cancelled"
              ? message.content
              : conversationTask?.operation?.result.no_changes || message.metadata.no_changes
                ? pick("Review complete. No changes are needed; existing cases are unchanged.", "检查已完成，无需修改，现有用例保持不变。")
              : artifactVersion > 0 && message.metadata.artifact_type === "test_brief"
                ? pick(`Test brief V${artifactVersion} is ready. Review it in the workspace.`, `测试说明 V${artifactVersion} 已准备好，请在工作区审阅。`)
                : message.status === "running"
                  ? pick("Processing your request. A summary will appear here; case results will appear in the workstation.", "正在处理请求。这里将展示结果摘要，用例结果将在工作区展示。")
                  : message.intent === "CASE_GENERATE"
                    ? pick("Candidate cases are ready for review in the workspace.", "候选用例已准备好，请在工作区审阅并纳入集合。")
                    : Number(message.metadata.task_revision ?? 1) > 1
                      ? pick(`Updated ${message.target_case_ids?.length ?? 0} cases this round. This task contains ${message.metadata.task_case_count ?? message.target_case_ids?.length ?? 0} cases for review.`, `本轮调整 ${message.target_case_ids?.length ?? 0} 条用例，本任务共 ${message.metadata.task_case_count ?? message.target_case_ids?.length ?? 0} 条用例待审阅，请在工作区确认。`)
                    : pick(`Prepared changes for ${message.target_case_ids?.length ?? 0} cases. Review and confirm them in the workspace.`, `已准备 ${message.target_case_ids?.length ?? 0} 条用例的变更，请在工作区审阅确认。`);
            return (
              <article
                key={message.id}
                id={`case-message-${message.id}`}
                className={`principle-message is-${message.role}`}
              >
                <span>
                  {messageLabel(
                    message.role,
                    message.intent,
                    message.metadata,
                    localizedIntentLabels,
                    pick("You", "你"),
                    pick("Test brief", "测试说明"),
                  )}
                </span>
                {hasAnalysisReport && (
                  <div className="principle-analysis-summary">
                    <div>
                      <strong>{pick("What I found", "检查结论")}</strong>
                      <p className="principle-review-answer">{report?.summary || pick("The review is complete. See the findings below.", "检查已完成，具体发现如下。")}</p>
                      <p className="principle-review-count">{pick(
                        `Checked ${analysisCount} cases. Found ${report?.findings.length ?? 0} groups (${highFindingCount} high priority), involving ${affectedCaseCount} case references. Changes require review and confirmation.`,
                        `已检查 ${analysisCount} 条用例，发现 ${report?.findings.length ?? 0} 组问题（高优先级 ${highFindingCount} 组），涉及 ${affectedCaseCount} 条用例引用。变更需审阅并确认。`,
                      )}</p>
                    </div>
                    <button type="button" onClick={() => openReviewPlan(message.id)}>
                      {pick("View plan in workspace", "在工作区查看计划")}
                      {(report?.findings.length ?? 0) > 3 && ` · ${report?.findings.length}`}
                    </button>
                    {message.id === messages.findLast((item) => Boolean(item.metadata.analysis_report))?.id && (
                      <div className="principle-review-followups">
                        <span>{pick("Continue from these findings", "接下来可以")}</span>
                        <button type="button" disabled={busy || Boolean(prompt.trim())} onClick={() => {
                          editPrompt(pick(
                            `Explain the evidence and priorities for these findings, without changing cases: ${report?.summary} ${report?.findings.slice(0, 3).map((item) => item.title).join("; ")}`,
                            `请解释以下检查发现的依据和处理优先级，暂不修改用例：${report?.summary} ${report?.findings.slice(0, 3).map((item) => item.title).join("；")}`,
                          ));
                          promptRef.current?.focus();
                        }}>{pick("Discuss priorities", "继续分析处理优先级")}</button>
                        {message.intent === "COVERAGE_ANALYZE" && Boolean(report?.findings.length) && (
                          <button type="button" disabled={busy || Boolean(prompt.trim())} onClick={() => {
                            editPrompt(pick(
                              `Prepare additional candidate cases for the current collection based on these coverage suggestions, for my review before inclusion: ${report?.findings.map((item) => `${item.title}: ${item.recommendation}`).join("; ")}`,
                              `请针对以下覆盖建议，为当前集合补充候选用例，先供我审阅再纳入正式集合：${report?.findings.map((item) => `${item.title}：${item.recommendation}`).join("；")}`,
                            ));
                            promptRef.current?.focus();
                          }}>{pick("Draft missing cases", "补充遗漏用例")}</button>
                        )}
                        <small>{pick("Adds a draft to the composer for you to edit and send.", "点击填入输入框，可调整后发送。")}</small>
                      </div>
                    )}
                  </div>
                )}
                {isMutationSummary && !isLiveWorkflow && message.status !== "running" && (
                  <p className="principle-mutation-result">{mutationSummary}</p>
                )}
                {querySnapshots && <div className="principle-analysis-summary"><div><strong>{pick(`Found ${querySnapshots.length} cases`, `找到 ${querySnapshots.length} 条用例`)}</strong><p>{[...new Set(querySnapshots.map((item) => item.module))].join(" · ") || pick("No matching cases", "暂无匹配用例")}</p></div><button type="button" onClick={() => openReviewPlan(message.id)}>{pick("View table", "查看结果表格")}</button></div>}
                <ConversationAttachments metadata={message.metadata} />
                {message.content && showAnalysisDetails && !isMutationSummary && !querySnapshots && (
                  <Streamdown
                    animated={{
                      animation: "fadeIn",
                      duration: 90,
                      easing: "ease-out",
                      sep: "char",
                      stagger: 8,
                    }}
                    caret="block"
                    isAnimating={isLiveWorkflow}
                  >
                    {message.content}
                  </Streamdown>
                )}
                {message.status === "awaiting_intent" && (
                  <div className="conversation-intent-confirmation">
                    <span>{pick("Choose what you want CasePilot to do:", "请选择这句话希望 CasePilot 执行的操作：")}</span>
                    <div>
                      {[
                        ...(message.intent && message.intent !== "UNRESOLVED" ? [message.intent] : []),
                        ...actionableIntents.filter((intent) => intent !== message.intent),
                      ]
                        .filter(
                          (intent): intent is ConversationIntent =>
                            Boolean(intent),
                        )
                        .map((intent) => (
                          <button
                            type="button"
                            key={intent}
                            disabled={busy}
                            onClick={() =>
                              void confirmPendingIntent(message.id, intent)
                            }
                          >
                            {localizedIntentActionLabels[intent]}
                          </button>
                        ))}
                    </div>
                  </div>
                )}
                {conversationTask?.message.id === message.id && conversationTask.operation?.status === "awaiting_target" && (
                  <div className="principle-review-followups">
                    <span>{pick("Reply below to clarify this task.", "直接在下方回复，即可补充当前任务。")}</span>
                    {message.metadata.modification_confirmation === true && (
                      <button type="button" disabled={busy || conversationRunning} onClick={() => void confirmModification(conversationTask.operation!.id)}>{pick("Confirm modification", "确认修改并生成建议")}</button>
                    )}
                    <button type="button" disabled={conversationRunning} onClick={() => { setResumeTaskId(conversationTask.id); promptRef.current?.focus(); }}>{pick("Provide details", "补充信息")}</button>
                    <button type="button" disabled={conversationRunning} onClick={() => { setResumeTaskId(""); void discardTask(conversationTask); }}>{pick("End task", "结束任务")}</button>
                  </div>
                )}
                {message.metadata.action === "new_conversation_required" && (
                  <div className="conversation-cross-collection">
                    <span>{pick("This conversation is locked to this collection and cannot make cross-collection changes.", "当前对话已锁定此集合，不会执行跨集合变更。")}</span>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        const collectionId = String(
                          message.metadata.requested_collection_id ?? "",
                        );
                        const operationId = String(
                          message.metadata.operation_id ?? "",
                        );
                        if (operationId && collectionId) {
                          void onContinueInNewConversation(
                            operationId,
                            collectionId,
                          );
                        }
                      }}
                    >
                      {pick("Start a conversation in that collection", "新建对话并打开该集合")}
                    </button>
                    <button
                      type="button"
                      className="is-secondary"
                      disabled={busy}
                      onClick={() => {
                        const operationId = String(
                          message.metadata.operation_id ?? "",
                        );
                        if (operationId) {
                          void onCancelOperation(operationId).then(async () => {
                            if (workspace) {
                              setWorkspace(await getConversation(workspace.id));
                            }
                          });
                        }
                      }}
                    >
                      {pick("Cancel this operation", "取消本次操作")}
                    </button>
                  </div>
                )}
                {!message.metadata.hidden_progress &&
                  (workflow || isLiveWorkflow) &&
                  (
                  <details
                    open={workflow?.status === "failed"}
                    className="principle-workflow is-compact"
                    data-status={workflow?.status ?? "running"}
                  >
                    <summary>{pick("Processing steps", "处理过程")} · {isLiveWorkflow ? pick("In progress", "进行中") : workflow?.status === "failed" ? pick("Failed", "未完成") : workflow?.status === "cancelled" ? pick("Stopped", "已停止") : pick("Completed", "已完成")}</summary>
                    {renderedStages.map((stage, index) => (
                      <div
                        key={`${stage.stage}-${index}`}
                        className={`principle-workflow-stage is-${stage.status}`}
                      >
                        {stage.status === "completed" ? <Check size={13} /> : <CircleAlert size={13} />}
                        <span>
                          {localizedWorkflowStageLabels[stage.stage] ?? pick("Processing task", "处理任务")}
                        </span>

                      </div>
                    ))}
                    {isLiveWorkflow && progress && (
                      <div className="principle-workflow-stage is-running">
                        <LoaderCircle className="auth-spinner" size={13} />
                        <span>
                          {localizedWorkflowStageLabels[progress.name] ?? pick("Processing", "正在处理")}
                        </span>
                        <small>{progress.progress}%</small>
                      </div>
                    )}
                    {workflow &&
                      terminalWorkflowStatuses.has(workflow.status) && (
                        <div
                          className={`principle-workflow-result is-${workflow.status}`}
                        >
                          {workflow.status === "completed"
                            ? pick("Completed", "处理完成")
                            : workflow.status === "cancelled"
                              ? pick("Stopped. You can edit or start again.", "已停止，可继续修改或重新开始")
                              : pick("Processing did not complete. Try again.", "处理未完成，请重试")}
                        </div>
                      )}
                    {message.status === "failed" &&
                      message.related_job_id &&
                      messages.at(-1)?.id === message.id && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void retryFailedMessage(message.id)}
                        >
                          {pick("Retry this request", "重试本次请求")}
                        </button>
                      )}
                  </details>
                  )}
                {artifactVersion > 0 && message.role === "assistant" && message.metadata.artifact_type === "test_brief" && (
                  <button
                    type="button"
                    className="principle-artifact-link"
                    onClick={() => selectBriefVersion(artifactVersion)}
                  >
                    <FileUp size={14} />
                    {pick("Structured test brief", "结构化测试说明")} V{artifactVersion}.md
                  </button>
                )}
                {conversationTask?.message.id === message.id && !["KNOWLEDGE_QA", "UNRESOLVED"].includes(message.intent ?? "") && !hasAnalysisReport && !isMutationSummary && !querySnapshots && (
                  <button type="button" className="principle-artifact-link" onClick={() => openReviewPlan(message.id)}>
                    <Sparkles size={14} />{pick("View case result", "查看用例结果")}
                  </button>
                )}
                {Boolean(message.metadata.workstation_task_id) && <button type="button" className="principle-artifact-link" onClick={() => openReviewPlan(String(message.metadata.workstation_task_id))}>{pick("Go to workstation review", "前往工作区审阅")}</button>}
                {message.citations.length > 0 && (
                  <small>
                    {pick("Sources: ", "来源：")}
                    {message.citations.map((item) => item.label).join("、")}
                  </small>
                )}
              </article>
            );
            })}
            {pendingMessage !== null && (
              <article className="principle-message is-user" data-testid="pending-conversation-message">
                <span>{pick("You", "你")}</span>
                <p style={{ whiteSpace: "pre-wrap" }}>{pendingMessage || pick("Continue this task", "继续当前任务")}</p>
              </article>
            )}
            {pendingMessage !== null && (
              <article className="principle-message is-assistant" role="status" aria-live="polite" data-testid="scope-thinking">
                <span><LoaderCircle className="auth-spinner" size={16} /> {pick("Thinking…", "正在思考…")}</span>
                <p>{pick("Understanding your request and selecting relevant cases…", "正在理解你的需求并筛选相关用例…")}</p>
                <small aria-hidden="true">{pick(`Elapsed ${runningSeconds}s`, `已等待 ${runningSeconds} 秒`)}</small>
                {runningSeconds >= 20 && <p>{pick("Still analyzing. Selected cases will appear when ready.", "仍在分析中，完成后会展示选中的用例。")}</p>}
              </article>
            )}
          </div>
        </div>

        {activeMutationTask && activeMutationTask.status !== "awaiting_target" && viewMode !== "plan" && !planningPreview && <div className="principle-change-set-link" role="status" data-testid="active-mutation-task-notice">
          <span>{pick("This task is still open. Further edits stay here until you accept or abandon it. Queries are separate tasks.", "当前任务尚未结束，后续修改将继续此任务；查询会单独建立任务。请在工作区完成采纳或放弃，之后才可开始新的生成或修改任务。")}</span>
          <button type="button" onClick={() => openReviewPlan(activeMutationTask.id)}>{pick("Go to workstation review", "前往工作区审阅")}</button>
        </div>}
        {activeChangeSet && !activeMutationTask && (
          <div className="principle-change-set-link">
            <span>{pick(`${activeChangeSet.items.filter(item => !["applied", "rejected"].includes(item.status ?? "")).length} cases awaiting change review`, `${activeChangeSet.items.filter(item => !["applied", "rejected"].includes(item.status ?? "")).length} 条用例待审阅变更`)}</span>
            <button type="button" onClick={() => openReviewPlan(tasks.find((task) => task.message.metadata.change_set_id === activeChangeSet.id)?.id)}>{pick("Review in workspace", "在工作区审阅")}</button>
          </div>
        )}

        <form className="principle-composer" onSubmit={submitMessage}>
          {showOperationPlan && operationPlan && (
              <ol className="conversation-operation-plan" aria-label={pick("Multi-action progress", "多意图执行进度")}>
                {pendingIntentOperations.map((operation) => (
                  <li key={operation.id} data-status={operation.status}>
                    <span>{operation.sequence + 1}</span>
                    <strong>{localizedIntentActionLabels[operation.intent]}</strong>
                    <small>
                      {localizedOperationStatusLabels[operation.status] ?? pick("Processing", "处理中")}
                    </small>
                    {operation.status === "awaiting_intent" && (
                      <div className="conversation-operation-confirmation">
                        {actionableIntents.map((intent) => (
                          <button
                            type="button"
                            key={intent}
                            disabled={conversationRunning}
                            onClick={() => void confirmOperation(operation.id, intent)}
                          >
                            {localizedIntentActionLabels[intent]}
                          </button>
                        ))}
                      </div>
                    )}
                  </li>
                ))}
              </ol>
            )}
          {singleRewriteTarget && (
            <div className="principle-target-context" aria-label={pick("AI rewrite targets", "AI 修改目标")}>
              <span><Sparkles size={14} /> {pick("Rewrite targets", "修改目标")}</span>
              <div className="principle-targets">
                {displayedTargets.map((item) => (
                  <button
                    type="button"
                    key={item.key}
                    onClick={() => toggleTarget(item.target, item.label)}
                    title={item.label}
                    aria-label={pick(`Remove rewrite target: ${item.label}`, `移除修改目标：${item.label}`)}
                    disabled={rewriteStatus === "running" || rewriteStatus === "review"}
                  >
                    <span>{item.label}</span>
                    <X size={13} aria-hidden="true" />
                  </button>
                ))}
              </div>
            </div>
          )}
          {rewriteStatus !== "idle" && rewriteStatus !== "selected" && (
            <div
              className={`principle-rewrite-status is-${rewriteStatus}`}
              aria-label={pick("AI rewrite status", "AI 改写状态")}
              aria-live="polite"
            >
              <span className="principle-rewrite-status__icon">
                {rewriteStatus === "running" ? (
                  <LoaderCircle size={16} />
                ) : rewriteStatus === "review" ? (
                  <Sparkles size={16} />
                ) : (
                  <CheckCircle2 size={16} />
                )}
              </span>
              <span>
                <strong>
                  {rewriteStatus === "running"
                    ? (activeRewriteOperation ? localizedIntentLabels[activeRewriteOperation.intent] : pick("Working", "正在处理"))
                    : rewriteStatus === "review"
                      ? pick("Rewrite complete, awaiting review", "改写完成，等待审阅")
                      : pick("Changes applied", "修改已应用")}
                </strong>
                <small>
                  {rewriteStatus === "running"
                    ? pick(`Working on ${activeRewriteTargets.length} cases. Review results in the workspace.`, `正在处理 ${activeRewriteTargets.length} 条用例，请在工作区审阅结果。`)
                    : rewriteStatus === "review"
                      ? pick("Review the field differences; only confirmed changes will be saved", "请检查字段差异；确认后才保存所选修改")
                      : pick("Saved as a new version and synced to the workspace", "已保存为新版本，工作区内容已同步更新")}
                </small>
              </span>
              {rewriteStatus === "running" && (
                <i className="principle-rewrite-status__track" aria-hidden="true" />
              )}
            </div>
          )}
          {attachments.length > 0 && (
            <div className="principle-attachments">
              {attachments.map((file) => (
                <div key={file.id} className="principle-attachment" data-status={file.status}>
                  <FileUp size={20} aria-hidden="true" />
                  <div className="principle-attachment__body">
                    <strong title={file.name}>{file.name}</strong>
                    <small role="status">{Math.max(1, Math.round(file.size / 1024))} KB · {file.status === "ready" ? pick("Ready", "已就绪") : file.status === "failed" ? pick("Failed · select file to retry", "失败 · 请重新选择文件") : file.status === "processing" ? pick("Uploaded · processing document", "已上传 · 正在解析资料") : pick(`Uploading ${file.percent}%`, `上传中 ${file.percent}%`)}</small>
                    {file.status === "uploading" && <progress aria-label={pick(`Upload progress for ${file.name}`, `${file.name} 上传进度`)} value={file.percent} max={100} />}
                  </div>
                  {file.status === "ready" ? <CheckCircle2 size={16} aria-label={pick("Ready", "已就绪")} /> : file.status === "failed" ? <CircleAlert size={16} /> : <LoaderCircle size={16} className="auth-spinner" aria-hidden="true" />}
                </div>
              ))}
            </div>
          )}
          <ConversationAttachments pending metadata={{ attachments: (
            Array.isArray(workspace?.context.pending_attachments) ? workspace.context.pending_attachments : []
          ).filter((file: { name: string }) => !attachments.some(local => local.name === file.name)) }} />
          {resumeTaskId && <div className="case-conversation-running"><span>{pick("Replying to task clarification", "正在补充当前任务信息")}</span><button type="button" disabled={conversationRunning} onClick={() => setResumeTaskId("")}>{pick("Cancel reply", "取消补充")}</button></div>}
          {conversationRunning && <div className="case-conversation-running" role="status">
            <LoaderCircle size={16} className="auth-spinner" />
            <span>{runningLabel}{progress?.active_batches?.length ? pick(` · Processing ${progress.active_batches.length} batches`, ` · 同时处理 ${progress.active_batches.length} 批`) : progress?.batch_start_index && progress?.batch_count ? pick(` · Current batch: cases ${progress.batch_start_index}–${progress.batch_start_index + progress.batch_count - 1}`, ` · 当前批次：第 ${progress.batch_start_index}–${progress.batch_start_index + progress.batch_count - 1} 条`) : ""}{progress && pendingMessage === null ? ` · ${progress.progress}%` : ""} · {pick(`Elapsed ${runningSeconds}s`, `已等待 ${runningSeconds} 秒`)}</span>
          </div>}
          {refineSourceId && <p role="status">{pick("Refining the selected result; earlier edits will be preserved.", "正在继续调整所选结果；未要求改变的已有修改将保留。")} <button type="button" onClick={() => setRefineSourceId("")}>{pick("Cancel", "取消续改")}</button></p>}
          <textarea
            ref={promptRef}
            value={prompt}
            onChange={(event) => editPrompt(event.target.value)}
            placeholder={
              conversationRunning ? pick("Task is running. Please wait for the result…", "任务正在执行，请等待结果…") : effectivePendingOperationId
                ? pick("Provide details or select cases to continue this task", "补充需求或选择用例后，继续执行当前任务")
                : singleRewriteTarget
                  ? pick(`Describe how you want to modify “${displayedTargets[0].label}”…`, `描述你希望如何修改「${displayedTargets[0].label}」…`)
                : pick("Continue refining the test brief, maintain test cases, or ask about the requirements…", "继续修改测试说明、维护当前用例，或询问需求内容…")
            }
            aria-label={singleRewriteTarget
              ? pick("Modify selected case with natural language", "用自然语言修改选中用例")
              : pick("Conversation message", "对话消息")}
            rows={4}
            disabled={conversationRunning || !workspace}
          />
          <div>
            <input
              ref={fileRef}
              hidden
              type="file"
              multiple
              onChange={(event) => void handleFiles(event)}
            />
            <button
              type="button"
              className="is-icon"
              onClick={() => fileRef.current?.click()}
              disabled={uploading || conversationRunning}
              aria-label={pick("Add attachment", "添加附件")}
            >
              {uploading ? (
                <LoaderCircle className="auth-spinner" size={18} />
              ) : (
                <Paperclip size={18} />
              )}
            </button>
            <select
              aria-label={pick("Generation model", "生成模型")}
              value={modelId}
              onChange={(event) => {
                const nextModelId = event.target.value;
                setModelId(nextModelId);
                if (workspace) {
                  void updateWorkspaceState(workspace.id, {
                    model_id: nextModelId,
                  }).then(setWorkspace, () => undefined);
                }
              }}
              disabled={conversationRunning}
            >
              {models.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.label}
                </option>
              ))}
            </select>
            {conversationRunning && currentJobId ? (
              <button
                type="button"
                className="principle-stop"
                onClick={() => void stopGeneration()}
              >
                <Square size={16} /> {pick("End task", "结束任务")}
              </button>
            ) : conversationRunning ? (
              <button type="button" disabled>
                <LoaderCircle className="auth-spinner" size={16} /> {pick("Processing", "正在处理")}
              </button>
            ) : (
              <button
                type="submit"
                disabled={
                  conversationRunning || uploading ||
                  !workspace ||
                  (effectivePendingOperationId
                    ? !selectedTargets.length && !prompt.trim()
                    : !prompt.trim())
                }
              >
                <Send size={16} /> {effectivePendingOperationId
                  ? pick("Continue changes", "继续执行修改")
                  : singleRewriteTarget
                    ? pick("Rewrite with AI", "让 AI 修改")
                    : pick("Send", "发送")}
              </button>
            )}
          </div>
        </form>
      </aside>

      <div
        className="principle-resizer"
        role="separator"
        aria-label={pick("Resize conversation panel", "调整对话区域宽度")}
        aria-orientation="vertical"
        aria-valuemin={420}
        aria-valuemax={720}
        aria-valuenow={chatWidth}
        tabIndex={0}
        onPointerDown={(event) => startPanelResize("chat", event)}
        onDoubleClick={() => resetPanelWidth("chat")}
        onKeyDown={(event) => {
          if (event.key.startsWith("Arrow")) event.preventDefault();
          resizeWithKeyboard("chat", event.key);
        }}
      >
        <i />
      </div>

      <main className="principle-canvas">
        <header>
          <div>
            <small>{pick("Case Workstation / Test case collection", "Case Workstation / 用例工作区")}</small>
            <div className="principle-title-row">
              <h1>{selectedCollection.name}</h1>
              <CollectionStatusBadge status={collectionStatus} />
            </div>
            <p>
              {localizedPhaseLabels[phase] ?? pick("Workspace restored", "工作区已恢复")} · {pick("This conversation only maintains this collection", "本对话仅维护此集合")}
            </p>
          </div>
          <div className="principle-canvas-actions">
            {visibleCases.length > 0 && !artifactOpen && (
              <button
                type="button"
                aria-label={inspectorCollapsed ? pick("Show case details", "显示用例详情") : pick("Hide case details", "隐藏用例详情")}
                title={inspectorCollapsed ? pick("Show case details", "显示用例详情") : pick("Hide case details", "隐藏用例详情")}
                aria-pressed={!inspectorCollapsed}
                onClick={() => setInspectorHidden((current) => !current)}
              >
                <PanelRight size={17} />
                <span>{inspectorCollapsed
                  ? pick("Show case details", "显示用例详情")
                  : pick("Hide case details", "隐藏用例详情")}</span>
              </button>
            )}
            <button type="button" onClick={onOpenHistory} aria-label={pick("Conversation history", "历史对话")} title={pick("Conversation history", "历史对话")}>
              <History size={17} />
              <span>{pick("Conversation history", "历史对话")}</span>
            </button>
            <button
              type="button"
              className="principle-new-conversation"
              aria-label={pick("New conversation", "创建新对话")}
              title={pick("New conversation", "创建新对话")}
              onClick={onNewConversation}
            >
              <MessageSquarePlus size={17} />
              <span>{pick("New conversation", "创建新对话")}</span>
            </button>
          </div>
        </header>

        {error && (
          <div className="principle-banner is-error" role="alert">
            <CircleAlert size={17} />
            <span>{error}</span>
            <button type="button" aria-label={pick("Dismiss notification", "关闭提示")} onClick={() => setError("")}>
              <X size={16} />
            </button>
          </div>
        )}

        {planningPreview ? (
          <section className="principle-brief planning-live-preview" aria-label={pick("Live test planning", "实时测试规划")}>
            <header className="principle-brief-toolbar">
              <div className="principle-brief-identity">
                <LoaderCircle className="auth-spinner" size={19} />
                <div>
                  <strong>{planningPreview.test_object || pick("Test planning", "测试规划")}</strong>
                  <span role="status">{planningProgress?.total_batches
                    ? pick(`${planningProgress.completed_batches ?? 0}/${planningProgress.total_batches} batches complete · ${planningProgress.test_point_count ?? 0} test points ready`,
                      `已完成 ${planningProgress.completed_batches ?? 0}/${planningProgress.total_batches} 批 · ${planningProgress.test_point_count ?? 0} 个测试点已就绪`)
                    : pick("Requirements ready · Organizing features", "需求说明已就绪 · 正在拆解功能点")}</span>
                </div>
              </div>
              <div className="planning-live-progress">
                <progress aria-label={pick("Planning progress", "规划进度")} value={planningProgress?.progress ?? 22} max={100} />
                <span>{planningProgress?.progress ?? 22}%</span>
              </div>
            </header>
            <div className="principle-brief-guidance">
              {pick("Completed batches appear below. You can confirm the plan when all batches finish.", "每完成一批就显示在下方，全部完成后即可确认规划并生成用例。")}
              {!!planningProgress?.active_batches?.length && <p>{pick("Generating: ", "正在生成：")}{planningProgress.active_batches.map(batch => batch.features.join("、")).join("；")}</p>}
            </div>
            <p className="planning-live-objective">{planningPreview.test_objective}</p>
            <div className="planning-live-features">
              {planningPreview.planning?.feature_points.map(feature => {
                const points = planningPreview.planning!.test_points.filter(point => point.feature_point_ids.includes(feature.id));
                return <details key={feature.id} open>
                  <summary>{feature.name} · {points.length ? pick(`${points.length} test points ready`, `${points.length} 个测试点已就绪`) : pick("Pending", "等待生成")}</summary>
                  <p>{feature.description}</p>
                  <ul>{points.map(point => <li key={point.id}><strong>{point.title}</strong><p>{point.objective}</p></li>)}</ul>
                </details>;
              })}
            </div>
          </section>
        ) : artifactOpen && selectedBrief ? (
          <section className="principle-brief">
            <header className="principle-brief-toolbar">
              <div className="principle-brief-identity">
                <Sparkles size={19} />
                <div>
                  <strong>{pick("Structured test brief", "结构化测试说明")}</strong>
                  <span>
                    {selectedBrief.status === "confirmed"
                      ? pick("Confirmed", "已确认")
                      : selectedBrief.status === "superseded"
                        ? pick("Previous version · Superseded", "历史版本 · 已失效")
                        : pick("Autosaved draft", "自动保存草稿")}
                  </span>
                </div>
              </div>
              <label>
                <span>{pick("Version", "版本")}</span>
                <select
                  aria-label={pick("Test brief version", "测试说明版本")}
                  value={selectedBrief.version}
                  onChange={(event) =>
                    selectBriefVersion(Number(event.target.value))
                  }
                >
                  {workspace?.test_briefs
                    .slice()
                    .reverse()
                    .map((brief) => (
                      <option key={brief.id} value={brief.version}>
                        V{brief.version}
                        {brief.status === "confirmed"
                          ? pick(" · Confirmed", " · 已确认")
                          : brief.status === "superseded"
                            ? pick(" · Previous", " · 历史")
                            : pick(" · Draft", " · 草稿")}
                      </option>
                    ))}
                </select>
              </label>
              {!!selectedBrief.content.planning?.test_points?.length && <>
                <button type="button" aria-pressed={briefView === "map"} onClick={() => setBriefView("map")}>{pick("Planning map", "规划脑图")}</button>
                <button type="button" aria-pressed={briefView === "text"} onClick={() => setBriefView("text")}>{pick("Test brief", "测试说明")}</button>
              </>}
              <button type="button" onClick={() => void copyBrief()}>
                <Copy size={16} />
                {pick("Copy", "复制")}
              </button>
              <button type="button" onClick={() => void saveBriefFile()}>
                <Download size={16} />
                {pick("Download .md", "下载 .md")}
              </button>
              {visibleCases.length > 0 && (
                <button type="button" onClick={() => setArtifactOpen(false)}>
                  {pick("Back to test cases", "返回用例")}
                </button>
              )}
              {selectedBrief.version === activeBrief?.version &&
                ["draft", "confirmed"].includes(activeBrief.status) &&
                ["brief_review", "candidate_review", "maintenance"].includes(phase) && (
                  <button
                    type="button"
                    className="is-primary"
                    onClick={() => void confirmBriefAndGenerate()}
                    disabled={busy || blockingQuestions.length > 0}
                  >
                    {busy ? (
                      <LoaderCircle className="auth-spinner" size={16} />
                    ) : (
                      <Check size={16} />
                    )}
                    {busy
                      ? pick("Starting generation…", "正在启动生成…")
                      : activeBrief.status === "confirmed"
                        ? pick("Generate again", "重新生成用例")
                        : pick("Confirm plan and generate", "确认规划并生成用例")}
                  </button>
                )}
            </header>
            {(!selectedBrief.content.planning?.test_points?.length || briefView === "text") && <div className="principle-brief-guidance">
              {pick("This is a read-only Markdown artifact. Use the CasePilot conversation on the left to make changes.", "这是一份只读 Markdown 产物。如需调整，请在左侧与 CasePilot 对话。")}
            </div>}
            {briefView === "map" && !!selectedBrief.content.planning?.test_points?.length && <TestPlanningMap
              key={workspace?.id}
              planning={selectedBrief.content.planning}
              generatedPointIds={candidates.flatMap((candidate) => (candidate.snapshot.test_point_ids ?? []) as string[])}
              title={selectedBrief.content.test_object}
              busy={busy}
              editable={selectedBrief.version === activeBrief?.version && !conversationRunning && blockingQuestions.length === 0}
              onGenerate={(ids) => void confirmBriefAndGenerate(ids)}
              onSavePoint={async (pointId, title, scenario) => {
                if (!workspace || !selectedBrief.content.planning) return;
                setBusy(true);
                setError("");
                try {
                  const content = structuredClone(selectedBrief.content);
                  const point = content.planning!.test_points.find((item) => item.id === pointId)!;
                  point.title = title;
                  point.scenario = scenario;
                  const saved = await saveTestBrief(workspace.id, content, selectedBrief.version);
                  await refreshWorkspace();
                  setSelectedBriefVersion(saved.version);
                  setArtifactOpen(true);
                } catch (caught) {
                  setError(caught instanceof Error ? caught.message : "规划保存失败");
                } finally { setBusy(false); }
              }}
            />}
            {(!selectedBrief.content.planning?.test_points?.length || briefView === "text") && <article className="principle-markdown" aria-label={pick("Structured test brief", "结构化测试说明")}>
              <Streamdown key={selectedBrief.id}>
                {selectedBrief.markdown_content}
              </Streamdown>
            </article>}
            {selectedBrief.version === activeBrief?.version &&
              blockingQuestions.length > 0 && (
                <div className="principle-brief-blocker">
                  <CircleAlert size={17} />
                  {pick("The test target is not clear yet. Add details in the conversation before generating test cases.", "尚未明确测试对象，请先通过对话补充，再生成用例。")}
                </div>
              )}
          </section>
        ) : visibleCases.length || activeChangeSet || viewMode === "plan" || tasks.length ? (
          <section className="principle-case-area">
            <div className="principle-viewbar">
              <div>
                <button
                  type="button"
                  className={viewMode === "map" ? "is-active" : ""}
                  onClick={() => {
                    viewTouchedRef.current = true;
                    setViewMode("map");
                    if (workspace) {
                      void updateWorkspaceState(workspace.id, {
                        active_view: "map",
                      });
                    }
                  }}
                >
                  <GitFork size={17} /> {pick("Mind map", "用例脑图")}
                </button>
                <button
                  type="button"
                  className={viewMode === "list" ? "is-active" : ""}
                  onClick={() => {
                    viewTouchedRef.current = true;
                    setViewMode("list");
                    if (workspace) {
                      void updateWorkspaceState(workspace.id, {
                        active_view: "list",
                      });
                    }
                  }}
                >
                  <List size={17} /> {pick("Test case list", "用例列表")}
                </button>
                <button
                    type="button"
                    className={viewMode === "plan" ? "is-active" : ""}
                    onClick={() => openReviewPlan()}
                  >
                    <Sparkles size={17} /> {pick("Case workspace", "用例工作区")}
                </button>
                {selectedBrief && (
                  <button type="button" disabled={Boolean(editingCaseId || creatingInWorkspace)} onClick={() => setArtifactOpen(true)}>
                    <Sparkles size={17} /> {pick("Structured brief", "结构化测试说明")}
                  </button>
                )}
              </div>
              <span>
                {phase === "candidate_review" ? pick(`${candidates.length} candidates awaiting review · ${cases.length} official cases`, `${candidates.length} 条候选待审阅 · ${cases.length} 条正式用例`) : pick(
                  `${visibleCases.length} test cases · ${new Set([...visibleCases.map((item) => planningModuleAliases(selectedBrief?.content.planning)[item.module] ?? item.module), ...(selectedCollection.mind_map_notes ?? []).filter((note) => note.kind === "module").map((note) => note.module)]).size} modules`,
                  `${visibleCases.length} 条用例 · ${new Set([...visibleCases.map((item) => planningModuleAliases(selectedBrief?.content.planning)[item.module] ?? item.module), ...(selectedCollection.mind_map_notes ?? []).filter((note) => note.kind === "module").map((note) => note.module)]).size} 个模块`,
                )}
              </span>
              {phase === "candidate_review" && viewMode !== "plan" && (
                <button
                  type="button"
                  className="is-primary"
                  onClick={() => void commitCandidates()}
                  disabled={!candidates.some((item) => item.included) || selectedCandidatesNeedReview || busy}
                >
                  <Save size={16} /> {pick("Accept selected", "采纳所选")}
                </button>
              )}
            </div>
            <div hidden={viewMode !== "plan"} style={viewMode !== "plan" ? { display: "none" } : undefined}><CaseTaskWorkspace
              tasks={resultTasks}
              selectedId={selectedTask?.id ?? ""}
              onSelect={setPlanMessageId}
              labels={localizedIntentLabels}
              statusLabels={localizedOperationStatusLabels}
              running={conversationRunning}
              hasLiveResults={hasLiveGenerationPreview || hasLiveRewritePreview}
              onDiscard={(task) => void discardTask(task)}
              activeTaskId={activeMutationTask?.id}
              onConversation={(id) => {
                if (id) document.getElementById(`case-message-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
                else promptRef.current?.focus();
              }}
              onArtifact={(task) => {
                if (task.message.metadata.action === "module_created") { setViewMode("map"); return; }
                const version = Number(task.message.metadata.brief_version ?? 0);
                if (version) selectBriefVersion(version);
                else if (task.message.metadata.change_set_id && selectedTaskChangeSet) document.getElementById("collection-changes")?.scrollIntoView({ behavior: "smooth" });
                else setViewMode("list");
              }}
            >
            {taskVersions.length > 1 && <div className="case-task-revisions" aria-label={pick("Revision history", "修改版本历史")}>
              <label>{pick("Revision", "修改版本")} <select aria-label={pick("Review revision", "查看修改版本")} value={resultVersion?.operation?.id ?? ""} onChange={event => setReviewVersion({ taskId: selectedTask!.id, latestId: selectedTask!.operation!.id, operationId: event.target.value })}>
                {taskVersions.map((version, index) => <option key={version.id} value={version.operation?.id}>V{index + 1}{index === taskVersions.length - 1 ? pick(" · Latest", " · 最新") : ""} · {String(version.operation?.payload.instruction ?? version.request?.content ?? "")}</option>)}
              </select></label>
              {historicalVersion && <button type="button" onClick={() => setReviewVersion({ taskId: "", latestId: "", operationId: "" })}>{pick("Back to latest revision", "返回最新版本")}</button>}
              <p role="status">{generatingRevision ? pick("Updating this task. The previous proposal remains available while the new revision is prepared.", "正在更新本任务，生成期间可继续查看上一版方案。") : historicalVersion ? pick("Viewing a historical revision. Return to the latest revision to continue editing or accept changes.", "当前为历史版本，返回最新版本后可继续修改或采纳。") : selectedTask?.id === activeMutationTask?.id ? pick("All revisions belong to this task. Continue editing until you are satisfied, then accept the changes.", "这些版本属于同一任务，可继续修改，满意后再采纳。") : pick("This task has ended. Further changes start a new task; these revisions remain available for review.", "当前任务已结束，再次修改会新建任务；历史版本仍可在此审阅。")}</p>
            </div>}
            {selectedScopeChanged && <p className="task-version-notice">{pick("This result is based on earlier case versions. Review again before preparing changes.", "此结果基于历史用例版本，请重新检查后再生成变更。")}</p>}
            {selectedChangeSetId && !selectedTaskChangeSet && <p role="status">{resultLoadError || pick("Loading task result…", "正在加载任务结果…")}</p>}
            {selectedTask && workspace && !historicalVersion && <CaseTaskArtifacts
              generationProgress={selectedTask.operation?.related_job_id === currentJobId ? progress : null}
              task={selectedTask} conversation={workspace} cases={cases} busy={conversationRunning} pendingCandidateRefs={pendingCandidateRefs}
              onLocate={(id) => { setSelectedCaseId(id); setCandidateDraft(candidates.find((item) => item.id === id) ?? null); setViewMode("list"); setInspectorHidden(false); }}
              onToggleCandidate={(candidate) => void toggleCandidate(candidate, !candidate.included)}
              onRefine={() => {
                const candidate = candidates.find(item => item.included) ?? candidates[0];
                if (!candidate) return;
                setSelectedCaseId(candidate.id);
                setCandidateDraft(structuredClone(candidate));
                setCandidateSaveMessage("");
                setViewMode("list");
                setInspectorHidden(false);
              }}
              onCommit={() => void commitCandidates()} onBrief={selectBriefVersion} onGenerate={() => void confirmBriefAndGenerate()}
            />}
            {(editingCaseId || creatingInWorkspace) && (
              <div hidden={viewMode !== "plan"}>
              <CaseEditorDialog
                key={editingCaseId || "workspace-new-case"}
                inline
                testCase={cases.find((item) => item.id === editingCaseId) ?? null}
                saving={savingInWorkspace}
                onClose={() => { setEditingCaseId(""); setCreatingInWorkspace(false); }}
                onSave={async (input) => {
                  setSavingInWorkspace(true);
                  try {
                    const current = cases.find((item) => item.id === editingCaseId);
                    if (current) await onSaveCase(current, input);
                    else await onCreateCaseInline(input);
                    setEditingCaseId("");
                    setCreatingInWorkspace(false);
                  } finally {
                    setSavingInWorkspace(false);
                  }
                }}
              />
              </div>
            )}
        {selectedTaskChangeSet && (
          <div id="collection-changes">
            <CaseCollectionChanges
              key={selectedTaskChangeSet.id}
              onCandidates={() => {
                const refs = new Set(selectedTaskChangeSet.items.map((item) => item.ref));
                const source = tasks.find((task) => candidatesForTask(task, workspace).some((item) => refs.has(item.ref)));
                if (source) openReviewPlan(source.id);
              }}
              onRefine={!historicalVersion && selectedTask?.operation ? () => {
                setRefineSourceId(selectedTask.operation!.id);
                promptRef.current?.focus();
              } : undefined}
              cases={cases}
              changeSet={selectedTaskChangeSet}
              acceptedFields={acceptedFields}
              onSelectFields={(selection) => {
                const next = { ...acceptedFields, ...selection };
                reviewSelections.current[selectedTaskChangeSet.id] = next;
                setAcceptedFields(next);
              }}
              busy={conversationRunning}
              onToggleField={(ref, field) => {
                const next = {
                  ...acceptedFields,
                  [ref]: acceptedFields[ref]?.includes(field)
                    ? acceptedFields[ref].filter((item) => item !== field)
                    : [...(acceptedFields[ref] ?? []), field],
                };
                reviewSelections.current[selectedTaskChangeSet.id] = next;
                setAcceptedFields(next);
              }}
              onApply={applyChangeSet}
              onAcceptAll={() => applyChangeSet(Object.fromEntries(selectedTaskChangeSet.items
                .filter((item) => !["applied", "rejected"].includes(item.status ?? ""))
                .map((item) => [item.ref, item.field_diff.map((diff) => diff.field)])))}
              onReviewItem={(ref, accept) => {
                const item = selectedTaskChangeSet.items.find((item) => item.ref === ref);
                return applyChangeSet({ [ref]: accept ? item?.field_diff.map((diff) => diff.field) ?? [] : [] }, [ref]);
              }}
              onReject={rejectChangeSet}
            />
          </div>
        )}
            {activePlanReport && !["running", "queued"].includes(selectedTask?.status ?? "") && (
              <CaseReviewPlan
                hidden={viewMode !== "plan"}
                changedSinceReview={changedSinceReview}
                key={activePlanMessage?.id}
                report={activePlanReport}
                intent={selectedTask?.message.intent ?? undefined}
                decisions={selectedTask?.operation?.result.review_decisions as TaskReviewDecisions | undefined}
                onSaveDecisions={selectedTask?.operation ? (decisions) => {
                  persistReviewDecisions(selectedTask.operation!.id, decisions);
                } : undefined}
                onFollowup={(action, findings, keepIds) => void runFollowup(action, findings, keepIds)}
                checkedCount={Number(activePlanMessage?.metadata.checked_case_count ?? activePlanMessage?.metadata.target_count ?? 0)}
                cases={cases}
                candidates={candidates}
                candidateCases={candidateCases}
                onEdit={openCaseEditor}
                onPrepareDelete={prepareReviewDeletion}
                changeSet={activeChangeSet}
                busy={conversationRunning}
                onLocate={(caseId) => {
                  setSelectedCaseId(caseId);
                  setMapFocusVersion((version) => version + 1);
                  setViewMode("map");
                  onSelectCase(caseId);
                  if (workspace) void updateWorkspaceState(workspace.id, { selected_case_id: caseId });
                }}
              />
            )}
            </CaseTaskWorkspace></div>
            {mapVisited && <Activity mode={viewMode === "map" ? "visible" : "hidden"}>
              <CaseMindMap
                key={`${selectedCollection.id}:${phase === "candidate_review" ? "candidates" : "official"}`}
                collection={selectedCollection}
                cases={visibleCases}
                moduleAliases={planningModuleAliases(selectedBrief?.content.planning)}
                selectedCaseId={selectedCaseId}
                focusVersion={mapFocusVersion}
                onSaveCase={phase === "maintenance" ? onSaveCase : undefined}
                onSelectCase={(caseId) => {
                  setSelectedCaseId(caseId);
                  if (workspace) void updateWorkspaceState(workspace.id, { selected_case_id: caseId });
                  const candidate = candidates.find((item) => item.id === caseId);
                  setCandidateDraft(
                    candidate ? structuredClone(candidate) : null,
                  );
                  onSelectCase(caseId);
                }}
                onCreateCase={() => undefined}
                onCreateCaseInline={phase === "maintenance" ? onCreateCaseInline : undefined}
                onEditCase={(testCase) => {
                  if (phase === "maintenance") openCaseEditor(testCase);
                  else setSelectedCaseId(testCase.id);
                }}
                onSelectTarget={(target, label) => {
                  if (target.kind === "case" && target.case_ids?.length === 1) {
                    const testCase = visibleCases.find((item) => item.id === target.case_ids?.[0]);
                    if (testCase) {
                      selectTarget(caseTarget(testCase), label);
                      return;
                    }
                  }
                  selectTarget(target, label);
                }}
                rewriteTargets={selectedRewriteTargets}
                rewriteStatus={rewriteStatus}
              />
            </Activity>}
            {viewMode === "list" && (
              <div className="principle-case-list">
                {visibleCases.map((testCase) => {
                  const candidate = candidates.find(
                    (item) => item.id === testCase.id,
                  );
                  return (
                    <div
                      key={testCase.id}
                      data-case-id={testCase.id}
                      className={[
                        "principle-case-row",
                        selectedCaseId === testCase.id ? "is-active" : "",
                        activeRewriteTargets.some(
                          (item) =>
                            (item.target.kind === "case" && (
                              item.target.case_ids?.includes(testCase.id) ||
                              (candidate && item.target.candidate_refs?.includes(candidate.ref))
                            )) || (item.target.kind === "module" && (
                              testCase.module === item.target.module ||
                              testCase.module.startsWith(`${item.target.module}/`)
                            )),
                        )
                          ? `is-ai-target is-ai-${rewriteStatus}`
                          : "",
                      ].filter(Boolean).join(" ")}
                    >
                      <button
                        type="button"
                        aria-pressed={selectedCaseId === testCase.id}
                        onClick={() => {
                          setSelectedCaseId(testCase.id);
                          setCandidateDraft(
                            candidate ? structuredClone(candidate) : null,
                          );
                          onSelectCase(testCase.id);
                          if (workspace) {
                            void updateWorkspaceState(workspace.id, {
                              selected_case_id: testCase.id,
                            });
                          }
                          selectTarget(caseTarget(testCase), testCase.title);
                        }}
                      >
                        <span className="principle-case-row__main">
                          <span className="principle-case-row__key">{testCase.case_key}</span>
                          <strong>{testCase.title}</strong>
                        </span>
                        <small>{testCase.module || pick("Uncategorized", "未分类")}</small>
                        <i
                          className={`priority-badge priority-badge--${testCase.priority.toLowerCase()}`}
                        >
                          {testCase.priority}
                        </i>
                      </button>
                      {candidate && (
                        <label>
                          <input
                            type="checkbox"
                            checked={candidate.included}
                            onChange={(event) =>
                              void toggleCandidate(
                                candidate,
                                event.target.checked,
                              )
                            }
                          />
                          {pick("Include", "纳入")}
                        </label>
                      )}
                      {!candidate && phase === "maintenance" && (
                        <label>
                          <input
                            type="checkbox"
                            checked={selectedTargets.some(
                              (item) =>
                                item.target.kind === "case" &&
                                item.target.case_ids?.includes(testCase.id),
                            )}
                            onChange={() =>
                              toggleTarget(
                                { kind: "case", case_ids: [testCase.id] },
                                testCase.title,
                              )
                            }
                          />
                          {pick("Select", "选择")}
                        </label>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        ) : (
          <div className="principle-blank-state">
            {loading || !workspace ? (
              <>
                <LoaderCircle className="auth-spinner" size={24} />
                <strong>{pick("Restoring workspace", "正在恢复工作区")}</strong>
              </>
            ) : (
              <>
                <FileUp size={30} />
                <strong>{pick("The mind map and test case list are empty", "脑图和用例列表保持空白")}</strong>
                <p>
                  {pick("Enter your generation request, then review and confirm the structured test brief. Existing cases remain hidden until candidate generation is complete.", "输入生成需求后，先审阅并确认结构化测试说明；候选生成完成前不会展示旧用例。")}
                </p>
              </>
            )}
          </div>
        )}
      </main>

      {!inspectorCollapsed && (
        <div
          className="principle-resizer principle-resizer--inspector"
          role="separator"
          aria-label={pick("Resize details panel", "调整详情区域宽度")}
          aria-orientation="vertical"
          aria-valuemin={280}
          aria-valuemax={520}
          aria-valuenow={inspectorWidth}
          tabIndex={0}
          onPointerDown={(event) => startPanelResize("inspector", event)}
          onDoubleClick={() => resetPanelWidth("inspector")}
          onKeyDown={(event) => {
            if (event.key.startsWith("Arrow")) event.preventDefault();
            resizeWithKeyboard("inspector", event.key);
          }}
        >
          <i />
        </div>
      )}

      {!inspectorCollapsed && (
        <aside className="principle-inspector">
          {selectedCase ? (
            <>
              <header>
                <span>{pick("CASE DETAILS", "用例详情")}</span>
                <button type="button" className="case-details-close" aria-label={pick("Close case details", "关闭用例详情")} title={pick("Close case details", "关闭用例详情")} onClick={() => setInspectorHidden(true)}><X size={16} /></button>
                {phase === "maintenance" && (
                  <button type="button" onClick={() => openCaseEditor(selectedCase)}>
                    <Pencil size={15} /> {pick("Edit", "编辑")}
                  </button>
                )}
              </header>
              {candidateDraft ? (
                <fieldset className="principle-candidate-editor" disabled={candidateSaving}>
                  <label>
                    {pick("Title", "标题")}
                    <input
                      value={candidateDraft.snapshot.title}
                      onChange={(event) =>
                        setCandidateDraft((current) =>
                          current
                            ? {
                                ...current,
                                snapshot: {
                                  ...current.snapshot,
                                  title: event.target.value,
                                },
                              }
                            : current,
                        )
                      }
                    />
                  </label>
                  <label>
                    {pick("Module", "模块")}
                    <input
                      value={candidateDraft.snapshot.module}
                      onChange={(event) =>
                        setCandidateDraft((current) =>
                          current
                            ? {
                                ...current,
                                snapshot: {
                                  ...current.snapshot,
                                  module: event.target.value,
                                },
                              }
                            : current,
                        )
                      }
                    />
                  </label>
                  <label>
                    {pick("Priority", "优先级")}
                    <select
                      value={candidateDraft.snapshot.priority}
                      onChange={(event) =>
                        setCandidateDraft((current) =>
                          current
                            ? {
                                ...current,
                                snapshot: {
                                  ...current.snapshot,
                                  priority: event.target.value as
                                    | "P0"
                                    | "P1"
                                    | "P2",
                                },
                              }
                            : current,
                        )
                      }
                    >
                      <option value="P0">P0</option>
                      <option value="P1">P1</option>
                      <option value="P2">P2</option>
                    </select>
                  </label>
                  <label>
                    {pick("Preconditions (one per line)", "前置条件（每行一条）")}
                    <textarea rows={4} value={candidateDraft.snapshot.preconditions.join("\n")} onChange={event => {
                      const value = event.target.value;
                      setCandidateDraft(current => current ? { ...current, snapshot: { ...current.snapshot, preconditions: value.split("\n") } } : current);
                      setCandidateSaveMessage("");
                    }} />
                  </label>
                  <CaseContentFields key={`${candidateDraft.id}-${candidateDraft.version}`} steps={candidateDraft.snapshot.steps} onChange={steps => {
                    setCandidateDraft(current => current ? { ...current, snapshot: { ...current.snapshot, steps } } : current);
                    setCandidateSaveMessage("");
                  }} />
                  <button type="button" disabled={candidateSaving || busy || !candidateDraft.snapshot.title.trim() || !candidateDraft.snapshot.steps.length || (!candidateDraft.snapshot.steps.some(step => step.action.trim()) || !candidateDraft.snapshot.steps.some(step => step.expected.trim()))} onClick={() => void saveCandidate()}>
                    <Save size={16} /> {candidateSaving ? pick("Saving…", "正在保存…") : pick("Save candidate changes", "保存候选修改")}
                  </button>
                  {candidateSaveMessage && <p role="status">{candidateSaveMessage}</p>}
                </fieldset>
              ) : (
                <>
                  <h2>{selectedCase.title}</h2>
                  <div className="principle-tags">
                    <span>{selectedCase.module || pick("Uncategorized", "未分类")}</span>
                    <span>{selectedCase.case_type}</span>
                    <span className={`priority-badge priority-badge--${selectedCase.priority.toLowerCase()}`}>{selectedCase.priority}</span>
                  </div>
                </>
              )}
              {!candidateDraft && <>
              <section>
                <strong>{pick("Preconditions", "前置条件")}</strong>
                <ul>
                  {selectedCase.preconditions.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </section>
              <section>
                <strong>{pick("Test steps", "测试步骤")}</strong>
                <ol>
                  {selectedCase.steps.filter(step => step.action.trim()).map((step) => (
                    <li key={step.id}>
                      <p>{step.action}</p>
                    </li>
                  ))}
                </ol>
              </section>
              <section>
                <strong>{pick("Case checkpoints", "用例校验点")}</strong>
                <ol>
                  {selectedCase.steps.filter(step => step.expected.trim()).map((step) => (
                    <li key={step.id}>
                      <p>{step.expected}</p>
                    </li>
                  ))}
                </ol>
              </section>
              </>}
            </>
          ) : (
            <div className="principle-inspector-empty">
              <Sparkles size={24} />
              <strong>{pick("CasePilot workspace", "CasePilot 工作区")}</strong>
              <p>{pick("Confirm the test brief and finish candidate generation to review detailed steps here.", "确认测试说明并完成候选生成后，可在这里审阅详细步骤。")}</p>
            </div>
          )}
        </aside>
      )}
    </section>
  );
}
