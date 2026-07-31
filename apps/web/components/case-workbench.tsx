"use client";

import { CaseMindMap } from "@/components/case-mind-map";
import {
  applyCaseChangeSet,
  cancelGeneration,
  commitWorkspaceCandidates,
  confirmTestBrief,
  downloadTestBrief,
  getCaseChangeSet,
  getOrCreateWorkspace,
  listGenerationModels,
  sendConversationMessage,
  updateWorkspaceCandidate,
  updateWorkspaceState,
  uploadKnowledgeFiles,
  waitForConversationJob,
  watchGeneration,
  type AgentModelId,
  type CaseChangeSetDto,
  type CaseCollectionDto,
  type ConversationDto,
  type ConversationIntent,
  type GenerationStage,
  type TestCaseDto,
  type TestCaseInput,
  type WorkspaceCandidateDto,
} from "@/lib/casepilot-api";
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
  onSelectCase: (caseId: string) => void;
  onCreateCase: (module?: string) => void;
  onEditCase: (testCase: TestCaseDto) => void;
  onImportCases: (
    collectionId: string,
    inputs: TestCaseInput[],
  ) => Promise<TestCaseDto[]>;
  onOpenLibrary: () => void;
  onNewConversation: () => void;
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

const terminalWorkflowStatuses = new Set(["completed", "failed", "cancelled"]);

function clampPanelWidth(value: number): number {
  return Math.min(520, Math.max(300, Math.round(value)));
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
    created_at: candidate.updated_at,
  };
}

function messageLabel(
  role: "user" | "assistant",
  intent: ConversationIntent | null,
  metadata: Record<string, unknown>,
): string {
  if (role === "user") return "你";
  if (
    intent === "CASE_GENERATE" &&
    ["draft", "update"].includes(String(metadata.brief_operation ?? ""))
  ) {
    return "测试说明";
  }
  return intent ? intentLabels[intent] : "CasePilot";
}

