"use client";

import { CaseStatusBadge } from "@/components/case-status";
import type { CaseCollection } from "@/components/case-collections";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { TestCase } from "@/lib/mock-data";
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  Ban,
  Check,
  CheckCircle2,
  Clock3,
  Link2,
  ListChecks,
  Play,
  RotateCcw,
  ShieldAlert,
} from "lucide-react";
import { useMemo, useState } from "react";

export type ExecutionStatus = "未执行" | "通过" | "不通过" | "跳过" | "堵塞";

type ExecutionRecord = {
  status: ExecutionStatus;
  actualResult: string;
  defectId: string;
  completedStepIds: string[];
  updatedAt?: string;
};

type TestExecutionProps = {
  collectionId: string;
  collectionName: string;
  collections: CaseCollection[];
  testCases: TestCase[];
  onSelectCollection: (collectionId: string) => void;
};

const resultOptions: {
  status: Exclude<ExecutionStatus, "未执行">;
  label: string;
  icon: typeof CheckCircle2;
  tone: "passed" | "failed" | "skipped" | "blocked";
}[] = [
  { status: "通过", label: "标记通过", icon: CheckCircle2, tone: "passed" },
  { status: "不通过", label: "标记不通过", icon: AlertCircle, tone: "failed" },
  { status: "跳过", label: "本轮跳过", icon: Ban, tone: "skipped" },
  { status: "堵塞", label: "标记堵塞", icon: ShieldAlert, tone: "blocked" },
];

function createExecutionRecords(testCases: TestCase[]): Record<string, ExecutionRecord> {
  return Object.fromEntries(
    testCases.map((testCase) => [
      testCase.id,
      {
        status: "未执行" as const,
        actualResult: "",
        defectId: "",
        completedStepIds: [],
      },
    ]),
  );
}

function ExecutionStatusBadge({ status }: { status: ExecutionStatus }) {
  const tone = status === "未执行"
    ? "not-run"
    : resultOptions.find((item) => item.status === status)?.tone ?? "not-run";

  return (
    <span className={`execution-status execution-status--${tone}`}>
      <i aria-hidden="true" />
      {status}
    </span>
  );
}

