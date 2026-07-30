"use client";

import { ExecutionNotes } from "@/components/execution-notes";
import {
  closeExecutionRun,
  addSpaceMember,
  createExecutionRun,
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
  type SpaceMemberDto,
} from "@/lib/casepilot-api";
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
  onDirtyChange?: (dirty: boolean) => void;
};

type ExecutionView = "overview" | "create" | "detail";

const executionOptions: {
  value: ExecutionStatusApi;
  label: string;
  icon: typeof Circle;
}[] = [
  { value: "not_run", label: "未执行", icon: Circle },
  { value: "passed", label: "通过", icon: CheckCircle2 },
  { value: "failed", label: "不通过", icon: XCircle },
  { value: "skipped", label: "跳过", icon: SkipForward },
  { value: "blocked", label: "堵塞", icon: AlertTriangle },
];

const runStatusLabel: Record<string, string> = {
  active: "执行中",
  completed: "已完成",
  aborted: "已终止",
};

const executionStatusLabel: Record<ExecutionStatusApi, string> = {
  not_run: "未执行",
  passed: "通过",
  failed: "不通过",
  skipped: "跳过",
  blocked: "堵塞",
};

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

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
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
  onDirtyChange,
}: ExecutionWorkspaceProps) {
  const [view, setView] = useState<ExecutionView>("overview");
  const [run, setRun] = useState<ExecutionRunDto | null>(null);
  const [runHistory, setRunHistory] = useState<ExecutionRunSummaryDto[]>([]);
  const [selectedRecordId, setSelectedRecordId] = useState("");
  const [selectedCollectionId, setSelectedCollectionId] = useState(
    preferredCollectionId,
  );
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
    setRunHistory(await listSpaceExecutionRuns(spaceId));
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
          if (!ignored) setRunHistory(items);
        })
        .catch((caught) => {
          if (!ignored) {
            setError(
              caught instanceof Error
                ? publicErrorMessage(caught.message)
                : "执行任务加载失败",
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
  }, [spaceId]);

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
              : "空间成员加载失败",
          );
        }
      });
    return () => {
      ignored = true;
    };
  }, [spaceId]);

  useEffect(() => {
    if (navigationRequest.id === 0) return;
    const timer = window.setTimeout(() => {
      if (navigationRequest.mode === "create") {
        setRun(null);
        setSelectedRecordId("");
        setRecordDraft(null);
        setSelectedCollectionId(
          preferredCollectionId || collections[0]?.id || "",
        );
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
    if (!selectedCollectionId) {
      setError("当前没有可执行的用例集合，请先创建用例集合。");
      return;
    }
    if (!description.trim()) {
      setDescriptionError("请填写本次执行任务的目标或范围。");
      descriptionRef.current?.focus();
      return;
    }
    const selectedCollection = collections.find(
      (collection) => collection.id === selectedCollectionId,
    );
    if (!selectedCollection?.case_count) {
      setError("空用例集合不能创建执行任务。");
      return;
    }
    if (!selectedAssigneeIds.length) {
      setError("请至少选择一名执行人。");
      return;
    }
    setLoading(true);
    setError("");
    setDescriptionError("");
    try {
      const result = await createExecutionRun(selectedCollectionId, {
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
          : "执行任务创建失败",
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
          : "执行任务加载失败",
      );
    } finally {
      setLoading(false);
    }
  };

  const finishRun = async () => {
    if (!run || readOnly || !run.can_manage) return;
    if (recordDraftDirty) {
      setRecordValidationError("请先保存或放弃当前用例的执行记录，再结束任务。");
      return;
    }
    const remaining = progress.total - progress.done;
    const message = remaining
      ? `仍有 ${remaining} 条用例未执行。确认结束后任务将变为只读，是否继续？`
      : "结束后任务将变为只读，无法继续修改执行结果。确认结束任务吗？";
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
          : "执行任务结束失败",
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
        setError("该用例刚被其他成员更新，已为你加载最新结果，请确认后重试。");
      } else {
        setError(
          caught instanceof Error
            ? publicErrorMessage(caught.message)
            : "执行记录保存失败",
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
    window.confirm("当前执行结果尚未保存，离开将丢失这些修改。是否继续？");

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
          ? "标记不通过时必须填写实际结果。"
          : recordDraft.status === "skipped"
            ? "标记跳过时必须填写跳过原因。"
            : "标记堵塞时必须填写原因、依赖和解除条件。",
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
          : "成员添加失败",
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
          : "成员移除失败",
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
          : "重新分配失败",
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

      {view === "overview" && (
        <>
          <header className="execution-header execution-header--overview">
            <div>
              <span className="management-kicker">QA 执行任务</span>
              <h1>执行任务</h1>
              <p>查看所有任务的实时进度、执行结果和参与成员。</p>
            </div>
            <button
              type="button"
              className="management-button management-button--primary"
              onClick={() => {
                setSelectedCollectionId(
                  preferredCollectionId || collections[0]?.id || "",
                );
                setView("create");
              }}
            >
              <Plus size={16} /> 新建执行任务
            </button>
          </header>

          <section className="execution-overview-metrics">
            <article>
              <History size={18} />
              <div><strong>{overviewStats.total}</strong><span>全部任务</span></div>
            </article>
            <article>
              <Clock3 size={18} />
              <div><strong>{overviewStats.active}</strong><span>执行中</span></div>
            </article>
            <article>
              <CheckCircle2 size={18} />
              <div><strong>{overviewStats.completed}</strong><span>已完成</span></div>
            </article>
            <article>
              <Users size={18} />
              <div><strong>{overviewStats.contributors}</strong><span>参与成员</span></div>
            </article>
          </section>

          <section className="execution-task-list">
            <div className="execution-task-list__head">
              <div>
                <strong>任务历史</strong>
                <span>每 5 秒自动同步多人执行进度</span>
              </div>
              <span>{runHistory.length} 个任务</span>
            </div>
            {runHistory.length === 0 ? (
              <div className="management-empty management-empty--detail">
                <ClipboardCheck size={30} />
                <strong>暂无执行任务</strong>
                <span>创建任务后即可邀请空间成员共同执行</span>
              </div>
            ) : (
              <div className="execution-task-grid">
                {runHistory.map((item) => {
                  const done = item.total_count - item.not_run_count;
                  const percent = item.total_count
                    ? Math.round((done / item.total_count) * 100)
                    : 0;
                  return (
                    <button
                      type="button"
                      key={item.id}
                      onClick={() => void openRun(item.id)}
                    >
                      <div className="execution-task-card__top">
                        <span
                          className={`execution-task-status execution-task-status--${item.status}`}
                        >
                          {runStatusLabel[item.status] ?? item.status}
                        </span>
                        <small>{formatTime(item.last_activity_at)} 更新</small>
                      </div>
                      <strong>{item.description}</strong>
                      <span>{item.collection_name}</span>
                      <div className="execution-task-card__progress">
                        <div>
                          <b>{percent}%</b>
                          <span>{done} / {item.total_count} 已执行</span>
                        </div>
                        <i><em style={{ width: `${percent}%` }} /></i>
                      </div>
                      <div className="execution-task-card__results">
                        <span>{item.passed_count} 通过</span>
                        <span>{item.failed_count} 不通过</span>
                        <span>{item.blocked_count} 堵塞</span>
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
                <ArrowLeft size={15} /> 返回任务列表
              </button>
              <span className="management-kicker">新建执行任务</span>
              <h1>创建多人执行任务</h1>
              <p>选择用例集合并填写任务描述，空间成员可共同执行。</p>
            </div>
          </header>
          <section className="execution-run-setup">
            <div>
              <span className="management-kicker">任务设置</span>
              <h2>填写执行任务说明</h2>
              <p>创建时冻结当前用例修订；后续修改用例不会改变本任务记录。</p>
            </div>
            <div className="execution-run-setup__fields">
              <label>
                用例集合 *
                <select
                  value={selectedCollectionId}
                  onChange={(event) =>
                    setSelectedCollectionId(event.target.value)
                  }
                >
                  {collections.map((collection) => (
                    <option value={collection.id} key={collection.id}>
                      {collection.name} · {collection.case_count} 条用例
                    </option>
                  ))}
                </select>
              </label>
              <label>
                任务描述 *
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
                  placeholder="例如：验证 Audio Feature 录音、转写与中断恢复主流程"
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
                <legend>执行人 *（用例将按稳定顺序平均分配）</legend>
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
                  <strong>空间成员管理</strong>
                  <div>
                    <input
                      type="email"
                      value={memberEmail}
                      onChange={(event) => setMemberEmail(event.target.value)}
                      placeholder="输入已注册邮箱"
                    />
                    <button
                      type="button"
                      disabled={!memberEmail.trim() || loading}
                      onClick={() => void addMember()}
                    >
                      添加成员
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
                          移除
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
              创建执行任务
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
                <ArrowLeft size={15} /> 返回任务列表
              </button>
              <span className="management-kicker">QA 执行任务</span>
              <h1>{run.description}</h1>
              <p>
                {run.collection_name} · {runStatusLabel[run.status] ?? run.status}
                {" · "}创建人 {run.creator_name}
              </p>
            </div>
            <div className="execution-header__actions">
              <div className="execution-progress">
                <div>
                  <strong>{progress.percent}%</strong>
                  <span>{progress.done} / {progress.total} 已执行</span>
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
                  <Square size={15} /> 结束任务
                </button>
              )}
            </div>
          </header>

          <section className="execution-collaborators">
            <Users size={15} />
            <strong>参与成员</strong>
            <span>
              {run.assignee_names.join("、")}
            </span>
            <small>多人更新每 5 秒自动同步</small>
          </section>

          {loading ? (
            <div className="management-loading">
              <LoaderCircle className="auth-spinner" size={22} />
              正在加载执行任务…
            </div>
          ) : (
            <div className="execution-layout">
              <aside className="execution-queue">
                <div className="execution-queue__head">
                  <strong>执行队列</strong>
                  <select
                    aria-label="按执行人筛选"
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
                    <option value="all">全部 · {run.records.length}</option>
                    <option value="mine">我的用例</option>
                    {members.map((member) => (
                      <option
                        key={member.account_id}
                        value={`assignee:${member.account_id}`}
                      >
                        {member.display_name}
                      </option>
                    ))}
                  </select>
                  <span>{filteredRecords.length} 条</span>
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
                        <small>{record.updated_by_name} 最后更新</small>
                      )}
                      <small>执行人：{record.assignee_name ?? "未分配"}</small>
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
                          {selectedRecord.test_case.case_key} · 本任务执行结果
                        </span>
                        <h2>{selectedRecord.test_case.title}</h2>
                        <p>
                          {selectedRecord.test_case.module} ·{" "}
                          {selectedRecord.test_case.priority} · V
                          {selectedRecord.test_case.revision_number}
                          {selectedRecord.updated_by_name
                            ? ` · ${selectedRecord.updated_by_name} 最后更新`
                            : ""}
                        </p>
                        {run.can_manage && !readOnly && (
                          <label className="execution-reassign">
                            执行人
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
                              <Icon size={15} /> {option.label}
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
                      <h3>执行前确认</h3>
                      <ul>
                        {selectedRecord.test_case.preconditions.map((item) => (
                          <li key={item}><Check size={14} /> {item}</li>
                        ))}
                      </ul>
                    </section>

                    <section className="execution-steps">
                      <h3>
                        执行步骤
                        <span>可选记录，不影响执行结果</span>
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
                              aria-label={`${completed ? "取消完成" : "完成"}第 ${index + 1} 步`}
                            >
                              {completed ? <Check size={15} /> : index + 1}
                            </button>
                            <div>
                              <strong>{step.action}</strong>
                              <p><span>预期结果</span>{step.expected}</p>
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
                        readOnly ? "批次已结束" : "仅当前执行人可编辑"
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
                    <strong>当前执行任务中没有用例</strong>
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
