"use client";

import { ExecutionNotes } from "@/components/execution-notes";
import { PlaylistPicker } from "@/components/playlist-picker";
import {
  closeExecutionRun,
  deleteExecutionRun,
  addSpaceMember,
  createPlaylistExecutionRun,
  getExecutionRun,
  listSpaceMembers,
  listSpaceExecutionRuns,
  publicErrorMessage,
  reassignExecutionRecord,
  removeSpaceMember,
  updateExecutionRecord,
  type CaseCollectionDto,
  type ExecutionRecordDto,
  type ExecutionRunDto,
  type ExecutionRunSummaryDto,
  type ExecutionStatusApi,
  type PlaylistDto,
  type SpaceMemberDto,
} from "@/lib/casepilot-api";
import { matchesExecutionSearch } from "@/lib/execution-search";
import { useI18n } from "@/lib/i18n";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  CheckCircle2,
  Circle,
  ClipboardCheck,
  Clock3,
  History,
  LoaderCircle,
  Plus,
  SkipForward,
  Square,
  Search,
  Trash2,
  Users,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

type ExecutionWorkspaceProps = {
  spaceId: string;
  accountId: string;
  spaceRole: string;
  collections: CaseCollectionDto[];
  preferredCollectionId: string;
  navigationRequest: {
    id: number;
    mode: "overview" | "create";
  };
  playlistCreationId?: string;
  onDirtyChange?: (dirty: boolean) => void;
};

type ExecutionView = "overview" | "create" | "detail";

const executionOptions: {
  value: ExecutionStatusApi;
  en: string;
  zh: string;
  icon: typeof Circle;
}[] = [
  { value: "not_run", en: "Not run", zh: "未执行", icon: Circle },
  { value: "passed", en: "Passed", zh: "通过", icon: CheckCircle2 },
  { value: "failed", en: "Failed", zh: "不通过", icon: XCircle },
  { value: "skipped", en: "Skipped", zh: "跳过", icon: SkipForward },
  { value: "blocked", en: "Blocked", zh: "堵塞", icon: AlertTriangle },
];

type ExecutionRecordDraft = {
  recordId: string;
  status: ExecutionStatusApi;
  actualResult: string;
  defectRef: string;
};

function draftFromRecord(record: ExecutionRecordDto): ExecutionRecordDraft {
  return {
    recordId: record.id,
    status: record.status,
    actualResult: record.actual_result,
    defectRef: record.defect_ref,
  };
}