export function TestExecution({
  collectionId,
  collectionName,
  collections,
  testCases,
  onSelectCollection,
}: TestExecutionProps) {
  const [selectedCaseId, setSelectedCaseId] = useState(testCases[0]?.id ?? "");
  const [records, setRecords] = useState<Record<string, ExecutionRecord>>(() =>
    createExecutionRecords(testCases),
  );
  const selectedIndex = Math.max(
    0,
    testCases.findIndex((testCase) => testCase.id === selectedCaseId),
  );
  const selectedCase = testCases[selectedIndex];
  const selectedRecord = selectedCase ? records[selectedCase.id] : undefined;
  const completedCount = Object.values(records).filter(
    (record) => record.status !== "未执行",
  ).length;
  const passedCount = Object.values(records).filter(
    (record) => record.status === "通过",
  ).length;
  const failedCount = Object.values(records).filter(
    (record) => record.status === "不通过",
  ).length;
  const blockedCount = Object.values(records).filter(
    (record) => record.status === "堵塞",
  ).length;
  const progress = testCases.length
    ? Math.round((completedCount / testCases.length) * 100)
    : 0;
  const statusCounts = useMemo(
    () =>
      Object.values(records).reduce<Record<ExecutionStatus, number>>(
        (counts, record) => ({
          ...counts,
          [record.status]: counts[record.status] + 1,
        }),
        { 未执行: 0, 通过: 0, 不通过: 0, 跳过: 0, 堵塞: 0 },
      ),
    [records],
  );

  const updateRecord = (caseId: string, patch: Partial<ExecutionRecord>) => {
    setRecords((current) => ({
      ...current,
      [caseId]: {
        ...current[caseId],
        ...patch,
      },
    }));
  };

  const markResult = (status: Exclude<ExecutionStatus, "未执行">) => {
    if (!selectedCase || !selectedRecord) return;
    updateRecord(selectedCase.id, {
      status,
      completedStepIds:
        status === "通过"
          ? selectedCase.steps.map((step) => step.id)
          : selectedRecord.completedStepIds,
      updatedAt: new Intl.DateTimeFormat("zh-CN", {
        hour: "2-digit",
        minute: "2-digit",
      }).format(new Date()),
    });
  };

  const resetResult = () => {
    if (!selectedCase) return;
    updateRecord(selectedCase.id, {
      status: "未执行",
      actualResult: "",
      defectId: "",
      completedStepIds: [],
      updatedAt: undefined,
    });
  };

  const toggleStep = (stepId: string) => {
    if (!selectedCase || !selectedRecord) return;
    const completedStepIds = selectedRecord.completedStepIds.includes(stepId)
      ? selectedRecord.completedStepIds.filter((id) => id !== stepId)
      : [...selectedRecord.completedStepIds, stepId];
    updateRecord(selectedCase.id, { completedStepIds });
  };

  const moveCase = (direction: -1 | 1) => {
    const nextIndex = selectedIndex + direction;
    const nextCase = testCases[nextIndex];
    if (nextCase) setSelectedCaseId(nextCase.id);
  };

  if (!selectedCase || !selectedRecord) {
    return (
      <section className="execution-page execution-page--empty">
        <div>
          <ListChecks size={28} />
          <h1>当前集合没有可执行用例</h1>
          <p>请切换用例集合，或先在工作台中生成并评审用例。</p>
          <Select value={collectionId} onValueChange={onSelectCollection}>
            <SelectTrigger aria-label="选择要执行的用例集合">
              <SelectValue placeholder="选择用例集合" />
            </SelectTrigger>
            <SelectContent>
              {collections.map((collection) => (
                <SelectItem value={collection.id} key={collection.id}>
                  {collection.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </section>
    );
  }

  return (
    <section className="execution-page">
      <header className="execution-header">
        <div>
          <span className="execution-eyebrow">
            <Play size={13} />
            TEST EXECUTION RUN
          </span>
          <h1>测试执行</h1>
          <p>加载已评审用例集合，逐条记录本次执行结果。</p>
        </div>
        <div className="execution-header__actions">
          <label>
            <span>执行用例集合</span>
            <Select value={collectionId} onValueChange={onSelectCollection}>
              <SelectTrigger aria-label="选择要执行的用例集合">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {collections.map((collection) => (
                  <SelectItem value={collection.id} key={collection.id}>
                    {collection.name} · {collection.count} 条
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
          <span className="execution-save-state" role="status">
            <Clock3 />
            页面内自动保存
          </span>
        </div>
      </header>

      <div className="execution-overview">
        <div className="execution-progress-card">
          <div>
            <span>当前进度</span>
            <strong>{progress}%</strong>
          </div>
          <i>
            <b style={{ width: `${progress}%` }} />
          </i>
          <p>
            <span>{collectionName}</span>
            <span>{completedCount} / {testCases.length} 已执行</span>
          </p>
        </div>
        <div className="execution-metric">
          <span className="execution-metric__icon execution-metric__icon--passed">
            <CheckCircle2 size={17} />
          </span>
          <strong>{passedCount}</strong>
          <small>通过</small>
        </div>
        <div className="execution-metric">
          <span className="execution-metric__icon execution-metric__icon--failed">
            <AlertCircle size={17} />
          </span>
          <strong>{failedCount}</strong>
          <small>不通过</small>
        </div>
        <div className="execution-metric">
          <span className="execution-metric__icon execution-metric__icon--blocked">
            <ShieldAlert size={17} />
          </span>
          <strong>{blockedCount}</strong>
          <small>堵塞</small>
        </div>
      </div>

      <div className="execution-layout">
        <aside className="execution-queue" aria-label="待执行用例列表">
          <header>
            <div>
              <strong>执行队列</strong>
              <span>{testCases.length} 条用例</span>
            </div>
            <span>{statusCounts["未执行"]} 条未执行</span>
          </header>
          <div className="execution-queue__list">
            {testCases.map((testCase, index) => {
              const record = records[testCase.id];
              return (
                <button
                  className={selectedCase.id === testCase.id ? "is-active" : ""}
                  type="button"
                  onClick={() => setSelectedCaseId(testCase.id)}
                  key={testCase.id}
                >
                  <span className="execution-queue__index">
                    {record.status === "通过" ? <Check size={14} /> : index + 1}
                  </span>
                  <span>
                    <small>{testCase.id} · {testCase.priority}</small>
                    <strong>{testCase.title}</strong>
                    <em>{testCase.module}</em>
                  </span>
                  <ExecutionStatusBadge status={record.status} />
                </button>
              );
            })}
          </div>
        </aside>

        <article className="execution-detail">
          <header className="execution-detail__header">
            <div>
              <span>{selectedCase.id} · {selectedCase.priority} · {selectedCase.type}</span>
              <h2>{selectedCase.title}</h2>
              <p>{selectedCase.module} · 来源：{selectedCase.source}</p>
            </div>
            <div>
              <span>用例状态</span>
              <CaseStatusBadge status={selectedCase.status} compact />
            </div>
          </header>

          <section className="execution-section">
            <header>
              <div>
                <strong>前置条件</strong>
                <span>{selectedCase.preconditions.length}</span>
              </div>
            </header>
            <ol className="execution-preconditions">
              {selectedCase.preconditions.map((item) => <li key={item}>{item}</li>)}
            </ol>
          </section>

          <section className="execution-section">
            <header>
              <div>
                <strong>执行步骤与校验点</strong>
                <span>{selectedCase.steps.length}</span>
              </div>
              <small>{selectedRecord.completedStepIds.length} / {selectedCase.steps.length} 已确认</small>
            </header>
            <div className="execution-steps">
              {selectedCase.steps.map((step, index) => {
                const checked = selectedRecord.completedStepIds.includes(step.id);
                return (
                  <label className={checked ? "is-checked" : ""} key={step.id}>
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleStep(step.id)}
                    />
                    <span className="execution-step__number">{index + 1}</span>
                    <span>
                      <strong>执行</strong>
                      <p>{step.action}</p>
                      <em>
                        <Check size={13} />
                        校验：{step.expected}
                      </em>
                    </span>
                  </label>
                );
              })}
            </div>
          </section>

          <section className="execution-section execution-result-panel">
            <header>
              <div>
                <strong>本次执行结果</strong>
                {selectedRecord.updatedAt && <span>已保存于 {selectedRecord.updatedAt}</span>}
              </div>
              <ExecutionStatusBadge status={selectedRecord.status} />
            </header>
            <div className="execution-result-actions">
              {resultOptions.map((option) => (
                <button
                  className={`execution-result-action execution-result-action--${option.tone} ${
                    selectedRecord.status === option.status ? "is-active" : ""
                  }`}
                  type="button"
                  aria-pressed={selectedRecord.status === option.status}
                  onClick={() => markResult(option.status)}
                  key={option.status}
                >
                  <option.icon size={17} />
                  {option.label}
                </button>
              ))}
            </div>
            <label className="execution-field">
              <span>实际结果与执行备注</span>
              <Textarea
                value={selectedRecord.actualResult}
                onChange={(event) =>
                  updateRecord(selectedCase.id, { actualResult: event.target.value })
                }
                placeholder="记录实际表现、关键数据或环境差异…"
              />
            </label>
            {(selectedRecord.status === "不通过" || selectedRecord.status === "堵塞") && (
              <label className="execution-field">
                <span>关联缺陷或阻塞项</span>
                <div className="execution-defect-field">
                  <Link2 size={15} />
                  <Input
                    value={selectedRecord.defectId}
                    onChange={(event) =>
                      updateRecord(selectedCase.id, { defectId: event.target.value })
                    }
                    placeholder="例如 BUG-1024 或缺陷链接"
                  />
                </div>
              </label>
            )}
          </section>

          <footer className="execution-detail__footer">
            <Button
              variant="ghost"
              type="button"
              onClick={resetResult}
              disabled={selectedRecord.status === "未执行"}
            >
              <RotateCcw />
              重置结果
            </Button>
            <div>
              <Button
                variant="outline"
                type="button"
                disabled={selectedIndex === 0}
                onClick={() => moveCase(-1)}
              >
                <ArrowLeft />
                上一条
              </Button>
              <Button
                type="button"
                disabled={selectedIndex === testCases.length - 1}
                onClick={() => moveCase(1)}
              >
                下一条
                <ArrowRight />
              </Button>
            </div>
          </footer>
        </article>
      </div>
    </section>
  );
}