export function CaseWorkbench({
  spaceId,
  spaceName,
  selectedCollection,
  cases,
  loading,
  onSelectCase,
  onEditCase,
  onOpenLibrary,
  onNewConversation,
  onOpenHistory,
  onDirtyChange,
}: CaseWorkbenchProps) {
  const [workspace, setWorkspace] = useState<ConversationDto | null>(null);
  const [prompt, setPrompt] = useState("");
  const [modelId, setModelId] = useState<AgentModelId>("auto");
  const [models, setModels] = useState<{ id: string; label: string }[]>([]);
  const [viewMode, setViewMode] = useState<"list" | "map">("list");
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [busy, setBusy] = useState(false);
  const [currentJobId, setCurrentJobId] = useState("");
  const [progress, setProgress] = useState<GenerationStage | null>(null);
  const [liveStages, setLiveStages] = useState<GenerationStage[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedBriefVersion, setSelectedBriefVersion] = useState(0);
  const [artifactOpen, setArtifactOpen] = useState(false);
  const [chatWidth, setChatWidth] = useState(360);
  const [inspectorWidth, setInspectorWidth] = useState(360);
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
  const watchedJobRef = useRef("");
  const {
    scrollRef: messagesScrollRef,
    contentRef: messagesContentRef,
    scrollToBottom,
  } = useStickToBottom({ initial: "instant", resize: "smooth" });

  const phase = String(workspace?.context.phase ?? "idle");
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
  const visibleCases =
    phase === "candidate_review"
      ? candidateCases
      : phase === "maintenance"
        ? cases
        : [];
  const selectedCase =
    visibleCases.find((item) => item.id === selectedCaseId) ??
    visibleCases[0] ??
    null;
  const selectedCandidate =
    candidates.find((item) => item.id === selectedCase?.id) ?? null;
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
  const latestMessage = messages.at(-1);
  const inspectorCollapsed =
    artifactOpen ||
    !["candidate_review", "maintenance"].includes(phase);

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
    setArtifactOpen(
      ["brief_review", "brief_drafting", "generating"].includes(
        String(result.context.phase ?? "idle"),
      ),
    );
    setChatWidth(
      clampPanelWidth(Number(result.context.chat_width ?? 360)),
    );
    setInspectorWidth(
      clampPanelWidth(Number(result.context.inspector_width ?? 360)),
    );
    const restoredCaseId = String(result.context.selected_case_id ?? "");
    setSelectedCaseId(restoredCaseId);
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
    const result = await getOrCreateWorkspace(selectedCollectionId);
    applyWorkspaceResult(result);
    return result;
  }, [applyWorkspaceResult, selectedCollectionId]);
  const waitAndRefresh = useCallback(
    async (jobId: string, conversationId = workspace?.id ?? "") => {
      if (!conversationId || watchedJobRef.current === jobId) return;
      watchedJobRef.current = jobId;
      setBusy(true);
      setCurrentJobId(jobId);
      try {
        const job = await watchGeneration(jobId, (stage) => {
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
        });
        if (job.status === "failed") {
          throw new Error(job.error_code ?? "任务处理失败，请稍后重试");
        }
        await waitForConversationJob(conversationId, jobId);
        await refreshWorkspace();
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
    [refreshWorkspace, workspace?.id],
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
        setModels([{ id: "auto", label: "默认模型" }]);
      });
  }, []);

  useEffect(() => {
    if (!selectedCollectionId) return;
    let ignored = false;
    void getOrCreateWorkspace(selectedCollectionId)
      .then((result) => {
        if (ignored) return;
        applyWorkspaceResult(result);
        setError("");
        setNotice("");
      })
      .catch((caught) => {
        setError(caught instanceof Error ? caught.message : "工作区恢复失败");
      });
    return () => {
      ignored = true;
    };
  }, [applyWorkspaceResult, selectedCollectionId]);

  useEffect(() => {
    if (
      !workspace ||
      !activeWorkspaceJobId ||
      !["brief_drafting", "generating"].includes(phase)
    ) {
      return;
    }
    void waitAndRefresh(activeWorkspaceJobId, workspace.id).catch((caught) => {
      setError(caught instanceof Error ? caught.message : "任务恢复失败");
    });
  }, [activeWorkspaceJobId, phase, waitAndRefresh, workspace]);

  useEffect(() => {
    onDirtyChange?.(false);
    return () => onDirtyChange?.(false);
  }, [onDirtyChange]);

  useEffect(() => {
    if (!latestMessage) return;
    void scrollToBottom({
      animation: "smooth",
      ignoreEscapes: true,
    });
  }, [currentJobId, latestMessage, scrollToBottom]);

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
        `工作区附件 ${new Date().toLocaleString("zh-CN")}`,
        files,
        "temporary",
      );
      setSourceIds((current) => [...new Set([...current, result.source.id])]);
      setAttachmentLabels((current) => [
        ...current,
        ...files.map((file) => file.name),
      ]);
      setNotice("附件已自动保存到当前工作区");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "附件保存失败");
    } finally {
      setUploading(false);
    }
  };

  const submitMessage = async (event: FormEvent) => {
    event.preventDefault();
    if (!workspace || !prompt.trim() || busy) return;
    const content = prompt.trim();
    setPrompt("");
    setError("");
    setNotice("");
    const formalTargets =
      selectedCase && phase === "maintenance"
        ? selectedCase.module && /当前模块|整个模块|本模块/.test(content)
          ? cases
              .filter((item) => item.module === selectedCase.module)
              .map((item) => item.id)
          : [selectedCase.id]
        : [];
    const candidateTargets = selectedCandidate
      ? [
          {
            ref: selectedCandidate.ref,
            version: selectedCandidate.version,
            snapshot: selectedCandidate.snapshot as unknown as Record<
              string,
              unknown
            >,
          },
        ]
      : [];
    try {
      const turn = await sendConversationMessage(workspace.id, {
        content,
        modelId,
        scope:
          selectedCase?.module && /当前模块|整个模块|本模块/.test(content)
            ? "module"
            : "current",
        targetCaseIds: formalTargets,
        targetCandidateSnapshots: candidateTargets,
        knowledgeSourceIds: sourceIds,
        useSpaceKnowledge: true,
      });
      setWorkspace(
        await updateWorkspaceState(workspace.id, {
          draft_text: "",
        }),
      );
      const jobId = turn.action.job_id;
      if (jobId) {
        await waitAndRefresh(jobId);
      } else if (turn.action.change_set_id) {
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
      setPrompt(content);
      setError(caught instanceof Error ? caught.message : "消息处理失败");
    }
  };

  const stopGeneration = async () => {
    if (!currentJobId) return;
    setError("");
    try {
      await cancelGeneration(currentJobId);
      await refreshWorkspace();
      setNotice("生成已停止，结构化测试说明仍保留");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "停止生成失败");
    } finally {
      setBusy(false);
      setCurrentJobId("");
      setProgress(null);
    }
  };

  const confirmBriefAndGenerate = async () => {
    if (!workspace) return;
    setError("");
    try {
      if (!activeBrief) throw new Error("请先生成结构化测试说明");
      const turn = await confirmTestBrief(
        workspace.id,
        activeBrief.version,
        modelId,
      );
      if (turn.action.job_id) await waitAndRefresh(turn.action.job_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "测试说明确认失败");
    }
  };

  const toggleCandidate = async (
    candidate: WorkspaceCandidateDto,
    included: boolean,
  ) => {
    try {
      await updateWorkspaceCandidate(candidate.id, { included });
      await refreshWorkspace();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "候选状态保存失败");
    }
  };

  const saveCandidate = async () => {
    if (!candidateDraft) return;
    try {
      await updateWorkspaceCandidate(candidateDraft.id, {
        snapshot: candidateDraft.snapshot as unknown as Record<string, unknown>,
      });
      await refreshWorkspace();
      setNotice("候选修改已自动保存");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "候选保存失败");
    }
  };

  const commitCandidates = async () => {
    if (!workspace) return;
    setBusy(true);
    try {
      const committed = await commitWorkspaceCandidates(workspace.id);
      setNotice(`已纳入 ${committed.length} 条正式用例`);
      await refreshWorkspace();
      onOpenLibrary();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "候选纳入失败");
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
      await refreshWorkspace();
      setNotice("变更已应用并记录审计");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "变更应用失败");
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
    const move = (pointerEvent: PointerEvent) => {
      const delta =
        panel === "chat"
          ? pointerEvent.clientX - startX
          : startX - pointerEvent.clientX;
      const next = clampPanelWidth(startWidth + delta);
      latestWidth = next;
      if (panel === "chat") setChatWidth(next);
      else setInspectorWidth(next);
    };
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
      window.removeEventListener("blur", stop);
      if (separator.hasPointerCapture(pointerId)) {
        separator.releasePointerCapture(pointerId);
      }
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
    const next = clampPanelWidth(current + delta);
    if (panel === "chat") setChatWidth(next);
    else setInspectorWidth(next);
    persistPanelWidth(panel, next);
  };

  const resetPanelWidth = (panel: "chat" | "inspector") => {
    if (panel === "chat") setChatWidth(360);
    else setInspectorWidth(360);
    persistPanelWidth(panel, 360);
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
      setNotice(`已复制结构化测试说明 V${selectedBrief.version}`);
    } catch {
      setError("复制失败，请检查浏览器剪贴板权限。");
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
      anchor.download = `${safeName}-结构化测试说明-V${selectedBrief.version}.md`;
      anchor.click();
      URL.revokeObjectURL(url);
      setNotice(`已下载结构化测试说明 V${selectedBrief.version}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "下载测试说明失败");
    }
  };

  if (!selectedCollection) {
    return <div className="principle-empty">请先选择一个用例集合</div>;
  }

  return (
    <section
      className="principle-workbench"
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
          <span>当前工作区</span>
          <strong>{selectedCollection.name}</strong>
          <small>{spaceName} · 自动保存</small>
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
                    请先说明测试对象；其他测试内容由 CasePilot
                    分析并整理为结构化测试说明。
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
                  )}
                </span>
                {message.content && <p>{message.content}</p>}
                {(workflow || isLiveWorkflow) && (
                  <div
                    className="principle-workflow"
                    data-status={workflow?.status ?? "running"}
                  >
                    <strong>CasePilot 工作流</strong>
                    {renderedStages.map((stage, index) => (
                      <div
                        key={`${stage.stage}-${index}`}
                        className={`principle-workflow-stage is-${stage.status}`}
                      >
                        <Check size={13} />
                        <span>
                          {workflowStageLabels[stage.stage] ?? "处理任务"}
                        </span>
                        <small>{stage.progress}%</small>
                      </div>
                    ))}
                    {isLiveWorkflow && progress && (
                      <div className="principle-workflow-stage is-running">
                        <LoaderCircle className="auth-spinner" size={13} />
                        <span>
                          {workflowStageLabels[progress.name] ?? "正在处理"}
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
                            ? "处理完成"
                            : workflow.status === "cancelled"
                              ? "已停止，可继续修改或重新开始"
                              : "处理未完成，请重试"}
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
                    结构化测试说明 V{artifactVersion}.md
                  </button>
                )}
                {message.citations.length > 0 && (
                  <small>
                    来源：
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
            <strong>变更审阅</strong>
            {activeChangeSet.items.map((item) => (
              <div key={item.ref}>
                <span>
                  {String(item.base_snapshot.title ?? item.ref)}
                </span>
                {item.field_diff.map((diff) => {
                  const checked = acceptedFields[item.ref]?.includes(diff.field);
                  return (
                    <label key={diff.field}>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() =>
                          setAcceptedFields((current) => ({
                            ...current,
                            [item.ref]: checked
                              ? (current[item.ref] ?? []).filter(
                                  (field) => field !== diff.field,
                                )
                              : [...(current[item.ref] ?? []), diff.field],
                          }))
                        }
                      />
                      {diff.field === "delete" ? "确认软删除" : diff.field}
                    </label>
                  );
                })}
              </div>
            ))}
            <div>
              <button type="button" onClick={() => setActiveChangeSet(null)}>
                取消
              </button>
              <button type="button" onClick={() => void applyChangeSet()}>
                确认应用
              </button>
            </div>
          </div>
        )}

        <form className="principle-composer" onSubmit={submitMessage}>
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
            placeholder="继续修改测试说明、维护当前用例，或询问需求内容…"
            rows={4}
            disabled={busy}
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
              aria-label="添加附件"
            >
              {uploading ? (
                <LoaderCircle className="auth-spinner" size={18} />
              ) : (
                <Paperclip size={18} />
              )}
            </button>
            <select
              aria-label="生成模型"
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
            {busy ? (
              <button
                type="button"
                className="principle-stop"
                onClick={() => void stopGeneration()}
              >
                <Square size={16} /> 停止生成
              </button>
            ) : (
              <button type="submit" disabled={!prompt.trim() || uploading}>
                <Send size={16} /> 发送
              </button>
            )}
          </div>
        </form>
      </aside>

      <div
        className="principle-resizer"
        role="separator"
        aria-label="调整对话区域宽度"
        aria-orientation="vertical"
        aria-valuemin={300}
        aria-valuemax={520}
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
            <small>用例集合 / 持续工作区</small>
            <h1>{selectedCollection.name}</h1>
            <p>{phaseLabels[phase] ?? "工作区已恢复"}</p>
          </div>
          <div className="principle-canvas-actions">
            <button type="button" onClick={onOpenHistory}>
              <History size={17} />
              历史对话
            </button>
            <button
              type="button"
              className="principle-new-conversation"
              onClick={onNewConversation}
            >
              <MessageSquarePlus size={17} />
              创建新对话
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
              aria-label="关闭提示"
              onClick={() => {
                setError("");
                setNotice("");
              }}
            >
              <X size={16} />
            </button>
          </div>
        )}

        {(artifactOpen ||
          ["brief_review", "brief_drafting", "generating"].includes(phase)) &&
        selectedBrief ? (
          <section className="principle-brief">
            <header className="principle-brief-toolbar">
              <div className="principle-brief-identity">
                <Sparkles size={19} />
                <div>
                  <strong>结构化测试说明</strong>
                  <span>
                    {selectedBrief.status === "confirmed"
                      ? "已确认"
                      : selectedBrief.status === "superseded"
                        ? "历史版本 · 已失效"
                        : "自动保存草稿"}
                  </span>
                </div>
              </div>
              <label>
                <span>版本</span>
                <select
                  aria-label="测试说明版本"
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
                          ? " · 已确认"
                          : brief.status === "superseded"
                            ? " · 历史"
                            : " · 草稿"}
                      </option>
                    ))}
                </select>
              </label>
              <button type="button" onClick={() => void copyBrief()}>
                <Copy size={16} />
                复制
              </button>
              <button type="button" onClick={() => void saveBriefFile()}>
                <Download size={16} />
                下载 .md
              </button>
              {["candidate_review", "maintenance"].includes(phase) && (
                <button type="button" onClick={() => setArtifactOpen(false)}>
                  返回用例
                </button>
              )}
              {selectedBrief.version === activeBrief?.version &&
                activeBrief.status === "draft" &&
                phase === "brief_review" && (
                  <button
                    type="button"
                    className="is-primary"
                    onClick={() => void confirmBriefAndGenerate()}
                    disabled={busy || blockingQuestions.length > 0}
                  >
                    <Check size={16} />
                    确认并生成用例
                  </button>
                )}
            </header>
            <div className="principle-brief-guidance">
              这是一份只读 Markdown 产物。如需调整，请在左侧与 CasePilot
              对话。
            </div>
            <article className="principle-markdown" aria-label="结构化测试说明">
              <Streamdown key={selectedBrief.id}>
                {selectedBrief.markdown_content}
              </Streamdown>
            </article>
            {selectedBrief.version === activeBrief?.version &&
              blockingQuestions.length > 0 && (
                <div className="principle-brief-blocker">
                  <CircleAlert size={17} />
                  尚未明确测试对象，请先通过对话补充，再生成用例。
                </div>
              )}
          </section>
        ) : visibleCases.length ? (
          <section className="principle-case-area">
            <div className="principle-viewbar">
              <div>
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
                  <GitFork size={17} /> 用例脑图
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
                  <List size={17} /> 用例列表
                </button>
              </div>
              <span>
                {visibleCases.length} 条用例 ·{" "}
                {new Set(visibleCases.map((item) => item.module)).size} 个模块
              </span>
              {phase === "candidate_review" && (
                <button
                  type="button"
                  className="is-primary"
                  onClick={() => void commitCandidates()}
                  disabled={!candidates.some((item) => item.included) || busy}
                >
                  <Save size={16} /> 纳入正式集合
                </button>
              )}
            </div>
            {viewMode === "map" ? (
              <CaseMindMap
                collection={selectedCollection}
                cases={visibleCases}
                selectedCaseId={selectedCase?.id ?? ""}
                onSelectCase={(caseId) => {
                  setSelectedCaseId(caseId);
                  const candidate = candidates.find((item) => item.id === caseId);
                  setCandidateDraft(
                    candidate ? structuredClone(candidate) : null,
                  );
                  onSelectCase(caseId);
                }}
                onCreateCase={() => undefined}
                onEditCase={(testCase) => {
                  if (phase === "maintenance") onEditCase(testCase);
                  else setSelectedCaseId(testCase.id);
                }}
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
                      className={
                        selectedCase?.id === testCase.id
                          ? "principle-case-row is-active"
                          : "principle-case-row"
                      }
                    >
                      <button
                        type="button"
                        aria-pressed={selectedCase?.id === testCase.id}
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
                        }}
                      >
                        <span>{testCase.case_key}</span>
                        <strong>{testCase.title}</strong>
                        <small>{testCase.module || "未分类"}</small>
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
                          纳入
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
                <strong>正在恢复工作区</strong>
              </>
            ) : (
              <>
                <FileUp size={30} />
                <strong>脑图和用例列表保持空白</strong>
                <p>
                  输入生成需求后，先审阅并确认结构化测试说明；候选生成完成前不会展示旧用例。
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
          aria-label="调整详情区域宽度"
          aria-orientation="vertical"
          aria-valuemin={300}
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
                <span>CASE DETAILS</span>
                {phase === "maintenance" && (
                  <button type="button" onClick={() => onEditCase(selectedCase)}>
                    <Pencil size={15} /> 编辑
                  </button>
                )}
              </header>
              {candidateDraft ? (
                <div className="principle-candidate-editor">
                  <label>
                    标题
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
                    模块
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
                    优先级
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
                    <Save size={16} /> 保存候选修改
                  </button>
                </div>
              ) : (
                <>
                  <h2>{selectedCase.title}</h2>
                  <div className="principle-tags">
                    <span>{selectedCase.module || "未分类"}</span>
                    <span>{selectedCase.case_type}</span>
                    <span>{selectedCase.priority}</span>
                  </div>
                </>
              )}
              <section>
                <strong>前置条件</strong>
                <ul>
                  {selectedCase.preconditions.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </section>
              <section>
                <strong>执行步骤与检查点</strong>
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
              <strong>CasePilot 工作区</strong>
              <p>确认测试说明并完成候选生成后，可在这里审阅详细步骤。</p>
            </div>
          )}
        </aside>
      )}
    </section>
  );
}
