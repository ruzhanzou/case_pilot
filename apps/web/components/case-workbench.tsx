"use client";

import { CaseMindMap } from "@/components/case-mind-map";
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
  downloadTestBrief,
  getCaseChangeSet,
  getConversation,
  getOrCreateWorkspace,
  listGenerationModels,
  rejectCaseChangeSet,
  resumeConversationOperation,
  sendConversationMessage,
  updateWorkspaceCandidate,
  updateWorkspaceState,
  uploadKnowledgeFiles,
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
  Paperclip,
  Pencil,
  Save,
  Send,
  Sparkles,
  Square,
  X,
} from "lucide-react";
import {
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
  KNOWLEDGE_QA: "知识问答",
  SMALL_TALK: "CasePilot",
  UNRESOLVED: "补充说明",
};

const intentActionLabels: Record<ConversationIntent, string> = {
  ...intentLabels,
  SMALL_TALK: "日常对话",
};

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
  "enhancement.completed": "Adding boundary and negative scenarios",
  "quality.completed": "Running quality checks",
  "knowledge.answered": "Answering with workspace knowledge",
  completed: "Completed", failed: "Failed", cancelled: "Stopped",
};
const englishOperationStatusLabels: Record<string, string> = {
  queued: "Queued", running: "Running", awaiting_confirmation: "Awaiting confirmation",
  awaiting_intent: "Choose an action", completed: "Completed", skipped: "Skipped",
  failed: "Failed", cancelled: "Cancelled",
};

function formatChangeValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    return value.map((item, index) =>
      typeof item === "string"
        ? `${index + 1}. ${item}`
        : typeof item === "object" && item !== null && "action" in item
          ? `${index + 1}. ${String(item.action)}\n   → ${String("expected" in item ? item.expected : "")}`
          : `${index + 1}. ${JSON.stringify(item)}`,
    ).join("\n");
  }
  return JSON.stringify(value, null, 2);
}

const terminalWorkflowStatuses = new Set(["completed", "failed", "cancelled"]);
const terminalOperationStatuses = new Set(["completed", "skipped"]);

function nextRunnableOperation(conversation: ConversationDto | null) {
  const operations = conversation?.operation_plan?.operations ?? [];
  return operations.find(
    (operation) =>
      operation.status === "queued" &&
      operations
        .filter((item) => item.sequence < operation.sequence)
        .every((item) => terminalOperationStatuses.has(item.status)),
  );
}

