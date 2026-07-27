"use client";

import { ExecutionNotes } from "@/components/execution-notes";
import {
  closeExecutionRun,
  createExecutionRun,
  getExecutionRun,
  listSpaceExecutionRuns,
  updateExecutionRecord,
  type CaseCollectionDto,
  type ExecutionRecordDto,
  type ExecutionRunDto,
  type ExecutionRunSummaryDto,
  type ExecutionStatusApi,
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
  collections: CaseCollectionDto[];
  preferredCollectionId: string;
  navigationRequest: {
    id: number;
    mode: "overview" | "create";
  };
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
  collections,
  preferredCollectionId,
  navigationRequest,
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
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const descriptionRef = useRef<HTMLTextAreaElement>(null);
  const activeRunId = run?.id;

  const refreshHistory = async () => {
    setRunHistory(await listSpaceExecutionRuns(spaceId));
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
              caught instanceof Error ? caught.message : "执行任务加载失败",
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
    if (navigationRequest.id === 0) return;
    const timer = window.setTimeout(() => {
      if (navigationRequest.mode === "create") {
        setSelectedCollectionId(
          preferredCollectionId || collections[0]?.id || "",
        );
        setDescriptionError("");
        setView("create");
      } else {
        setRun(null);
        setSelectedRecordId("");
        setView("overview");
      }
    });
    return () => window.clearTimeout(timer);
  }, [collections, navigationRequest, preferredCollectionId]);

  useEffect(() => {
    if (view !== "detail" || !activeRunId || saving) return;
    const timer = window.setInterval(() => {
      void getExecutionRun(activeRunId).then(setRun).catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [activeRunId, saving, view]);

  const readOnly = run?.status !== "active";
  const selectedRecord =
    run?.records.find((record) => record.id === selectedRecordId) ?? null;

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
    setLoading(true);
    setError("");
    setDescriptionError("");
    try {
      const result = await createExecutionRun(selectedCollectionId, {
        description: description.trim(),
      });
      setRun(result);
      setSelectedRecordId(result.records[0]?.id ?? "");
      setDescription("");
      setView("detail");
      await refreshHistory();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "执行任务创建失败");
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
      setView("detail");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "执行任务加载失败");
    } finally {
      setLoading(false);
    }
  };

  const finishRun = async () => {
    if (!run || readOnly) return;
    setSaving(true);
    setError("");
    try {
      const result = await closeExecutionRun(run.id, "completed");
      setRun(result);
      await refreshHistory();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "执行任务结束失败");
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
  ) => {
    if (readOnly) return;
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
      await refreshHistory();
    } catch (caught) {
      if (caught instanceof Error && caught.message === "execution_record_changed") {
        if (run) {
          const latestRun = await getExecutionRun(run.id);
          setRun(latestRun);
        }
        setError("该用例刚被其他成员更新，已为你加载最新结果，请确认后重试。");
      } else {
        setError(caught instanceof Error ? caught.message : "执行记录保存失败");
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="execution-workspace">
      {error && <div className="management-banner-error">{error}</div>}

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
          <header className="execution-header">
            <div>
              <button
                type="button"
                className="execution-back"
                onClick={() => {
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
              {!readOnly && (
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
              {run.contributor_names.length
                ? run.contributor_names.join("、")
                : run.creator_name}
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
                  <span>{run.records.length} 条</span>
                </div>
                {run.records.map((record, index) => (
                  <button
                    type="button"
                    key={record.id}
                    className={
                      record.id === selectedRecordId
                        ? "execution-queue__item is-active"
                        : "execution-queue__item"
                    }
                    onClick={() => setSelectedRecordId(record.id)}
                  >
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    <div>
                      <code>{record.test_case.case_key}</code>
                      <strong>{record.test_case.title}</strong>
                      {record.updated_by_name && (
                        <small>{record.updated_by_name} 最后更新</small>
                      )}
                    </div>
                    <i
                      className={`execution-dot execution-dot--${record.status}`}
                    />
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
                      </div>
                      <div className="execution-status-actions">
                        {executionOptions.map((option) => {
                          const Icon = option.icon;
                          return (
                            <button
                              type="button"
                              key={option.value}
                              className={
                                selectedRecord.status === option.value
                                  ? `is-active execution-status--${option.value}`
                                  : ""
                              }
                              disabled={saving || readOnly}
                              onClick={() => {
                                const completedStepIds =
                                  option.value === "passed"
                                    ? selectedRecord.test_case.steps.map(
                                        (step) => step.id,
                                      )
                                    : selectedRecord.completed_step_ids;
                                void persistRecord(selectedRecord, {
                                  status: option.value,
                                  completed_step_ids: completedStepIds,
                                });
                              }}
                            >
                              <Icon size={15} /> {option.label}
                            </button>
                          );
                        })}
                      </div>
                    </header>

                    <section className="execution-preconditions">
                      <h3>执行前确认</h3>
                      <ul>
                        {selectedRecord.test_case.preconditions.map((item) => (
                          <li key={item}><Check size={14} /> {item}</li>
                        ))}
                      </ul>
                    </section>

                    <section className="execution-steps">
                      <h3>执行步骤</h3>
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
                              disabled={saving || readOnly}
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
                      key={`${selectedRecord.id}-${selectedRecord.updated_at}`}
                      record={selectedRecord}
                      saving={saving}
                      readOnly={readOnly}
                      onSave={(input) => persistRecord(selectedRecord, input)}
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