function formatTime(value: string, locale: string) {
  return new Intl.DateTimeFormat(locale, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function ExecutionWorkspace({
  spaceId,
  accountId,
  spaceRole,
  collections,
  preferredCollectionId,
  navigationRequest,
  playlistCreationId,
  onDirtyChange,
}: ExecutionWorkspaceProps) {
  const { locale, pick } = useI18n();
  const runStatusLabel: Record<string, string> = {
    active: pick("Active", "执行中"),
    completed: pick("Completed", "已完成"),
    aborted: pick("Aborted", "已终止"),
  };
  const executionStatusLabel = Object.fromEntries(
    executionOptions.map((option) => [option.value, pick(option.en, option.zh)]),
  ) as Record<ExecutionStatusApi, string>;
  const [taskQuery, setTaskQuery] = useState("");
  const [deletingId, setDeletingId] = useState("");
  const [pendingDelete, setPendingDelete] = useState<ExecutionRunSummaryDto | null>(null);
  const deleteDialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (pendingDelete) deleteDialogRef.current?.showModal();
    else deleteDialogRef.current?.close();
  }, [pendingDelete]);
  const deletedRunIds = useRef(new Set<string>());
  const [view, setView] = useState<ExecutionView>("overview");
  const [run, setRun] = useState<ExecutionRunDto | null>(null);
  const [runHistory, setRunHistory] = useState<ExecutionRunSummaryDto[]>([]);
  const [selectedRecordId, setSelectedRecordId] = useState("");
  const [selectedPlaylist, setSelectedPlaylist] = useState<PlaylistDto | null>(null);
  const [createSeedCollectionId, setCreateSeedCollectionId] = useState("");
  const [playlistRequestId, setPlaylistRequestId] = useState(0);
  const [description, setDescription] = useState("");
  const [descriptionError, setDescriptionError] = useState("");
  const [members, setMembers] = useState<SpaceMemberDto[]>([]);
  const [selectedAssigneeIds, setSelectedAssigneeIds] = useState<string[]>([]);
  const [memberEmail, setMemberEmail] = useState("");
  const [recordFilter, setRecordFilter] = useState("all");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [recordValidationError, setRecordValidationError] = useState("");
  const [recordDraft, setRecordDraft] =
    useState<ExecutionRecordDraft | null>(null);
  const descriptionRef = useRef<HTMLTextAreaElement>(null);
  const actualResultRef = useRef<HTMLTextAreaElement>(null);
  const activeRunId = run?.id;

  const refreshHistory = async () => {
    setRunHistory((await listSpaceExecutionRuns(spaceId)).filter((item) => !deletedRunIds.current.has(item.id)));
  };

  const refreshMembers = async () => {
    const result = await listSpaceMembers(spaceId);
    setMembers(result);
    setSelectedAssigneeIds((current) =>
      current.length
        ? current.filter((id) =>
            result.some((member) => member.account_id === id),
          )
        : result.map((member) => member.account_id),
    );
  };

  useEffect(() => {
    let ignored = false;
    const load = () => {
      void listSpaceExecutionRuns(spaceId)
        .then((items) => {
          if (!ignored) setRunHistory(items.filter((item) => !deletedRunIds.current.has(item.id)));
        })
        .catch((caught) => {
          if (!ignored) {
            setError(
              caught instanceof Error
                ? publicErrorMessage(caught.message)
                : pick("Failed to load execution runs", "执行任务加载失败"),
            );
          }
        });
    };
    load();
    const timer = window.setInterval(load, 5000);
    return () => {
      ignored = true;
      window.clearInterval(timer);
    };
  }, [pick, spaceId]);

  useEffect(() => {
    let ignored = false;
    void listSpaceMembers(spaceId)
      .then((result) => {
        if (ignored) return;
        setMembers(result);
        setSelectedAssigneeIds(
          result.map((member) => member.account_id),
        );
      })
      .catch((caught) => {
        if (!ignored) {
          setError(
            caught instanceof Error
              ? publicErrorMessage(caught.message)
              : pick("Failed to load space members", "空间成员加载失败"),
          );
        }
      });
    return () => {
      ignored = true;
    };
  }, [pick, spaceId]);

  useEffect(() => {
    if (navigationRequest.id === 0) return;
    const timer = window.setTimeout(() => {
      if (navigationRequest.mode === "create") {
        setRun(null);
        setSelectedRecordId("");
        setRecordDraft(null);
        setSelectedPlaylist(null);
        setCreateSeedCollectionId(preferredCollectionId || "");
        setPlaylistRequestId((current) => current + 1);
        setDescriptionError("");
        setView("create");
      } else {
        setRun(null);
        setSelectedRecordId("");
        setRecordDraft(null);
        setView("overview");
      }
    });
    return () => window.clearTimeout(timer);
  }, [collections, navigationRequest, preferredCollectionId]);

  const readOnly = run?.status !== "active";
  const selectedRecord =
    run?.records.find((record) => record.id === selectedRecordId) ?? null;
  const recordReadOnly = Boolean(
    readOnly || (selectedRecord && !selectedRecord.can_edit),
  );
  const filteredRecords = useMemo(() => {
    if (!run) return [];
    if (recordFilter === "mine") {
      return run.records.filter((record) => record.assignee_id === accountId);
    }
    if (recordFilter.startsWith("assignee:")) {
      const assigneeId = recordFilter.slice("assignee:".length);
      return run.records.filter((record) => record.assignee_id === assigneeId);
    }
    return run.records;
  }, [accountId, recordFilter, run]);
  const recordDraftDirty = Boolean(
    selectedRecord &&
      recordDraft?.recordId === selectedRecord.id &&
      (recordDraft.status !== selectedRecord.status ||
        recordDraft.actualResult !== selectedRecord.actual_result ||
        recordDraft.defectRef !== selectedRecord.defect_ref),
  );
  useEffect(() => {
    if (view !== "detail" || !activeRunId || saving) return;
    const timer = window.setInterval(() => {
      void getExecutionRun(activeRunId)
        .then((latestRun) => {
          setRun(latestRun);
          if (!recordDraftDirty) {
            const latestRecord =
              latestRun.records.find(
                (record) => record.id === selectedRecordId,
              ) ?? null;
            setRecordDraft(
              latestRecord ? draftFromRecord(latestRecord) : null,
            );
          }
        })
        .catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [
    activeRunId,
    recordDraftDirty,
    saving,
    selectedRecordId,
    view,
  ]);

  useEffect(() => {
    onDirtyChange?.(recordDraftDirty);
    return () => onDirtyChange?.(false);
  }, [onDirtyChange, recordDraftDirty]);

  useEffect(() => {
    if (!recordDraftDirty) return;
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [recordDraftDirty]);

  const progress = useMemo(() => {
    if (!run?.records.length) return { done: 0, total: 0, percent: 0 };
    const done = run.records.filter(
      (record) => record.status !== "not_run",
    ).length;
    return {
      done,
      total: run.records.length,
      percent: Math.round((done / run.records.length) * 100),
    };
  }, [run]);

  const filteredRuns = runHistory.filter((item) => matchesExecutionSearch(item, taskQuery));

  const deleteRun = async (item: ExecutionRunSummaryDto) => {
    if (deletingId || !item.can_manage) return;
    setDeletingId(item.id);
    setError("");
    try {
      await deleteExecutionRun(item.id);
      setPendingDelete(null);
      deletedRunIds.current.add(item.id);
      setRunHistory((items) => items.filter((entry) => entry.id !== item.id));
    } catch (caught) {
      setError(caught instanceof Error ? publicErrorMessage(caught.message) : pick("Failed to delete run", "删除任务失败"));
    } finally {
      setDeletingId("");
    }
  };

  const overviewStats = useMemo(
    () => ({
      total: runHistory.length,
      active: runHistory.filter((item) => item.status === "active").length,
      completed: runHistory.filter((item) => item.status === "completed").length,
      contributors: new Set(
        runHistory.flatMap((item) => item.contributor_names),
      ).size,
    }),
    [runHistory],
  );

  const startRun = async () => {
    if (!selectedPlaylist) {
      setError(pick("Select or save a Playlist first.", "请先选择或保存一个 Playlist。"));
      return;
    }
    if (!description.trim()) {
      setDescriptionError(pick("Describe the objective or scope of this run.", "请填写本次执行任务的目标或范围。"));
      descriptionRef.current?.focus();
      return;
    }
    if (!selectedPlaylist.case_count) {
      setError(pick("An empty Playlist cannot start an execution run.", "空 Playlist 不能创建执行任务。"));
      return;
    }
    if (selectedPlaylist.unavailable_case_ids.length) {
      setError(pick("The Playlist contains unavailable cases. Remove them before creating the run.", "Playlist 中存在不可用用例，请编辑并移除后再创建任务。"));
      return;
    }
    if (!selectedAssigneeIds.length) {
      setError(pick("Select at least one assignee.", "请至少选择一名执行人。"));
      return;
    }
    setLoading(true);
    setError("");
    setDescriptionError("");
    try {
      const result = await createPlaylistExecutionRun(spaceId, {
        playlist_id: selectedPlaylist.id,
        description: description.trim(),
        assignee_ids: selectedAssigneeIds,
      });
      setRun(result);
      setSelectedRecordId(result.records[0]?.id ?? "");
      setRecordDraft(
        result.records[0] ? draftFromRecord(result.records[0]) : null,
      );
      setDescription("");
      setView("detail");
      await refreshHistory();
    } catch (caught) {
      setError(
        caught instanceof Error
          ? publicErrorMessage(caught.message)
          : pick("Failed to create execution run", "执行任务创建失败"),
      );
    } finally {
      setLoading(false);
    }
  };

  const openRun = async (runId: string) => {
    setLoading(true);
    setError("");
    try {
      const result = await getExecutionRun(runId);
      setRun(result);
      setSelectedRecordId(result.records[0]?.id ?? "");
      setRecordDraft(
        result.records[0] ? draftFromRecord(result.records[0]) : null,
      );
      setView("detail");
    } catch (caught) {
      setError(
        caught instanceof Error
          ? publicErrorMessage(caught.message)
          : pick("Failed to load execution run", "执行任务加载失败"),
      );
    } finally {
      setLoading(false);
    }
  };

  const finishRun = async () => {
    if (!run || readOnly || !run.can_manage) return;
    if (recordDraftDirty) {
      setRecordValidationError(pick("Save or discard the current result before ending the run.", "请先保存或放弃当前用例的执行记录，再结束任务。"));
      return;
    }
    const remaining = progress.total - progress.done;
    const message = remaining
      ? pick(`${remaining} test cases have not been run. Ending the run makes it read-only. Continue?`, `仍有 ${remaining} 条用例未执行。确认结束后任务将变为只读，是否继续？`)
      : pick("Ending the run makes it read-only and results can no longer be changed. Continue?", "结束后任务将变为只读，无法继续修改执行结果。确认结束任务吗？");
    if (!window.confirm(message)) return;
    setSaving(true);
    setError("");
    try {
      const result = await closeExecutionRun(
        run.id,
        "completed",
        remaining > 0,
      );
      setRun(result);
      await refreshHistory();
    } catch (caught) {
      setError(
        caught instanceof Error
          ? publicErrorMessage(caught.message)
          : pick("Failed to end execution run", "执行任务结束失败"),
      );
    } finally {
      setSaving(false);
    }
  };

  const persistRecord = async (
    record: ExecutionRecordDto,
    patch: Partial<
      Pick<
        ExecutionRecordDto,
        "status" | "completed_step_ids" | "actual_result" | "defect_ref"
      >
    >,
  ): Promise<ExecutionRecordDto | null> => {
    if (readOnly || !record.can_edit) return null;
    setSaving(true);
    setError("");
    try {
      const updated = await updateExecutionRecord(record.id, {
        status: patch.status ?? record.status,
        completed_step_ids:
          patch.completed_step_ids ?? record.completed_step_ids,
        actual_result: patch.actual_result ?? record.actual_result,
        defect_ref: patch.defect_ref ?? record.defect_ref,
        base_updated_at: record.updated_at,
      });
      setRun((current) =>
        current
          ? {
              ...current,
              contributor_names: updated.updated_by_name
                ? Array.from(
                    new Set([
                      ...current.contributor_names,
                      updated.updated_by_name,
                    ]),
                  )
                : current.contributor_names,
              records: current.records.map((item) =>
                item.id === updated.id ? updated : item,
              ),
            }
          : current,
      );
      if (!recordDraftDirty) setRecordDraft(draftFromRecord(updated));
      await refreshHistory();
      return updated;
    } catch (caught) {
      if (caught instanceof Error && caught.message === "execution_record_changed") {
        if (run) {
          const latestRun = await getExecutionRun(run.id);
          setRun(latestRun);
        }
        setError(pick("Another member just updated this case. The latest result has been loaded; review it and try again.", "该用例刚被其他成员更新，已为你加载最新结果，请确认后重试。"));
      } else {
        setError(
          caught instanceof Error
            ? publicErrorMessage(caught.message)
            : pick("Failed to save execution result", "执行记录保存失败"),
        );
      }
      return null;
    } finally {
      setSaving(false);
    }
  };

  const discardRecordDraft = () => {
    if (selectedRecord) setRecordDraft(draftFromRecord(selectedRecord));
    setRecordValidationError("");
  };

  const confirmDiscardRecordDraft = () =>
    !recordDraftDirty ||
    window.confirm(pick("The current result is unsaved and will be lost. Continue?", "当前执行结果尚未保存，离开将丢失这些修改。是否继续？"));

  const selectExecutionRecord = (recordId: string) => {
    if (!confirmDiscardRecordDraft()) return;
    const nextRecord =
      run?.records.find((record) => record.id === recordId) ?? null;
    setRecordDraft(nextRecord ? draftFromRecord(nextRecord) : null);
    setRecordValidationError("");
    setSelectedRecordId(recordId);
  };

  const saveRecordDraft = async () => {
    if (!selectedRecord || !recordDraft || recordReadOnly) return;
    if (
      ["failed", "skipped", "blocked"].includes(recordDraft.status) &&
      !recordDraft.actualResult.trim()
    ) {
      setRecordValidationError(
        recordDraft.status === "failed"
          ? pick("Enter the actual result when marking a case as failed.", "标记不通过时必须填写实际结果。")
          : recordDraft.status === "skipped"
            ? pick("Enter a reason when marking a case as skipped.", "标记跳过时必须填写跳过原因。")
            : pick("Enter the cause, dependency, and unblock condition when marking a case as blocked.", "标记堵塞时必须填写原因、依赖和解除条件。"),
      );
      actualResultRef.current?.focus();
      return;
    }
    setRecordValidationError("");
    const updated = await persistRecord(selectedRecord, {
      status: recordDraft.status,
      actual_result: recordDraft.actualResult,
      defect_ref: recordDraft.defectRef,
    });
    if (updated) setRecordDraft(draftFromRecord(updated));
  };

  const addMember = async () => {
    if (!memberEmail.trim()) return;
    setLoading(true);
    setError("");
    try {
      await addSpaceMember(spaceId, memberEmail.trim());
      setMemberEmail("");
      await refreshMembers();
    } catch (caught) {
      setError(
        caught instanceof Error
          ? publicErrorMessage(caught.message)
          : pick("Failed to add member", "成员添加失败"),
      );
    } finally {
      setLoading(false);
    }
  };

  const removeMember = async (memberId: string) => {
    setLoading(true);
    setError("");
    try {
      await removeSpaceMember(spaceId, memberId);
      await refreshMembers();
    } catch (caught) {
      setError(
        caught instanceof Error
          ? publicErrorMessage(caught.message)
          : pick("Failed to remove member", "成员移除失败"),
      );
    } finally {
      setLoading(false);
    }
  };

  const reassignRecord = async (recordId: string, assigneeId: string) => {
    if (!run?.can_manage) return;
    setSaving(true);
    setError("");
    try {
      const updated = await reassignExecutionRecord(recordId, assigneeId);
      setRun((current) =>
        current
          ? {
              ...current,
              assignee_ids: Array.from(
                new Set([...current.assignee_ids, assigneeId]),
              ),
              assignee_names: Array.from(
                new Set([
                  ...current.assignee_names,
                  updated.assignee_name ?? "",
                ]),
              ).filter(Boolean),
              records: current.records.map((item) =>
                item.id === updated.id ? updated : item,
              ),
            }
          : current,
      );
      setRecordDraft(draftFromRecord(updated));
    } catch (caught) {
      setError(
        caught instanceof Error
          ? publicErrorMessage(caught.message)
          : pick("Failed to reassign", "重新分配失败"),
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className={
        view === "detail"
          ? "execution-workspace execution-workspace--detail"
          : "execution-workspace"
      }
    >
      {error && (
        <div className="management-banner-error" role="alert">{error}</div>
      )}
      <dialog ref={deleteDialogRef} className="execution-delete-dialog"
        aria-labelledby="execution-delete-title" aria-describedby="execution-delete-description"
        onCancel={(event) => { event.preventDefault(); if (!deletingId) setPendingDelete(null); }}>
        <h2 id="execution-delete-title">{pick("Delete task?", "删除任务？")}</h2>
        <p id="execution-delete-description">{pick(
          `“${pendingDelete?.description ?? ""}” and its execution results and notes will be permanently deleted. Source cases and Playlists are kept.`,
          `“${pendingDelete?.description ?? ""}”及其执行结果和备注将永久删除，原始用例和 Playlist 会保留。`,
        )}</p>
        {error && <p role="alert" className="management-banner-error">{error}</p>}
        <div className="management-modal__footer">
          <button type="button" className="management-button" disabled={Boolean(deletingId)}
            onClick={() => setPendingDelete(null)}>{pick("Cancel", "取消")}</button>
          <button type="button" className="management-button" disabled={Boolean(deletingId)}
            onClick={() => pendingDelete && void deleteRun(pendingDelete)}>
            {deletingId ? pick("Deleting…", "删除中…") : pick("Confirm delete", "确认删除")}
          </button>
        </div>
      </dialog>

      {view === "overview" && (
        <>
          <header className="execution-header execution-header--overview">
            <div>
              <span className="management-kicker">{pick("QA EXECUTION", "QA 执行任务")}</span>
              <h1>{pick("Execution runs", "执行任务")}</h1>
              <p>{pick("Track live progress, results, and participants across all runs.", "查看所有任务的实时进度、执行结果和参与成员。")}</p>
            </div>
            <button
              type="button"
              className="management-button management-button--primary"
              onClick={() => {
                setSelectedPlaylist(null);
                setCreateSeedCollectionId("");
                setPlaylistRequestId((current) => current + 1);
                setView("create");
              }}
            >
              <Plus size={16} /> {pick("New Playlist run", "新建 Playlist 执行任务")}
            </button>
          </header>

          <section className="execution-playlist-callout">
            <div className="execution-playlist-callout__icon">
              <ClipboardCheck size={22} />
            </div>
            <div>
              <span className="management-kicker">{pick("PLAYLIST SCOPE", "Playlist 执行范围")}</span>
              <strong>{pick("Select and reuse cases across collections", "跨用例集合选择并复用执行用例")}</strong>
              <p>{pick("Add one or more full collections, or search and select individual cases. Duplicates are removed automatically.", "支持完整加入单个或多个用例集合，也可搜索并逐条选择用例；重复用例会自动去重。")}</p>
            </div>
            <button
              type="button"
              className="management-button"
              onClick={() => {
                setSelectedPlaylist(null);
                setCreateSeedCollectionId("");
                setPlaylistRequestId((current) => current + 1);
                setView("create");
              }}
            >
              {pick("Manage Playlists", "管理 Playlist")}
            </button>
          </section>

          <section className="execution-overview-metrics">
            <article>
              <History size={18} />
              <div><strong>{overviewStats.total}</strong><span>{pick("All runs", "全部任务")}</span></div>
            </article>
            <article>
              <Clock3 size={18} />
              <div><strong>{overviewStats.active}</strong><span>{pick("Active", "执行中")}</span></div>
            </article>
            <article>
              <CheckCircle2 size={18} />
              <div><strong>{overviewStats.completed}</strong><span>{pick("Completed", "已完成")}</span></div>
            </article>
            <article>
              <Users size={18} />
              <div><strong>{overviewStats.contributors}</strong><span>{pick("Participants", "参与成员")}</span></div>
            </article>
          </section>

          <section className="execution-task-list">
            <div className="execution-task-list__head">
              <div>
                <strong>{pick("Run history", "任务历史")}</strong>
                <span>{pick("Multi-user progress syncs every 5 seconds", "每 5 秒自动同步多人执行进度")}</span>
              </div>
              <span>{pick(`${runHistory.length} runs`, `${runHistory.length} 个任务`)}</span>
            </div>
            <label className="execution-task-search">
              <Search size={16} aria-hidden="true" />
              <input type="search" value={taskQuery} onChange={(event) => setTaskQuery(event.target.value)}
                aria-label={pick("Search tasks", "搜索任务")}
                placeholder={pick("Search description, source, or member", "搜索任务描述、来源或成员")} />
              <span aria-live="polite">{pick(`${filteredRuns.length} runs`, `${filteredRuns.length} 个任务`)}</span>
            </label>
            {filteredRuns.length === 0 ? (
              <div className="management-empty management-empty--detail">
                <ClipboardCheck size={30} />
                <strong>{taskQuery.trim() ? pick("No matching tasks", "未找到匹配的任务") : pick("No execution runs", "暂无执行任务")}</strong>
                <span>{taskQuery.trim() ? pick("Try another keyword or clear the search.", "请尝试其他关键词或清空搜索。") : pick("Create a run to execute cases with space members.", "创建任务后即可邀请空间成员共同执行")}</span>
              </div>
            ) : (
              <div className="execution-task-grid">
                {filteredRuns.map((item) => {
                  const done = item.total_count - item.not_run_count;
                  const percent = item.total_count
                    ? Math.round((done / item.total_count) * 100)
                    : 0;
                  return (
                    <article className="execution-task-card" key={item.id}>
                    <button
                      type="button"
                      className="execution-task-card__open"
                      onClick={() => void openRun(item.id)}
                    >
                      <div className="execution-task-card__top">
                        <span
                          className={`execution-task-status execution-task-status--${item.status}`}
                        >
                          {runStatusLabel[item.status] ?? item.status}
                        </span>
                        <small>{pick(`Updated ${formatTime(item.last_activity_at, locale)}`, `${formatTime(item.last_activity_at, locale)} 更新`)}</small>
                      </div>
                      <strong>{item.description}</strong>
                      <span>
                        {item.source_name} · {pick(`from ${item.source_collection_count} collections · ${item.total_count} cases`, `来自 ${item.source_collection_count} 个集合 · ${item.total_count} 条用例`)}
                      </span>
                      <div className="execution-task-card__progress">
                        <div>
                          <b>{percent}%</b>
                          <span>{pick(`${done} / ${item.total_count} executed`, `${done} / ${item.total_count} 已执行`)}</span>
                        </div>
                        <i><em style={{ width: `${percent}%` }} /></i>
                      </div>
                      <div className="execution-task-card__results">
                        <span>{pick(`${item.passed_count} passed`, `${item.passed_count} 通过`)}</span>
                        <span>{pick(`${item.failed_count} failed`, `${item.failed_count} 不通过`)}</span>
                        <span>{pick(`${item.blocked_count} blocked`, `${item.blocked_count} 堵塞`)}</span>
                      </div>
                      <div className="execution-task-card__people">
                        <Users size={14} />
                        <span>
                          {item.contributor_names.length
                            ? item.contributor_names.join("、")
                            : item.creator_name}
                        </span>
                      </div>
                    </button>
                    {item.can_manage && (
                      <button type="button" className="execution-task-card__delete"
                        disabled={Boolean(deletingId)} onClick={() => setPendingDelete(item)}
                        aria-label={pick(`Delete task: ${item.description}`, `删除任务：${item.description}`)}>
                        {deletingId === item.id ? <LoaderCircle size={14} /> : <Trash2 size={14} />}
                        {pick("Delete", "删除")}
                      </button>
                    )}
                    </article>
                  );
                })}
              </div>
            )}
          </section>
        </>
      )}

      {view === "create" && (
        <>
          <header className="execution-header">
            <div>
              <button
                type="button"
                className="execution-back"
                onClick={() => setView("overview")}
              >
                <ArrowLeft size={15} /> {pick("Back to runs", "返回任务列表")}
              </button>
              <span className="management-kicker">{pick("NEW EXECUTION RUN", "新建执行任务")}</span>
              <h1>{pick("Create a collaborative run", "创建多人执行任务")}</h1>
              <p>{pick("Choose a reusable Playlist and describe the run for your team.", "选择可复用 Playlist 并填写任务描述，空间成员可共同执行。")}</p>
            </div>
          </header>
          <section className="execution-run-setup">
            <div>
              <span className="management-kicker">{pick("RUN SETTINGS", "任务设置")}</span>
              <h2>{pick("Choose scope and describe the run", "选择执行范围并填写任务说明")}</h2>
              <p>{pick("Case revisions are frozen at creation; later edits do not change this run.", "创建时冻结当前用例修订；后续修改用例不会改变本任务记录。")}</p>
            </div>
            <div className="execution-run-setup__fields">
              <PlaylistPicker
                key={playlistRequestId}
                spaceId={spaceId}
                collections={collections}
                seedCollectionId={createSeedCollectionId}
                requestId={playlistRequestId}
                creationSessionId={playlistCreationId}
                selectedPlaylistId={selectedPlaylist?.id ?? ""}
                onSelect={setSelectedPlaylist}
                onError={setError}
              />
              <label>
                {pick("Run description *", "任务描述 *")}
                <textarea
                  ref={descriptionRef}
                  rows={4}
                  value={description}
                  aria-invalid={descriptionError ? "true" : undefined}
                  aria-describedby={
                    descriptionError ? "execution-description-error" : undefined
                  }
                  onChange={(event) => {
                    setDescription(event.target.value);
                    if (event.target.value.trim()) setDescriptionError("");
                  }}
                  placeholder={pick("e.g. Validate recording, transcription, and interruption recovery", "例如：验证 Audio Feature 录音、转写与中断恢复主流程")}
                />
                {descriptionError && (
                  <small
                    id="execution-description-error"
                    className="execution-field-error"
                    role="alert"
                  >
                    {descriptionError}
                  </small>
                )}
              </label>
              <fieldset className="execution-assignee-picker">
                <legend>{pick("Assignees * (cases are distributed evenly)", "执行人 *（用例将按稳定顺序平均分配）")}</legend>
                {members.map((member) => (
                  <label key={member.account_id}>
                    <input
                      type="checkbox"
                      checked={selectedAssigneeIds.includes(member.account_id)}
                      onChange={(event) =>
                        setSelectedAssigneeIds((current) =>
                          event.target.checked
                            ? [...new Set([...current, member.account_id])]
                            : current.filter(
                                (item) => item !== member.account_id,
                              ),
                        )
                      }
                    />
                    <span>
                      <strong>{member.display_name}</strong>
                      <small>{member.email}</small>
                    </span>
                  </label>
                ))}
              </fieldset>
              {spaceRole === "owner" && (
                <div className="execution-member-manager">
                  <strong>{pick("Space members", "空间成员管理")}</strong>
                  <div>
                    <input
                      type="email"
                      value={memberEmail}
                      onChange={(event) => setMemberEmail(event.target.value)}
                      placeholder={pick("Enter a registered email", "输入已注册邮箱")}
                    />
                    <button
                      type="button"
                      disabled={!memberEmail.trim() || loading}
                      onClick={() => void addMember()}
                    >
                      {pick("Add member", "添加成员")}
                    </button>
                  </div>
                  {members
                    .filter((member) => member.role !== "owner")
                    .map((member) => (
                      <p key={member.account_id}>
                        <span>{member.display_name} · {member.email}</span>
                        <button
                          type="button"
                          onClick={() => void removeMember(member.account_id)}
                        >
                          {pick("Remove", "移除")}
                        </button>
                      </p>
                    ))}
                </div>
              )}
            </div>
            <button
              type="button"
              className="management-button management-button--primary"
              disabled={loading}
              onClick={() => void startRun()}
            >
              {loading ? (
                <LoaderCircle className="auth-spinner" size={16} />
              ) : (
                <ClipboardCheck size={16} />
              )}
              {pick("Create execution run", "创建执行任务")}
            </button>
          </section>
        </>
      )}

      {view === "detail" && run && (
        <>
          <header className="execution-header execution-header--detail">
            <div>
              <button
                type="button"
                className="execution-back"
                onClick={() => {
                  if (!confirmDiscardRecordDraft()) return;
                  discardRecordDraft();
                  setView("overview");
                  void refreshHistory();
                }}
              >
                <ArrowLeft size={15} /> {pick("Back to runs", "返回任务列表")}
              </button>
              <span className="management-kicker">{pick("QA EXECUTION", "QA 执行任务")}</span>
              <h1>{run.description}</h1>
              <p>
                {run.source_name} · {pick(`from ${run.source_collection_count} collections · ${run.records.length} cases`, `来自 ${run.source_collection_count} 个集合 · ${run.records.length} 条用例`)}
                {" · "}{runStatusLabel[run.status] ?? run.status}
                {" · "}{pick("Created by", "创建人")} {run.creator_name}
              </p>
            </div>
            <div className="execution-header__actions">
              <div className="execution-progress">
                <div>
                  <strong>{progress.percent}%</strong>
                  <span>{pick(`${progress.done} / ${progress.total} executed`, `${progress.done} / ${progress.total} 已执行`)}</span>
                </div>
                <span className="execution-progress__track">
                  <i style={{ width: `${progress.percent}%` }} />
                </span>
              </div>
              {!readOnly && run.can_manage && (
                <button
                  type="button"
                  className="management-button"
                  disabled={saving}
                  onClick={() => void finishRun()}
                >
                  <Square size={15} /> {pick("End run", "结束任务")}
                </button>
              )}
            </div>
          </header>

          <section className="execution-collaborators">
            <Users size={15} />
            <strong>{pick("Participants", "参与成员")}</strong>
            <span>
              {run.assignee_names.join("、")}
            </span>
            <small>{pick("Multi-user updates sync every 5 seconds", "多人更新每 5 秒自动同步")}</small>
          </section>

          {loading ? (
            <div className="management-loading">
              <LoaderCircle className="auth-spinner" size={22} />
              {pick("Loading execution run…", "正在加载执行任务…")}
            </div>
          ) : (
            <div className="execution-layout">
              <aside className="execution-queue">
                <div className="execution-queue__head">
                  <strong>{pick("Execution queue", "执行队列")}</strong>
                  <select
                    aria-label={pick("Filter by assignee", "按执行人筛选")}
                    value={recordFilter}
                    onChange={(event) => {
                      const value = event.target.value;
                      setRecordFilter(value);
                      const nextRecord =
                        value === "all"
                          ? run.records[0]
                          : value === "mine"
                            ? run.records.find(
                                (record) => record.assignee_id === accountId,
                              )
                            : run.records.find(
                                (record) =>
                                  record.assignee_id ===
                                  value.slice("assignee:".length),
                              );
                      if (nextRecord) {
                        setSelectedRecordId(nextRecord.id);
                        setRecordDraft(draftFromRecord(nextRecord));
                      }
                    }}
                  >
                    <option value="all">{pick(`All · ${run.records.length}`, `全部 · ${run.records.length}`)}</option>
                    <option value="mine">{pick("My cases", "我的用例")}</option>
                    {members.map((member) => (
                      <option
                        key={member.account_id}
                        value={`assignee:${member.account_id}`}
                      >
                        {member.display_name}
                      </option>
                    ))}
                  </select>
                  <span>{pick(`${filteredRecords.length} cases`, `${filteredRecords.length} 条`)}</span>
                </div>
                {filteredRecords.map((record, index) => (
                  <button
                    type="button"
                    key={record.id}
                    className={
                      record.id === selectedRecordId
                        ? "execution-queue__item is-active"
                        : "execution-queue__item"
                    }
                    onClick={() => selectExecutionRecord(record.id)}
                    aria-current={
                      record.id === selectedRecordId ? "true" : undefined
                    }
                    aria-label={`${String(index + 1).padStart(2, "0")} ${record.test_case.case_key} ${record.test_case.title} ${executionStatusLabel[record.status]}`}
                  >
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    <div>
                      <code>{record.test_case.case_key}</code>
                      <strong>{record.test_case.title}</strong>
                      {record.updated_by_name && (
                        <small>{pick(`Last updated by ${record.updated_by_name}`, `${record.updated_by_name} 最后更新`)}</small>
                      )}
                      <small>{pick("Assignee", "执行人")}：{record.assignee_name ?? pick("Unassigned", "未分配")}</small>
                    </div>
                    <span
                      className={`execution-queue__status execution-queue__status--${record.status}`}
                    >
                      <i aria-hidden="true" />
                      {executionStatusLabel[record.status]}
                    </span>
                  </button>
                ))}
              </aside>

              <section className="execution-case">
                {selectedRecord ? (
                  <>
                    <header className="execution-case__header">
                      <div>
                        <span className="management-kicker">
                          {selectedRecord.test_case.case_key} · {pick("Result in this run", "本任务执行结果")}
                        </span>
                        <h2>{selectedRecord.test_case.title}</h2>
                        <p>
                          {selectedRecord.test_case.module} ·{" "}
                          {selectedRecord.test_case.priority} · V
                          {selectedRecord.test_case.revision_number}
                          {selectedRecord.updated_by_name
                            ? pick(` · Last updated by ${selectedRecord.updated_by_name}`, ` · ${selectedRecord.updated_by_name} 最后更新`)
                            : ""}
                        </p>
                        {run.can_manage && !readOnly && (
                          <label className="execution-reassign">
                            {pick("Assignee", "执行人")}
                            <select
                              value={selectedRecord.assignee_id ?? ""}
                              onChange={(event) =>
                                void reassignRecord(
                                  selectedRecord.id,
                                  event.target.value,
                                )
                              }
                              disabled={saving}
                            >
                              {members.map((member) => (
                                <option
                                  key={member.account_id}
                                  value={member.account_id}
                                >
                                  {member.display_name}
                                </option>
                              ))}
                            </select>
                          </label>
                        )}
                      </div>
                      <div className="execution-status-actions">
                        {executionOptions.map((option) => {
                          const Icon = option.icon;
                          return (
                            <button
                              type="button"
                              key={option.value}
                              className={
                                recordDraft?.status === option.value
                                  ? `is-active execution-status--${option.value}`
                                  : ""
                              }
                              disabled={saving || recordReadOnly}
                              aria-pressed={recordDraft?.status === option.value}
                              onClick={() => {
                                setRecordDraft((current) => ({
                                  ...(current ?? draftFromRecord(selectedRecord)),
                                  status: option.value,
                                }));
                                setRecordValidationError("");
                              }}
                            >
                              <Icon size={15} /> {pick(option.en, option.zh)}
                            </button>
                          );
                        })}
                      </div>
                    </header>
                    {recordValidationError && (
                      <div className="execution-record-error" role="alert">
                        {recordValidationError}
                      </div>
                    )}

                    <section className="execution-preconditions">
                      <h3>{pick("Pre-run checks", "执行前确认")}</h3>
                      <ul>
                        {selectedRecord.test_case.preconditions.map((item) => (
                          <li key={item}><Check size={14} /> {item}</li>
                        ))}
                      </ul>
                    </section>

                    <section className="execution-steps">
                      <h3>
                        {pick("Execution steps", "执行步骤")}
                        <span>{pick("Optional; does not affect the result", "可选记录，不影响执行结果")}</span>
                      </h3>
                      {selectedRecord.test_case.steps.map((step, index) => {
                        const completed =
                          selectedRecord.completed_step_ids.includes(step.id);
                        return (
                          <article
                            className={completed ? "is-completed" : ""}
                            key={step.id}
                          >
                            <button
                              type="button"
                              className="execution-step-check"
                              disabled={saving || recordReadOnly}
                              onClick={() => {
                                const completedStepIds = completed
                                  ? selectedRecord.completed_step_ids.filter(
                                      (id) => id !== step.id,
                                    )
                                  : [
                                      ...selectedRecord.completed_step_ids,
                                      step.id,
                                    ];
                                void persistRecord(selectedRecord, {
                                  completed_step_ids: completedStepIds,
                                });
                              }}
                              aria-label={pick(`${completed ? "Unmark" : "Complete"} step ${index + 1}`, `${completed ? "取消完成" : "完成"}第 ${index + 1} 步`)}
                            >
                              {completed ? <Check size={15} /> : index + 1}
                            </button>
                            <div>
                              <strong>{step.action}</strong>
                              <p><span>{pick("Expected", "预期结果")}</span>{step.expected}</p>
                            </div>
                          </article>
                        );
                      })}
                    </section>

                    <ExecutionNotes
                      actualResult={recordDraft?.actualResult ?? ""}
                      defectRef={recordDraft?.defectRef ?? ""}
                      dirty={recordDraftDirty}
                      saving={saving}
                      readOnly={recordReadOnly}
                      readOnlyLabel={
                        readOnly ? pick("Run ended", "批次已结束") : pick("Only the assignee can edit", "仅当前执行人可编辑")
                      }
                      actualResultRef={actualResultRef}
                      onActualResultChange={(value) => {
                        setRecordDraft((current) => ({
                          ...(current ?? draftFromRecord(selectedRecord)),
                          actualResult: value,
                        }));
                        setRecordValidationError("");
                      }}
                      onDefectRefChange={(value) =>
                        setRecordDraft((current) => ({
                          ...(current ?? draftFromRecord(selectedRecord)),
                          defectRef: value,
                        }))
                      }
                      onSave={saveRecordDraft}
                    />
                  </>
                ) : (
                  <div className="management-empty management-empty--detail">
                    <ClipboardCheck size={28} />
                    <strong>{pick("This run has no cases", "当前执行任务中没有用例")}</strong>
                  </div>
                )}
              </section>
            </div>
          )}
        </>
      )}
    </div>
  );
}