function clampPanelWidth(
  panel: "chat" | "inspector",
  value: number,
): number {
  const [minimum, maximum] = panel === "chat" ? [380, 640] : [280, 480];
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
  onEditCase,
  onSaveCase,
  onCasesChanged,
  onOpenLibrary,
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
  const [modelId, setModelId] = useState<AgentModelId>("auto");
  const [models, setModels] = useState<{ id: string; label: string }[]>([]);
  const [viewMode, setViewMode] = useState<"list" | "map">("list");
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [selectedTargets, setSelectedTargets] = useState<
    { key: string; label: string; target: ConversationTarget }[]
  >([]);
  const [rewriteTargets, setRewriteTargets] = useState<
    { key: string; label: string; target: ConversationTarget }[]
  >([]);
  const [busy, setBusy] = useState(false);
  const [currentJobId, setCurrentJobId] = useState("");
  const [progress, setProgress] = useState<GenerationStage | null>(null);
  const [liveStages, setLiveStages] = useState<GenerationStage[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedBriefVersion, setSelectedBriefVersion] = useState(0);
  const [artifactOpen, setArtifactOpen] = useState(false);
  const [chatWidth, setChatWidth] = useState(400);
  const [inspectorWidth, setInspectorWidth] = useState(300);
  const [activeChangeSet, setActiveChangeSet] =
    useState<CaseChangeSetDto | null>(null);
  const [acceptedFields, setAcceptedFields] = useState<
    Record<string, string[]>
  >({});
  const [candidateDraft, setCandidateDraft] =
    useState<WorkspaceCandidateDto | null>(null);
  const [uploading, setUploading] = useState(false);
  const [attachmentLabels, setAttachmentLabels] = useState<string[]>([]);
  const [sourceIds, setSourceIds] = useState<string[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);
  const promptSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const streamScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const watchedJobRef = useRef("");
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
  const effectivePendingOperationId = pendingOperationId ??
    workspace?.operation_plan?.operations.find((item) => item.status === "awaiting_target")?.id;
  const activeRewriteTargets = rewriteTargets.length
    ? rewriteTargets
    : selectedTargets;
  const rewriteStatus: "idle" | "selected" | "running" | "review" | "applied" =
    !activeRewriteTargets.length
      ? "idle"
      : activeChangeSet
        ? "review"
        : busy
          ? "running"
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
        message.content.trim() || workflowByMessageId.has(message.id),
    ) ?? [];
  const operationPlan = workspace?.operation_plan ?? null;
  const showOperationPlan = Boolean(
    operationPlan &&
      operationPlan.operations.length > 1 &&
      new Set(operationPlan.operations.map((item) => item.intent)).size > 1,
  );
  const latestMessage = messages.at(-1);
  const inspectorCollapsed =
    artifactOpen ||
    !visibleCases.length;

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

  const targetsFromInstruction = useCallback((instruction: string): ConversationTarget[] => {
    const matches = visibleCases.filter((item) =>
      (item.case_key.length >= 4 && instruction.includes(item.case_key)) ||
      (item.title.length >= 4 && instruction.includes(item.title)),
    );
    if (matches.length) return matches.map(caseTarget);
    const moduleMatches = [...new Set(visibleCases.map((item) => item.module).filter(Boolean))]
      .filter((module) => instruction.includes(`模块「${module}」`) || instruction.includes(`模块“${module}”`));
    return moduleMatches.length === 1 ? [{ kind: "module", module: moduleMatches[0] }] : [];
  }, [caseTarget, visibleCases]);

  const selectedCollectionId = selectedCollection?.id ?? "";
  const applyWorkspaceResult = useCallback((result: ConversationDto) => {
    setWorkspace(result);
    setPrompt(String(result.context.draft_text ?? ""));
    const restoredModelId = String(result.context.model_id ?? "");
    if (restoredModelId) setModelId(restoredModelId);
    setViewMode(result.context.active_view === "map" ? "map" : "list");
    const restoredBriefVersion = Number(
      result.context.selected_brief_version ??
        result.test_briefs.at(-1)?.version ??
        0,
    );
    setSelectedBriefVersion(restoredBriefVersion);
    const workspacePhase = `${result.id}:${String(result.context.phase ?? "idle")}`;
    if (workspacePhase !== lastWorkspacePhaseRef.current) {
      lastWorkspacePhaseRef.current = workspacePhase;
      setArtifactOpen(
        ["brief_review", "brief_drafting", "generating"].includes(
          String(result.context.phase ?? "idle"),
        ),
      );
    }
    setChatWidth(
      clampPanelWidth("chat", Number(result.context.chat_width ?? 400)),
    );
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
    setCurrentJobId(activeJobId);
    setBusy(
      Boolean(activeJobId) &&
        ["brief_drafting", "generating"].includes(
          String(result.context.phase ?? ""),
        ),
    );
    const restoredCandidate =
      result.candidates.find((item) => item.id === restoredCaseId) ??
      result.candidates[0] ??
      null;
    setCandidateDraft(
      restoredCandidate ? structuredClone(restoredCandidate) : null,
    );
  }, []);
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
        setAcceptedFields(Object.fromEntries(changeSet.items.map((item) => [
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
      setBusy(true);
      setCurrentJobId(jobId);
      setProgress({ name: "queued", progress: 0 });
      try {
        const job = await watchGeneration(
          jobId,
          (stage) => {
            setProgress(stage);
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
        if (job.status === "failed") {
          throw new Error(job.error_code ?? pick("Task failed. Try again later.", "任务处理失败，请稍后重试"));
        }
        await refreshWorkspace();
      } catch (caught) {
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
    [pick, refreshWorkspace, workspace?.id],
  );

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
      !["brief_drafting", "generating"].includes(phase)
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
    if (!latestMessage) return;
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
  }, [currentJobId, latestMessage, scrollToBottom]);

  useEffect(
    () => () => {
      if (streamScrollTimerRef.current) {
        clearTimeout(streamScrollTimerRef.current);
      }
    },
    [],
  );

  useEffect(() => {
    if (!workspace || prompt === String(workspace.context.draft_text ?? "")) {
      return;
    }
    if (promptSaveTimer.current) clearTimeout(promptSaveTimer.current);
    promptSaveTimer.current = setTimeout(() => {
      void updateWorkspaceState(workspace.id, { draft_text: prompt }).then(
        setWorkspace,
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
    if (!files.length || !spaceId) return;
    setUploading(true);
    setError("");
    try {
      const result = await uploadKnowledgeFiles(
        spaceId,
        pick(`Workspace attachment ${new Date().toLocaleString("en-US")}`, `工作区附件 ${new Date().toLocaleString("zh-CN")}`),
        files,
        "temporary",
      );
      setSourceIds((current) => [...new Set([...current, result.source.id])]);
      setAttachmentLabels((current) => [
        ...current,
        ...files.map((file) => file.name),
      ]);
      setNotice(pick("Attachment saved to the current workspace", "附件已自动保存到当前工作区"));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : pick("Failed to save attachment", "附件保存失败"));
    } finally {
      setUploading(false);
    }
  };

  const submitMessage = async (event: FormEvent) => {
    event.preventDefault();
    if (
      !workspace ||
      busy ||
      (!effectivePendingOperationId && !prompt.trim()) ||
      (effectivePendingOperationId && !selectedTargets.length)
    ) return;
    const content = prompt.trim();
    let structuredTargets = selectedTargets.length
      ? selectedTargets.map((item) => item.target)
      : targetsFromInstruction(content);
    let inferredCurrentCase = false;
    if (
      !structuredTargets.length &&
      selectedCase &&
      /(?:当前用例(?!集)|这条用例|选中(?:的)?用例|current\s+(?:test\s+)?case|selected\s+(?:test\s+)?case)/i.test(content)
    ) {
      structuredTargets = [caseTarget(selectedCase)];
      inferredCurrentCase = true;
    }
    const contextOnlyTarget = inferredCurrentCase &&
      !/(?:修改|改写|调整|补充|新增|替换|删除|改成|改为|\b(?:modify|edit|update|rewrite|revise|delete|remove)\b)/i.test(content);
    const resolvedSelections = contextOnlyTarget
      ? selectedTargets
      : selectedTargets.length
      ? selectedTargets
      : structuredTargets.map((target) => {
          const testCase = visibleCases.find((item) =>
            target.kind === "case" && (
              target.case_ids?.includes(item.id) ||
              candidates.some((candidate) => candidate.id === item.id && target.candidate_refs?.includes(candidate.ref))
            ),
          );
          const label = testCase?.title ?? target.module ?? pick("Selected cases", "已匹配用例");
          return { key: JSON.stringify(target), label, target };
        });
    if (!contextOnlyTarget) {
      setSelectedTargets(resolvedSelections);
      setRewriteTargets(resolvedSelections);
    }
    setBusy(true);
    setPrompt("");
    setError("");
    setNotice("");
    try {
      const turn = effectivePendingOperationId
        ? await resumeConversationOperation(effectivePendingOperationId, {
            targets: structuredTargets,
          })
        : await sendConversationMessage(workspace.id, {
            content,
            modelId,
            scope: "current",
            knowledgeSourceIds: sourceIds,
            useSpaceKnowledge: true,
            targets: structuredTargets,
          });
      setWorkspace(
        await updateWorkspaceState(workspace.id, {
          draft_text: "",
          selected_targets: resolvedSelections.map((item) => ({
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
      if (effectivePendingOperationId) setSelectedTargets([]);
      if (jobId && !turn.action.change_set_id) {
        const refreshed = await refreshWorkspace();
        const next = nextRunnableOperation(refreshed);
        if (next) {
          const resumed = await resumeConversationOperation(next.id);
          if (resumed.action.job_id) await waitAndRefresh(resumed.action.job_id);
          else await refreshWorkspace();
        }
      }
    } catch (caught) {
      setPrompt(content);
      setError(caught instanceof Error ? caught.message : pick("Failed to process message", "消息处理失败"));
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
    setError("");
    try {
      await cancelGeneration(currentJobId);
      await refreshWorkspace();
      setNotice(pick("Generation stopped. The structured test brief is still available.", "生成已停止，结构化测试说明仍保留"));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : pick("Failed to stop generation", "停止生成失败"));
    } finally {
      setBusy(false);
      setCurrentJobId("");
      setProgress(null);
    }
  };

  const confirmBriefAndGenerate = async () => {
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
      );
      await refreshWorkspace();
      if (turn.action.job_id) {
        await waitAndRefresh(turn.action.job_id);
      } else {
        setBusy(false);
        setProgress(null);
      }
      let refreshed = await refreshWorkspace();
      for (let index = 0; index < 2; index += 1) {
        const next = nextRunnableOperation(refreshed);
        if (!next) break;
        const resumed = await resumeConversationOperation(next.id);
        if (resumed.action.job_id) {
          await waitAndRefresh(resumed.action.job_id);
        }
        if (resumed.action.change_set_id) {
          const changeSet = await getCaseChangeSet(resumed.action.change_set_id);
          setActiveChangeSet(changeSet);
          setAcceptedFields(
            Object.fromEntries(
              changeSet.items.map((item) => [
                item.ref,
                item.field_diff.map((diff) => diff.field),
              ]),
            ),
          );
          break;
        }
        refreshed = await refreshWorkspace();
      }
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
    try {
      await updateWorkspaceCandidate(candidate.id, {
        baseVersion: candidate.version,
        included,
      });
      await refreshWorkspace();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : pick("Failed to save candidate status", "候选状态保存失败"));
    }
  };

  const saveCandidate = async () => {
    if (!candidateDraft) return;
    try {
      await updateWorkspaceCandidate(candidateDraft.id, {
        baseVersion: candidateDraft.version,
        snapshot: candidateDraft.snapshot as unknown as Record<string, unknown>,
      });
      await refreshWorkspace();
      setNotice(pick("Candidate changes saved automatically", "候选修改已自动保存"));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : pick("Failed to save candidate", "候选保存失败"));
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
      let refreshed = await refreshWorkspace();
      const next = nextRunnableOperation(refreshed);
      if (next) {
        const resumed = await resumeConversationOperation(next.id);
        if (resumed.action.job_id) await waitAndRefresh(resumed.action.job_id);
        else refreshed = await refreshWorkspace();
      } else {
        onOpenLibrary();
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : pick("Failed to add candidates", "候选纳入失败"));
    } finally {
      setBusy(false);
    }
  };

  const applyChangeSet = async () => {
    if (!activeChangeSet) return;
    setBusy(true);
    try {
      await applyCaseChangeSet(activeChangeSet.id, acceptedFields);
      setActiveChangeSet(null);
      await onCasesChanged();
      const refreshed = await refreshWorkspace();
      const next = nextRunnableOperation(refreshed);
      if (next) {
        const resumed = await resumeConversationOperation(next.id);
        if (resumed.action.job_id) await waitAndRefresh(resumed.action.job_id);
        else await refreshWorkspace();
      }
      setNotice(changeAppliedNotice);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : pick("Failed to apply changes", "变更应用失败"));
    } finally {
      setBusy(false);
    }
  };

  const rejectChangeSet = async () => {
    if (!activeChangeSet) return;
    setBusy(true);
    setError("");
    try {
      await rejectCaseChangeSet(activeChangeSet.id);
      setActiveChangeSet(null);
      await refreshWorkspace();
      setNotice(pick("Changes rejected. Official test cases were not modified.", "已拒绝变更，正式用例未修改"));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : pick("Failed to reject changes", "拒绝变更失败"));
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
    let previewOffset = 0;
    let frameId: number | null = null;
    const renderPreview = () => {
      frameId = null;
      separator.style.transform = `translateX(${previewOffset}px)`;
    };
    const move = (pointerEvent: PointerEvent) => {
      const delta =
        panel === "chat"
          ? pointerEvent.clientX - startX
          : startX - pointerEvent.clientX;
      const next = clampPanelWidth(panel, startWidth + delta);
      latestWidth = next;
      previewOffset = pointerEvent.clientX - startX;
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
        <div className="principle-context-card">
          <span>{pick("Current workspace", "当前工作区")}</span>
          <strong>{selectedCollection.name}</strong>
          <small>{pick(`${spaceName} · Autosaved · This conversation only maintains this collection`, `${spaceName} · 自动保存 · 本对话仅维护此集合`)}</small>
        </div>

        <div
          className="principle-messages"
          aria-live="polite"
          ref={messagesScrollRef}
        >
          <div className="principle-messages-content" ref={messagesContentRef}>
            {!messages.length && (
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
            {messages.map((message) => {
            const workflow = workflowByMessageId.get(message.id);
            const isLiveWorkflow =
              workflow?.job_id === currentJobId ||
              message.related_job_id === currentJobId;
            const persistedStages = workflow?.stages ?? [];
            const renderedStages =
              isLiveWorkflow && liveStages.length
                ? liveStages
                    .filter((stage) => stage.name !== progress?.name)
                    .map((stage) => ({
                      stage: stage.name,
                      progress: stage.progress,
                      status: "completed",
                    }))
                : persistedStages;
            const artifactVersion = Number(message.metadata.brief_version ?? 0);
            return (
              <article
                key={message.id}
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
                {message.content && (
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
                        message.intent,
                        ...(
                          [
                            "CASE_GENERATE",
                            "CASE_MODIFY",
                            "KNOWLEDGE_QA",
                            "SMALL_TALK",
                          ] as ConversationIntent[]
                        ).filter((intent) => intent !== message.intent),
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
                  (workflow || isLiveWorkflow) && (
                  <div
                    className="principle-workflow"
                    data-status={workflow?.status ?? "running"}
                  >
                    <strong>{pick("CasePilot workflow", "CasePilot 工作流")}</strong>
                    {renderedStages.map((stage, index) => (
                      <div
                        key={`${stage.stage}-${index}`}
                        className={`principle-workflow-stage is-${stage.status}`}
                      >
                        <Check size={13} />
                        <span>
                          {localizedWorkflowStageLabels[stage.stage] ?? pick("Processing task", "处理任务")}
                        </span>
                        <small>{stage.progress}%</small>
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
                  </div>
                  )}
                {artifactVersion > 0 && (
                  <button
                    type="button"
                    className="principle-artifact-link"
                    onClick={() => selectBriefVersion(artifactVersion)}
                  >
                    <FileUp size={14} />
                    {pick("Structured test brief", "结构化测试说明")} V{artifactVersion}.md
                  </button>
                )}
                {message.citations.length > 0 && (
                  <small>
                    {pick("Sources: ", "来源：")}
                    {message.citations.map((item) => item.label).join("、")}
                  </small>
                )}
              </article>
            );
            })}
          </div>
        </div>

        {activeChangeSet && (
          <div className="principle-change-set">
            <strong>{pick("Review changes", "变更审阅")}</strong>
            {activeChangeSet.items.map((item) => (
              <div key={item.ref}>
                <span>
                  {String(item.base_snapshot.title ?? item.ref)}
                </span>
                {item.field_diff.map((diff) => {
                  const checked = acceptedFields[item.ref]?.includes(diff.field);
                  return (
                    <div className="principle-change-set__field" key={diff.field}>
                      <label>
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() =>
                            setAcceptedFields((current) => ({
                              ...current,
                              [item.ref]: checked
                                ? (current[item.ref] ?? []).filter((field) => field !== diff.field)
                                : [...(current[item.ref] ?? []), diff.field],
                            }))
                          }
                        />
                        {diff.field === "delete" ? pick("Confirm soft delete", "确认软删除") : diff.field}
                      </label>
                      <div className="principle-change-set__comparison">
                        <div><small>{pick("Before", "原内容")}</small><pre>{formatChangeValue(diff.before)}</pre></div>
                        <div><small>{pick("After", "改写后")}</small><pre>{formatChangeValue(diff.after)}</pre></div>
                      </div>
                    </div>
                  );
                })}
              </div>
            ))}
            <div>
              <button type="button" onClick={() => void rejectChangeSet()} disabled={busy}>
                {pick("Reject changes", "拒绝变更")}
              </button>
              <button type="button" onClick={() => void applyChangeSet()} disabled={busy}>
                {pick("Apply changes", "确认应用")}
              </button>
            </div>
          </div>
        )}

        <form className="principle-composer" onSubmit={submitMessage}>
          {showOperationPlan && operationPlan && (
              <ol className="conversation-operation-plan" aria-label={pick("Multi-action progress", "多意图执行进度")}>
                {operationPlan.operations.map((operation) => (
                  <li key={operation.id} data-status={operation.status}>
                    <span>{operation.sequence + 1}</span>
                    <strong>{localizedIntentActionLabels[operation.intent]}</strong>
                    <small>
                      {localizedOperationStatusLabels[operation.status] ?? pick("Processing", "处理中")}
                    </small>
                    {operation.status === "awaiting_intent" && (
                      <div className="conversation-operation-confirmation">
                        {(
                          [
                            "CASE_GENERATE",
                            "CASE_MODIFY",
                            "KNOWLEDGE_QA",
                            "SMALL_TALK",
                          ] as ConversationIntent[]
                        ).map((intent) => (
                          <button
                            type="button"
                            key={intent}
                            disabled={busy}
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
          {displayedTargets.length > 0 && (
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
                    ? pick("AI is rewriting", "AI 正在改写")
                    : rewriteStatus === "review"
                      ? pick("Rewrite complete, awaiting review", "改写完成，等待审阅")
                      : pick("Changes applied", "修改已应用")}
                </strong>
                <small>
                  {rewriteStatus === "running"
                    ? pick(`Processing ${activeRewriteTargets.length} targets and generating field-level differences…`, `正在处理 ${activeRewriteTargets.length} 个目标并生成字段差异…`)
                    : rewriteStatus === "review"
                      ? pick("Review the field differences before applying them to official test cases", "请检查字段差异，确认后再应用到正式用例")
                      : pick("Saved as a new revision and synced to the mind map", "已保存为新 Revision，脑图内容已同步更新")}
                </small>
              </span>
              {rewriteStatus === "running" && (
                <i className="principle-rewrite-status__track" aria-hidden="true" />
              )}
            </div>
          )}
          {attachmentLabels.length > 0 && (
            <div className="principle-attachments">
              {attachmentLabels.map((name) => (
                <span key={name}>{name}</span>
              ))}
            </div>
          )}
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder={
              effectivePendingOperationId
                ? pick("Select a test case or mind map node above to continue", "选择上方用例或脑图节点后，继续执行修改")
                : displayedTargets.length === 1
                  ? pick(`Describe how you want to modify “${displayedTargets[0].label}”…`, `描述你希望如何修改「${displayedTargets[0].label}」…`)
                  : displayedTargets.length > 1
                    ? pick(`Describe how you want to modify these ${displayedTargets.length} targets…`, `描述你希望如何修改这 ${displayedTargets.length} 个目标…`)
                : pick("Continue refining the test brief, maintain test cases, or ask about the requirements…", "继续修改测试说明、维护当前用例，或询问需求内容…")
            }
            aria-label={pick("Modify selected targets with natural language", "用自然语言修改选中目标")}
            rows={4}
            disabled={busy || !workspace}
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
              disabled={uploading || busy}
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
              disabled={busy}
            >
              {models.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.label}
                </option>
              ))}
            </select>
            {busy && currentJobId ? (
              <button
                type="button"
                className="principle-stop"
                onClick={() => void stopGeneration()}
              >
                <Square size={16} /> {pick("Stop generation", "停止生成")}
              </button>
            ) : busy ? (
              <button type="button" disabled>
                <LoaderCircle className="auth-spinner" size={16} /> {pick("Processing", "正在处理")}
              </button>
            ) : (
              <button
                type="submit"
                disabled={
                  uploading ||
                  !workspace ||
                  (effectivePendingOperationId
                    ? !selectedTargets.length
                    : !prompt.trim())
                }
              >
                <Send size={16} /> {effectivePendingOperationId
                  ? pick("Continue changes", "继续执行修改")
                  : displayedTargets.length
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
        aria-valuemin={380}
        aria-valuemax={640}
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
            <small>{pick("Test case collection / Continuous workspace", "用例集合 / 持续工作区")}</small>
            <div className="principle-title-row">
              <h1>{selectedCollection.name}</h1>
              <CollectionStatusBadge status={collectionStatus} />
            </div>
            <p>
              {localizedPhaseLabels[phase] ?? pick("Workspace restored", "工作区已恢复")} · {pick("This conversation only maintains this collection", "本对话仅维护此集合")}
            </p>
          </div>
          <div className="principle-canvas-actions">
            <button type="button" onClick={onOpenHistory}>
              <History size={17} />
              {pick("Conversation history", "历史对话")}
            </button>
            <button
              type="button"
              className="principle-new-conversation"
              onClick={onNewConversation}
            >
              <MessageSquarePlus size={17} />
              {pick("New conversation", "创建新对话")}
            </button>
          </div>
        </header>

        {(error || notice) && (
          <div
            className={`principle-banner ${error ? "is-error" : "is-success"}`}
          >
            {error ? <CircleAlert size={17} /> : <CheckCircle2 size={17} />}
            <span>{error || notice}</span>
            <button
              type="button"
              aria-label={pick("Dismiss notification", "关闭提示")}
              onClick={() => {
                setError("");
                setNotice("");
              }}
            >
              <X size={16} />
            </button>
          </div>
        )}

        {artifactOpen && selectedBrief ? (
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
                phase === "brief_review" && (
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
                        ? pick("Retry generation", "重新生成用例")
                        : pick("Confirm and generate", "确认并生成用例")}
                  </button>
                )}
            </header>
            <div className="principle-brief-guidance">
              {pick("This is a read-only Markdown artifact. Use the CasePilot conversation on the left to make changes.", "这是一份只读 Markdown 产物。如需调整，请在左侧与 CasePilot 对话。")}
            </div>
            <article className="principle-markdown" aria-label={pick("Structured test brief", "结构化测试说明")}>
              <Streamdown key={selectedBrief.id}>
                {selectedBrief.markdown_content}
              </Streamdown>
            </article>
            {selectedBrief.version === activeBrief?.version &&
              blockingQuestions.length > 0 && (
                <div className="principle-brief-blocker">
                  <CircleAlert size={17} />
                  {pick("The test target is not clear yet. Add details in the conversation before generating test cases.", "尚未明确测试对象，请先通过对话补充，再生成用例。")}
                </div>
              )}
          </section>
        ) : visibleCases.length ? (
          <section className="principle-case-area">
            <div className="principle-viewbar">
              <div>
                {selectedBrief && (
                  <button type="button" onClick={() => setArtifactOpen(true)}>
                    <Sparkles size={17} /> {pick("Structured brief", "结构化测试说明")}
                  </button>
                )}
                <button
                  type="button"
                  className={viewMode === "map" ? "is-active" : ""}
                  onClick={() => {
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
              </div>
              <span>
                {pick(
                  `${visibleCases.length} test cases · ${new Set(visibleCases.map((item) => item.module)).size} modules`,
                  `${visibleCases.length} 条用例 · ${new Set(visibleCases.map((item) => item.module)).size} 个模块`,
                )}
              </span>
              {phase === "candidate_review" && (
                <button
                  type="button"
                  className="is-primary"
                  onClick={() => void commitCandidates()}
                  disabled={!candidates.some((item) => item.included) || busy}
                >
                  <Save size={16} /> {pick("Add to official collection", "纳入正式集合")}
                </button>
              )}
            </div>
            {viewMode === "map" ? (
              <CaseMindMap
                key={`${selectedCollection.id}:${phase === "candidate_review" ? "candidates" : "official"}`}
                collection={selectedCollection}
                cases={visibleCases}
                selectedCaseId={selectedCaseId}
                onSelectCase={(caseId) => {
                  setSelectedCaseId(caseId);
                  const candidate = candidates.find((item) => item.id === caseId);
                  setCandidateDraft(
                    candidate ? structuredClone(candidate) : null,
                  );
                  onSelectCase(caseId);
                }}
                onCreateCase={() => undefined}
                onCreateCaseInline={phase === "maintenance" ? onCreateCaseInline : undefined}
                onEditCase={(testCase) => {
                  if (phase === "maintenance") onEditCase(testCase);
                  else setSelectedCaseId(testCase.id);
                }}
                onSaveCase={phase === "maintenance" ? onSaveCase : undefined}
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
            ) : (
              <div className="principle-case-list">
                {visibleCases.map((testCase) => {
                  const candidate = candidates.find(
                    (item) => item.id === testCase.id,
                  );
                  return (
                    <div
                      key={testCase.id}
                      className={[
                        "principle-case-row",
                        selectedCaseId === testCase.id ? "is-active" : "",
                        activeRewriteTargets.some(
                          (item) =>
                            item.target.kind === "case" &&
                            item.target.case_ids?.includes(testCase.id),
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
                        <span>{testCase.case_key}</span>
                        <strong>{testCase.title}</strong>
                        <small>{testCase.module || pick("Uncategorized", "未分类")}</small>
                        <i
                          className={`priority-${testCase.priority.toLowerCase()}`}
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
                {phase === "maintenance" && (
                  <button type="button" onClick={() => onEditCase(selectedCase)}>
                    <Pencil size={15} /> {pick("Edit", "编辑")}
                  </button>
                )}
              </header>
              {candidateDraft ? (
                <div className="principle-candidate-editor">
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
                  <button type="button" onClick={() => void saveCandidate()}>
                    <Save size={16} /> {pick("Save candidate changes", "保存候选修改")}
                  </button>
                </div>
              ) : (
                <>
                  <h2>{selectedCase.title}</h2>
                  <div className="principle-tags">
                    <span>{selectedCase.module || pick("Uncategorized", "未分类")}</span>
                    <span>{selectedCase.case_type}</span>
                    <span>{selectedCase.priority}</span>
                  </div>
                </>
              )}
              <section>
                <strong>{pick("Preconditions", "前置条件")}</strong>
                <ul>
                  {selectedCase.preconditions.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </section>
              <section>
                <strong>{pick("Steps and checkpoints", "执行步骤与检查点")}</strong>
                <ol>
                  {selectedCase.steps.map((step) => (
                    <li key={step.id}>
                      <p>{step.action}</p>
                      <small>{step.expected}</small>
                    </li>
                  ))}
                </ol>
              </section>
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
