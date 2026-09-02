"use client";

import { CaseEditorDialog } from "@/components/case-editor-dialog";
import { CaseLibrary } from "@/components/case-library";
import { CaseWorkbench } from "@/components/case-workbench";
import { CollectionEditorDialog } from "@/components/collection-editor-dialog";
import { ConversationHistoryDrawer } from "@/components/conversation-history-drawer";
import { ExecutionWorkspace } from "@/components/execution-workspace";
import { KnowledgeBase } from "@/components/knowledge-base";
import { NewConversation } from "@/components/new-conversation";
import {
  cancelConversationOperation,
  continueOperationInNewConversation,
  createCollection,
  createConversation,
  createTestCase,
  createTestCasesBatch,
  confirmConversationIntent,
  deleteCollection,
  deleteTestCase,
  getConversation,
  listCollections,
  listTestCases,
  resumeConversationOperation,
  sendConversationMessage,
  updateCollection,
  updateTestCase,
  uploadConversationAttachments,
  waitForConversationJob,
  type Account,
  type AgentModelId,
  type CaseCollectionDto,
  type ConversationDto,
  type ConversationIntent,
  type ConversationSummaryDto,
  type ConversationTurnDto,
  type TestCaseDto,
  type TestCaseInput,
} from "@/lib/casepilot-api";
import {
  BookOpen,
  Layers3,
  LoaderCircle,
  LogOut,
  PencilLine,
  PlayCircle,
  Sparkles,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

type CaseManagementAppProps = {
  account: Account;
  onLogout: () => Promise<void>;
};

type ManagementPage = "workbench" | "knowledge" | "library" | "execution";

function nextRunnableOperation(conversation: ConversationDto) {
  const operations = conversation.operation_plan?.operations ?? [];
  return operations.find(
    (operation) =>
      operation.status === "queued" &&
      operations
        .filter((item) => item.sequence < operation.sequence)
        .every((item) => ["completed", "skipped"].includes(item.status)),
  );
}

const assetIntents: ConversationIntent[] = [
  "CASE_GENERATE",
  "CASE_MODIFY",
  "CASE_DELETE",
  "CASE_QUERY",
];

function shouldOpenWorkspace(
  intent: ConversationIntent,
  conversation: ConversationDto,
) {
  return Boolean(
    conversation.collection_id && assetIntents.includes(intent),
  );
}

export function CaseManagementApp({
  account,
  onLogout,
}: CaseManagementAppProps) {
  const space = account.spaces[0];
  const [page, setPage] = useState<ManagementPage>("workbench");
  const [workbenchMode, setWorkbenchMode] = useState<
    "create" | "workspace"
  >("create");
  const [executionNavigation, setExecutionNavigation] = useState<{
    id: number;
    mode: "overview" | "create";
  }>({ id: 0, mode: "overview" });
  const [collections, setCollections] = useState<CaseCollectionDto[]>([]);
  const [selectedCollectionId, setSelectedCollectionId] = useState("");
  const [cases, setCases] = useState<TestCaseDto[]>([]);
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [executionDirty, setExecutionDirty] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(true);
  const [historyRevision, setHistoryRevision] = useState(0);
  const [landingConversation, setLandingConversation] =
    useState<ConversationDto | null>(null);
  const [caseEditor, setCaseEditor] = useState<
    | { mode: "create"; module?: string }
    | { mode: "edit"; testCase: TestCaseDto }
    | null
  >(null);
  const [collectionEditor, setCollectionEditor] = useState<
    { mode: "create" } | { mode: "edit"; collection: CaseCollectionDto } | null
  >(null);
  const bootstrapped = useRef(false);

  const selectedCollection =
    collections.find((item) => item.id === selectedCollectionId) ?? null;
  const selectedCase =
    cases.find((item) => item.id === selectedCaseId) ?? null;
  const confirmDiscardPageChanges = () => {
    const dirty = page === "execution" && executionDirty;
    return (
      !dirty ||
      window.confirm("当前页面有尚未保存的修改，离开将丢失这些内容。是否继续？")
    );
  };

  const refreshCollections = async (preferredId?: string) => {
    if (!space) return [];
    const result = await listCollections(space.id);
    setCollections(result);
    setSelectedCollectionId((current) => {
      if (preferredId && result.some((item) => item.id === preferredId)) {
        return preferredId;
      }
      if (result.some((item) => item.id === current)) return current;
      return result[0]?.id ?? "";
    });
    return result;
  };

  const refreshCases = async (collectionId: string, preferredId?: string) => {
    const result = await listTestCases(collectionId);
    setCases(result);
    setSelectedCaseId((current) => {
      if (preferredId && result.some((item) => item.id === preferredId)) {
        return preferredId;
      }
      if (result.some((item) => item.id === current)) return current;
      return result[0]?.id ?? "";
    });
    setCollections((current) =>
      current.map((collection) =>
        collection.id === collectionId
          ? { ...collection, case_count: result.length }
          : collection,
      ),
    );
    return result;
  };

  const selectCollection = async (collectionId: string) => {
    setSelectedCollectionId(collectionId);
    setSelectedCaseId("");
    setCases([]);
    setLoading(true);
    setError("");
    try {
      await refreshCases(collectionId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "用例加载失败");
    } finally {
      setLoading(false);
    }
  };

  const openLibraryWithFreshCases = async () => {
    if (!selectedCollectionId) {
      setPage("library");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await refreshCases(selectedCollectionId);
      await refreshCollections(selectedCollectionId);
      setPage("library");
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "正式用例加载失败",
      );
    } finally {
      setLoading(false);
    }
  };

  const updateLandingStream = (jobId: string, content: string) => {
    setLandingConversation((current) =>
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
  };

  const sendNewConversationMessage = async (input: {
    content: string;
    modelId: AgentModelId;
  }) => {
    if (!space) return;
    setSaving(true);
    setError("");
    try {
      let conversation = landingConversation;
      if (!conversation) {
        conversation = await createConversation({
          spaceId: space.id,
          title: "新对话",
        });
        setLandingConversation(conversation);
      }

      const turn = await sendConversationMessage(conversation.id, {
        content: input.content,
        modelId: input.modelId,
        scope: "current",
        useSpaceKnowledge: true,
      });
      let refreshedConversation = await getConversation(conversation.id);
      setLandingConversation(refreshedConversation);

      setHistoryRevision((current) => current + 1);

      if (
        shouldOpenWorkspace(turn.intent, refreshedConversation) &&
        !turn.requires_intent_confirmation
      ) {
        if (refreshedConversation.collection_id) {
          await refreshCollections(refreshedConversation.collection_id);
          await selectCollection(refreshedConversation.collection_id);
        }
        setWorkbenchMode("workspace");
        setPage("workbench");
        return;
      }

      if (turn.action.job_id) {
        await waitForConversationJob(
          refreshedConversation.id,
          turn.action.job_id,
          900_000,
          (content) => updateLandingStream(turn.action.job_id!, content),
        );
        refreshedConversation = await getConversation(
          refreshedConversation.id,
        );
        setLandingConversation(refreshedConversation);
        setHistoryRevision((current) => current + 1);
      }
      for (let index = 0; index < 3; index += 1) {
        const nextOperation = nextRunnableOperation(refreshedConversation);
        if (!nextOperation) break;
        const resumed = await resumeConversationOperation(nextOperation.id);
        refreshedConversation = await getConversation(refreshedConversation.id);
        setLandingConversation(refreshedConversation);
        setHistoryRevision((current) => current + 1);
        if (shouldOpenWorkspace(resumed.intent, refreshedConversation)) {
          if (refreshedConversation.collection_id) {
            await refreshCollections(refreshedConversation.collection_id);
            await selectCollection(refreshedConversation.collection_id);
          }
          setWorkbenchMode("workspace");
          setPage("workbench");
          return;
        }
        if (resumed.action.job_id) {
          await waitForConversationJob(
            refreshedConversation.id,
            resumed.action.job_id,
            900_000,
            (content) =>
              updateLandingStream(resumed.action.job_id!, content),
          );
        }
        refreshedConversation = await getConversation(refreshedConversation.id);
        setLandingConversation(refreshedConversation);
        setHistoryRevision((current) => current + 1);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "消息处理失败");
      throw caught;
    } finally {
      setSaving(false);
    }
  };

  const uploadNewConversationFiles = async (files: File[]) => {
    if (!space) return;
    setSaving(true);
    setError("");
    try {
      let conversation = landingConversation;
      if (!conversation) {
        conversation = await createConversation({
          spaceId: space.id,
          title: "新对话",
        });
      }
      await uploadConversationAttachments(conversation.id, files);
      const refreshed = await getConversation(conversation.id);
      setLandingConversation(refreshed);
      setHistoryRevision((current) => current + 1);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "附件上传失败");
      throw caught;
    } finally {
      setSaving(false);
    }
  };

  const confirmLandingCollection = async (turn: ConversationTurnDto) => {
    setSaving(true);
    setError("");
    try {
      const bound = await getConversation(turn.conversation_id);
      setLandingConversation(bound);
      setHistoryRevision((current) => current + 1);
      if (!bound.collection_id) throw new Error("集合确认未生效");
      await refreshCollections(bound.collection_id);
      await selectCollection(bound.collection_id);
      setWorkbenchMode("workspace");
      setPage("workbench");
      if (turn.action.job_id) {
        void waitForConversationJob(
          bound.id,
          turn.action.job_id,
          900_000,
          (content) => updateLandingStream(turn.action.job_id!, content),
        ).then(async () => {
          setLandingConversation(await getConversation(bound.id));
          setHistoryRevision((current) => current + 1);
        });
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "集合绑定失败");
      throw caught;
    } finally {
      setSaving(false);
    }
  };

  const continueLandingInNewConversation = async (
    operationId: string,
    collectionId: string,
  ) => {
    setSaving(true);
    setError("");
    try {
      const conversation = await continueOperationInNewConversation(
        operationId,
        collectionId,
      );
      setLandingConversation(conversation);
      await refreshCollections(collectionId);
      await selectCollection(collectionId);
      setWorkbenchMode("workspace");
      setPage("workbench");
      setHistoryRevision((current) => current + 1);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "新建对话失败");
      throw caught;
    } finally {
      setSaving(false);
    }
  };

  const cancelLandingOperation = async (operationId: string) => {
    if (!landingConversation) return;
    setSaving(true);
    setError("");
    try {
      await cancelConversationOperation(operationId);
      setLandingConversation(await getConversation(landingConversation.id));
      setHistoryRevision((current) => current + 1);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "取消操作失败");
      throw caught;
    } finally {
      setSaving(false);
    }
  };

  const confirmLandingConversationIntent = async (
    messageId: string,
    intent: ConversationIntent,
  ) => {
    if (!landingConversation) return;
    setSaving(true);
    setError("");
    try {
      const turn = await confirmConversationIntent(messageId, intent);
      let refreshedConversation = await getConversation(landingConversation.id);
      setLandingConversation(refreshedConversation);
      setHistoryRevision((current) => current + 1);

      if (shouldOpenWorkspace(turn.intent, refreshedConversation)) {
        if (refreshedConversation.collection_id) {
          await refreshCollections(refreshedConversation.collection_id);
          await selectCollection(refreshedConversation.collection_id);
        }
        setWorkbenchMode("workspace");
        setPage("workbench");
        return;
      }

      if (turn.action.job_id) {
        await waitForConversationJob(
          refreshedConversation.id,
          turn.action.job_id,
          900_000,
          (content) => updateLandingStream(turn.action.job_id!, content),
        );
        refreshedConversation = await getConversation(
          refreshedConversation.id,
        );
        setLandingConversation(refreshedConversation);
        setHistoryRevision((current) => current + 1);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "意图确认失败");
      throw caught;
    } finally {
      setSaving(false);
    }
  };

  const confirmLandingOperation = async (
    operationId: string,
    intent: ConversationIntent,
  ) => {
    if (!landingConversation) return;
    setSaving(true);
    setError("");
    try {
      const turn = await resumeConversationOperation(operationId, { intent });
      const refreshed = await getConversation(landingConversation.id);
      setLandingConversation(refreshed);
      setHistoryRevision((current) => current + 1);
      if (shouldOpenWorkspace(intent, refreshed)) {
        if (refreshed.collection_id) {
          await refreshCollections(refreshed.collection_id);
          await selectCollection(refreshed.collection_id);
        }
        setWorkbenchMode("workspace");
      } else if (turn.action.job_id) {
        await waitForConversationJob(
          refreshed.id,
          turn.action.job_id,
          900_000,
          (content) => updateLandingStream(turn.action.job_id!, content),
        );
        setLandingConversation(await getConversation(refreshed.id));
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "意图确认失败");
      throw caught;
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    let active = true;
    if (!space || bootstrapped.current) return;
    bootstrapped.current = true;
    setLoading(true);
    setError("");
    void (async () => {
      const availableCollections = await listCollections(space.id);
      const initialCollection = availableCollections[0];
      const initialCases = initialCollection
        ? await listTestCases(initialCollection.id)
        : [];
      if (!active) return;
      setCollections(
        availableCollections.map((collection) =>
          collection.id === initialCollection?.id
            ? { ...collection, case_count: initialCases.length }
            : collection,
        ),
      );
      setSelectedCollectionId(initialCollection?.id ?? "");
      setCases(initialCases);
      setSelectedCaseId("");
    })()
      .catch((caught) => {
        if (active) {
          setError(
            caught instanceof Error ? caught.message : "用例数据加载失败",
          );
        }
      })
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [space]);

  const openHistoryConversation = async (
    conversation: ConversationSummaryDto,
  ) => {
    const detail = await getConversation(conversation.id);
    setLandingConversation(detail);
    if (conversation.collection_id) {
      await selectCollection(conversation.collection_id);
    }
    setWorkbenchMode(conversation.collection_id ? "workspace" : "create");
    setPage("workbench");
  };

  const displayName = useMemo(
    () => account.display_name.slice(0, 1).toUpperCase(),
    [account.display_name],
  );

  const saveCollection = async (input: {
    name: string;
    description: string;
  }, startExecution = false) => {
    if (!space || !collectionEditor) return;
    setSaving(true);
    setError("");
    try {
      const result =
        collectionEditor.mode === "create"
          ? await createCollection(space.id, input)
          : await updateCollection(collectionEditor.collection.id, input);
      await refreshCollections(result.id);
      if (collectionEditor.mode === "create") {
        await selectCollection(result.id);
        if (startExecution) {
          setExecutionNavigation((current) => ({
            id: current.id + 1,
            mode: "create",
          }));
          setPage("execution");
        }
      }
      setCollectionEditor(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "用例集合保存失败");
    } finally {
      setSaving(false);
    }
  };

  const removeCollection = async () => {
    if (!selectedCollection) return;
    if (
      !window.confirm(
        `确定删除用例集合“${selectedCollection.name}”吗？集合内用例仍保留在审计记录中。`,
      )
    ) {
      return;
    }
    setSaving(true);
    setError("");
    try {
      await deleteCollection(selectedCollection.id);
      setCases([]);
      setSelectedCaseId("");
      const remaining = await refreshCollections();
      if (remaining[0]) {
        await selectCollection(remaining[0].id);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "用例集合删除失败");
    } finally {
      setSaving(false);
    }
  };

  const saveCase = async (input: TestCaseInput) => {
    if (!selectedCollection || !caseEditor) return;
    setSaving(true);
    setError("");
    try {
      const result =
        caseEditor.mode === "create"
          ? await createTestCase(selectedCollection.id, input)
          : await updateTestCase(caseEditor.testCase.id, {
              ...input,
              base_revision_id: caseEditor.testCase.current_revision_id,
            });
      await refreshCases(selectedCollection.id, result.id);
      setCaseEditor(null);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message === "case_key_already_exists"
            ? "当前空间中已存在相同用例编号"
            : caught.message
          : "用例保存失败",
      );
    } finally {
      setSaving(false);
    }
  };

  const removeCase = async (testCase: TestCaseDto) => {
    if (!selectedCollection) return;
    if (!window.confirm(`确定删除用例 ${testCase.case_key} 吗？`)) return;
    setSaving(true);
    setError("");
    try {
      await deleteTestCase(testCase.id);
      await refreshCases(selectedCollection.id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "用例删除失败");
    } finally {
      setSaving(false);
    }
  };

  const importGeneratedCases = async (
    collectionId: string,
    inputs: TestCaseInput[],
  ) => {
    if (!collections.some((collection) => collection.id === collectionId)) {
      throw new Error("请先选择目标用例集合");
    }
    setSaving(true);
    setError("");
    try {
      const created = await createTestCasesBatch(collectionId, inputs);
      setSelectedCollectionId(collectionId);
      await refreshCases(collectionId, created[0]?.id);
      return created;
    } catch (caught) {
      const message =
        caught instanceof Error
          ? caught.message === "case_key_already_exists"
            ? "候选用例编号已存在，请调整候选后再保存"
            : caught.message === "duplicate_case_key_in_batch"
              ? "候选用例中存在重复编号，请调整后再保存"
              : caught.message
          : "候选用例写入失败";
      setError(message);
      throw caught;
    } finally {
      setSaving(false);
    }
  };

  return (
    <main className="management-app">
      <aside className="management-nav">
        <div className="management-brand" aria-label="CasePilot">
          <PencilLine size={21} />
        </div>
        <nav aria-label="主导航">
          <button
            type="button"
            className={page === "knowledge" ? "is-active" : ""}
            onClick={() => {
              if (!confirmDiscardPageChanges()) return;
              setHistoryOpen(false);
              setPage("knowledge");
            }}
            aria-label="空间知识库"
          >
            <BookOpen size={20} />
            <span>知识库</span>
          </button>
          <button
            type="button"
            className={page === "workbench" ? "is-active" : ""}
            onClick={() => {
              if (!confirmDiscardPageChanges()) return;
              setHistoryOpen(false);
              setWorkbenchMode("create");
              setPage("workbench");
            }}
            aria-label="AI 用例工作台"
          >
            <Sparkles size={20} />
            <span>AI 工作台</span>
          </button>
          <button
            type="button"
            className={page === "library" ? "is-active" : ""}
            onClick={() => {
              if (!confirmDiscardPageChanges()) return;
              setHistoryOpen(false);
              setPage("library");
            }}
            aria-label="用例管理"
          >
            <Layers3 size={20} />
            <span>用例管理</span>
          </button>
          <button
            type="button"
            className={page === "execution" ? "is-active" : ""}
            onClick={() => {
              if (!confirmDiscardPageChanges()) return;
              setHistoryOpen(false);
              setExecutionNavigation((current) => ({
                id: current.id + 1,
                mode: "overview",
              }));
              setPage("execution");
            }}
            aria-label="执行用例"
          >
            <PlayCircle size={20} />
            <span>执行用例</span>
          </button>
        </nav>
        <div className="management-nav__footer">
          <button
            type="button"
            className="management-avatar"
            title={account.display_name}
            aria-label={`当前用户：${account.display_name}`}
          >
            {displayName}
          </button>
          <button
            type="button"
            onClick={() => {
              if (!confirmDiscardPageChanges()) return;
              void onLogout();
            }}
            aria-label="退出登录"
            title="退出登录"
          >
            <LogOut size={19} />
          </button>
        </div>
      </aside>

      <section
        className={`management-stage${
          historyOpen && page === "workbench"
            ? " management-stage--history-open"
            : ""
        }`}
      >
        <header className="management-topbar">
          <div>
            <span>{space?.name ?? "本地质量空间"}</span>
            <strong>
              {page === "workbench"
                ? workbenchMode === "create"
                  ? "AI 新对话"
                  : "AI 用例工作台"
                : page === "knowledge"
                  ? "空间知识库"
                : page === "library"
                  ? "用例资产管理"
                  : "QA 用例执行"}
            </strong>
          </div>
          <div className="management-topbar__status">
            <span>{account.display_name}</span>
          </div>
        </header>

        {error && (
          <div className="management-banner-error">
            <span>{error}</span>
            <button type="button" onClick={() => setError("")} aria-label="关闭提示">
              <X size={16} />
            </button>
          </div>
        )}

        <ConversationHistoryDrawer
          spaceId={space?.id ?? ""}
          open={historyOpen && page === "workbench"}
          revision={historyRevision}
          currentConversationId={landingConversation?.id}
          onClose={() => setHistoryOpen(false)}
          onNewConversation={() => {
            setLandingConversation(null);
            setWorkbenchMode("create");
            setPage("workbench");
          }}
          onOpenConversation={openHistoryConversation}
        />

        {loading && !collections.length ? (
          <div className="management-loading management-loading--page">
            <LoaderCircle className="auth-spinner" size={24} />
            正在准备工作区…
          </div>
        ) : page === "workbench" && workbenchMode === "create" ? (
          <NewConversation
            spaceName={space?.name ?? "本地质量空间"}
            saving={saving}
            conversation={landingConversation}
            collections={collections}
            onSend={sendNewConversationMessage}
            onUploadFiles={uploadNewConversationFiles}
            onOpenLibrary={() => setPage("library")}
            onOpenHistory={() => setHistoryOpen(true)}
            onConfirmCollection={confirmLandingCollection}
            onContinueInNewConversation={continueLandingInNewConversation}
            onCancelOperation={cancelLandingOperation}
            onConfirmIntent={confirmLandingConversationIntent}
            onConfirmOperation={confirmLandingOperation}
          />
        ) : page === "workbench" ? (
          <CaseWorkbench
            spaceId={space?.id ?? ""}
            spaceName={space?.name ?? "本地质量空间"}
            selectedCollection={selectedCollection}
            cases={cases}
            loading={loading}
            conversationId={
              landingConversation?.collection_id === selectedCollectionId
                ? landingConversation.id
                : undefined
            }
            pendingOperationId={
              landingConversation?.operation_plan?.operations.find(
                (operation) => operation.status === "awaiting_target",
              )?.id
            }
            onSelectCase={setSelectedCaseId}
            onCreateCase={(module) => setCaseEditor({ mode: "create", module })}
            onEditCase={(testCase) =>
              setCaseEditor({ mode: "edit", testCase })
            }
            onImportCases={importGeneratedCases}
            onOpenLibrary={() => void openLibraryWithFreshCases()}
            onNewConversation={() => {
              setLandingConversation(null);
              setWorkbenchMode("create");
            }}
            onContinueInNewConversation={continueLandingInNewConversation}
            onCancelOperation={cancelLandingOperation}
            onOpenHistory={() => setHistoryOpen(true)}
          />
        ) : page === "knowledge" ? (
          <KnowledgeBase spaceId={space?.id ?? ""} />
        ) : page === "library" ? (
          <CaseLibrary
            collections={collections}
            selectedCollection={selectedCollection}
            cases={cases}
            selectedCase={selectedCase}
            loading={loading}
            onSelectCollection={(collectionId) => void selectCollection(collectionId)}
            onCreateCollection={() => setCollectionEditor({ mode: "create" })}
            onEditCollection={() =>
              selectedCollection &&
              setCollectionEditor({
                mode: "edit",
                collection: selectedCollection,
              })
            }
            onDeleteCollection={() => void removeCollection()}
            onCreateCase={(module) => setCaseEditor({ mode: "create", module })}
            onOpenWorkbench={() => {
              setWorkbenchMode("workspace");
              setPage("workbench");
            }}
            onStartExecution={() => {
              setExecutionNavigation((current) => ({
                id: current.id + 1,
                mode: "create",
              }));
              setPage("execution");
            }}
            onSelectCase={setSelectedCaseId}
            onEditCase={(testCase) =>
              setCaseEditor({ mode: "edit", testCase })
            }
            onDeleteCase={(testCase) => void removeCase(testCase)}
          />
        ) : (
          <ExecutionWorkspace
            spaceId={space?.id ?? ""}
            accountId={account.id}
            spaceRole={space?.role ?? "member"}
            collections={collections}
            preferredCollectionId={selectedCollectionId}
            navigationRequest={executionNavigation}
            onDirtyChange={setExecutionDirty}
          />
        )}
      </section>

      {caseEditor && (
        <CaseEditorDialog
          key={
            caseEditor.mode === "edit"
              ? `${caseEditor.testCase.id}-${caseEditor.testCase.current_revision_id}`
              : "new-case"
          }
          testCase={caseEditor.mode === "edit" ? caseEditor.testCase : null}
          initialModule={
            caseEditor.mode === "create" ? caseEditor.module : undefined
          }
          saving={saving}
          onClose={() => setCaseEditor(null)}
          onSave={saveCase}
        />
      )}

      {collectionEditor && (
        <CollectionEditorDialog
          key={
            collectionEditor.mode === "edit"
              ? collectionEditor.collection.id
              : "new-collection"
          }
          collection={
            collectionEditor.mode === "edit"
              ? collectionEditor.collection
              : null
          }
          saving={saving}
          onClose={() => setCollectionEditor(null)}
          onSave={saveCollection}
        />
      )}
    </main>
  );
}
