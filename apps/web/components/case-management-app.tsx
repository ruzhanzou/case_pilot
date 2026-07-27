"use client";

import { CaseEditorDialog } from "@/components/case-editor-dialog";
import { CaseLibrary } from "@/components/case-library";
import { CaseWorkbench } from "@/components/case-workbench";
import { CollectionEditorDialog } from "@/components/collection-editor-dialog";
import { ExecutionWorkspace } from "@/components/execution-workspace";
import {
  createCollection,
  createTestCase,
  createTestCasesBatch,
  deleteCollection,
  deleteTestCase,
  listCollections,
  listTestCases,
  updateCollection,
  updateTestCase,
  type Account,
  type CaseCollectionDto,
  type TestCaseDto,
  type TestCaseInput,
} from "@/lib/casepilot-api";
import { sampleAudioCases } from "@/lib/sample-audio-cases";
import { sampleLoginCases } from "@/lib/sample-cases";
import {
  CheckCircle2,
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

type ManagementPage = "workbench" | "library" | "execution";

const sampleCollectionName = "账号登录验收用例集";
const legacyCollectionDescription =
  "用于验收用例管理、版本修订和 QA 执行状态记录";
const sampleCollectionDescription =
  "覆盖账号登录、登录安全、会话管理与账号注册的 12 条结构化示例用例";
const audioCollectionName = "Audio Feature 用例集";
const audioCollectionDescription =
  "覆盖音频初始化、录制、实时反馈、中断恢复、保存回放和稳定性的 18 条结构化用例";

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
  const [workbenchDirty, setWorkbenchDirty] = useState(false);
  const [executionDirty, setExecutionDirty] = useState(false);
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
    const dirty =
      (page === "workbench" && workbenchDirty) ||
      (page === "execution" && executionDirty);
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

  useEffect(() => {
    let active = true;
    if (!space || bootstrapped.current) return;
    bootstrapped.current = true;
    setLoading(true);
    setError("");
    void (async () => {
      let availableCollections = await listCollections(space.id);
      let acceptanceCollection =
        availableCollections.find((item) => item.name === sampleCollectionName);
      const legacyCollection = availableCollections.find(
        (item) => item.name === "快速体验用例集",
      );
      if (
        acceptanceCollection &&
        acceptanceCollection.description === legacyCollectionDescription
      ) {
        acceptanceCollection = await updateCollection(
          acceptanceCollection.id,
          { description: sampleCollectionDescription },
        );
        availableCollections = availableCollections.map((item) =>
          item.id === acceptanceCollection?.id ? acceptanceCollection : item,
        );
      }
      if (!acceptanceCollection && legacyCollection) {
        acceptanceCollection = await updateCollection(legacyCollection.id, {
          name: sampleCollectionName,
          description: sampleCollectionDescription,
        });
        availableCollections = availableCollections.map((item) =>
          item.id === acceptanceCollection?.id ? acceptanceCollection : item,
        );
      }
      if (!acceptanceCollection) {
        acceptanceCollection = await createCollection(space.id, {
          name: sampleCollectionName,
          description: sampleCollectionDescription,
        });
        availableCollections = [...availableCollections, acceptanceCollection];
      }
      let acceptanceCases = await listTestCases(acceptanceCollection.id);
      const existingKeys = new Set(
        acceptanceCases.map((item) => item.case_key),
      );
      for (const definition of sampleLoginCases) {
        const caseKey = definition.input.case_key;
        if (!caseKey || existingKeys.has(caseKey)) continue;
        const created = await createTestCase(
          acceptanceCollection.id,
          definition.input,
        );
        acceptanceCases = [...acceptanceCases, created];
        existingKeys.add(caseKey);
      }
      let audioCollection = availableCollections.find(
        (item) => item.name === audioCollectionName,
      );
      if (!audioCollection) {
        audioCollection = await createCollection(space.id, {
          name: audioCollectionName,
          description: audioCollectionDescription,
        });
        availableCollections = [...availableCollections, audioCollection];
      }
      let audioCases = await listTestCases(audioCollection.id);
      const existingAudioKeys = new Set(
        audioCases.map((item) => item.case_key),
      );
      for (const definition of sampleAudioCases) {
        const caseKey = definition.input.case_key;
        if (!caseKey || existingAudioKeys.has(caseKey)) continue;
        const created = await createTestCase(
          audioCollection.id,
          definition.input,
        );
        audioCases = [...audioCases, created];
        existingAudioKeys.add(caseKey);
      }
      if (!active) return;
      setCollections(
        availableCollections.map((collection) => {
          if (collection.id === acceptanceCollection.id) {
            return { ...collection, case_count: acceptanceCases.length };
          }
          if (collection.id === audioCollection.id) {
            return { ...collection, case_count: audioCases.length };
          }
          return collection;
        }),
      );
      setSelectedCollectionId(acceptanceCollection.id);
      setCases(acceptanceCases);
      setSelectedCaseId(
        acceptanceCases.find((item) => item.case_key === "AUTH-001")?.id ??
          acceptanceCases[0]?.id ??
          "",
      );
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

  const importGeneratedCases = async (inputs: TestCaseInput[]) => {
    if (!selectedCollection) {
      throw new Error("请先选择目标用例集合");
    }
    setSaving(true);
    setError("");
    try {
      const created = await createTestCasesBatch(selectedCollection.id, inputs);
      await refreshCases(selectedCollection.id, created[0]?.id);
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
            className={page === "workbench" ? "is-active" : ""}
            onClick={() => {
              if (!confirmDiscardPageChanges()) return;
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

      <section className="management-stage">
        <header className="management-topbar">
          <div>
            <span>{space?.name ?? "本地质量空间"}</span>
            <strong>
              {page === "workbench"
                ? "AI 用例工作台"
                : page === "library"
                  ? "用例资产管理"
                  : "QA 用例执行"}
            </strong>
          </div>
          <div className="management-topbar__status">
            <CheckCircle2 size={15} />
            数据已连接
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

        {loading && !collections.length ? (
          <div className="management-loading management-loading--page">
            <LoaderCircle className="auth-spinner" size={24} />
            正在准备登录验收用例…
          </div>
        ) : page === "workbench" ? (
          <CaseWorkbench
            spaceName={space?.name ?? "本地质量空间"}
            collections={collections}
            selectedCollection={selectedCollection}
            cases={cases}
            loading={loading}
            onSelectCollection={(collectionId) => void selectCollection(collectionId)}
            onSelectCase={setSelectedCaseId}
            onCreateCase={(module) => setCaseEditor({ mode: "create", module })}
            onEditCase={(testCase) =>
              setCaseEditor({ mode: "edit", testCase })
            }
            onImportCases={importGeneratedCases}
            initialMode={workbenchMode}
            onDirtyChange={setWorkbenchDirty}
          />
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
