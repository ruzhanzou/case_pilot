"use client";

import type { CaseChangeSetDto, ConversationOperationPlanDto, TestCaseDto } from "@/lib/casepilot-api";
import { useI18n } from "@/lib/i18n";

type Props = {
  cases: TestCaseDto[];
  operations: ConversationOperationPlanDto | null;
  phase: string;
  candidateCount: number;
  includedCount: number;
  selectedCase: TestCaseDto | null;
  changeSet: CaseChangeSetDto | null;
  acceptedFields: Record<string, string[]>;
  busy: boolean;
  onCreate: () => void;
  onViewBrief: () => void;
  onViewCandidates: () => void;
  onCommitCandidates: () => Promise<void>;
  onEdit: (testCase: TestCaseDto) => void;
  onPrepareDelete: (caseIds: string[]) => Promise<void>;
  onToggleField: (ref: string, field: string) => void;
  onApply: () => Promise<void>;
  onReject: () => Promise<void>;
};

const kinds = ["CASE_GENERATE", "CASE_MODIFY", "CASE_DELETE"] as const;

export function CaseCollectionChanges({ cases, operations, phase, candidateCount, includedCount, selectedCase, changeSet, acceptedFields, busy, onCreate, onViewBrief, onViewCandidates, onCommitCandidates, onEdit, onPrepareDelete, onToggleField, onApply, onReject }: Props) {
  const { pick } = useI18n();
  const operationByKind = Object.fromEntries(kinds.map((kind) => [kind, operations?.operations.findLast((item) => item.intent === kind)]));
  const isDeleteChange = Boolean(changeSet?.items.some((item) => item.operation === "delete"));
  const operationStatus = (status: string) => ({
    queued: pick("Queued", "排队中"), running: pick("In progress", "处理中"),
    awaiting_confirmation: pick("Awaiting review", "待审阅"),
    awaiting_target: pick("Select cases", "待选择用例"),
    awaiting_intent: pick("Confirm intent", "待确认意图"),
    completed: pick("Completed", "已完成"), failed: pick("Failed", "失败"),
    cancelled: pick("Cancelled", "已取消"), skipped: pick("Skipped", "已跳过"),
  }[status] ?? status);

  return (
    <details key={`${changeSet?.id ?? "none"}:${phase}`} open={Boolean(changeSet) || phase === "candidate_review"} className="collection-changes" aria-label={pick("Collection changes", "集合变更")}>
      <summary className="collection-changes__heading">
        <div><strong>{pick("Collection changes", "集合变更")}</strong><span>{pick("Create, edit, and delete cases in this workspace", "在工作区处理用例的新增、修改和删除")}</span></div>
        {changeSet && <span className="collection-changes__badge">{pick("Pending confirmation", "待确认")}</span>}
      </summary>
      <div className="collection-changes__cards">
        <div>
          <strong>{pick("Add", "新增")}</strong>
          <small>{operationByKind.CASE_GENERATE ? pick(`Request: ${operationStatus(operationByKind.CASE_GENERATE.status)}`, `请求状态：${operationStatus(operationByKind.CASE_GENERATE.status)}`) : pick("New or generated cases", "新建或生成用例")}</small>
          {phase === "candidate_review" ? <>
            <p>{pick(`${includedCount} of ${candidateCount} candidates selected`, `已选择 ${includedCount} / ${candidateCount} 条候选用例`)}</p>
            <div><button type="button" onClick={onViewCandidates}>{pick("Review candidates", "审阅候选")}</button><button type="button" className="is-primary" disabled={!includedCount || busy} onClick={() => void onCommitCandidates()}>{pick("Add selected", "纳入已选用例")}</button></div>
          </> : <div><button type="button" disabled={busy || !["maintenance", "idle"].includes(phase)} onClick={onCreate}>{pick("New case", "新建用例")}</button>{["brief_review", "generating"].includes(phase) && <button type="button" onClick={onViewBrief}>{pick("View generation brief", "查看生成说明")}</button>}</div>}
        </div>
        <div>
          <strong>{pick("Edit", "修改")}</strong>
          <small>{operationByKind.CASE_MODIFY ? pick(`Request: ${operationStatus(operationByKind.CASE_MODIFY.status)}`, `请求状态：${operationStatus(operationByKind.CASE_MODIFY.status)}`) : pick("Edit the selected official case", "修改选中的正式用例")}</small>
          <p>{selectedCase?.case_key ?? pick("Select a case first", "请先选择用例")}</p>
          <button type="button" disabled={!selectedCase || phase !== "maintenance" || busy} onClick={() => selectedCase && onEdit(selectedCase)}>{pick("Edit selected case", "编辑选中用例")}</button>
        </div>
        <div>
          <strong>{pick("Delete", "删除")}</strong>
          <small>{operationByKind.CASE_DELETE ? pick(`Request: ${operationStatus(operationByKind.CASE_DELETE.status)}`, `请求状态：${operationStatus(operationByKind.CASE_DELETE.status)}`) : pick("Deletion requires a separate review", "删除需单独审阅确认")}</small>
          <p>{selectedCase?.case_key ?? pick("Select a case first", "请先选择用例")}</p>
          <button type="button" disabled={!selectedCase || phase !== "maintenance" || busy || Boolean(changeSet)} onClick={() => selectedCase && void onPrepareDelete([selectedCase.id])}>{pick("Review deletion", "审阅删除")}</button>
        </div>
      </div>
      {changeSet?.status === "ready" && (
        <div className="collection-changes__review">
          <div><strong>{isDeleteChange ? pick("Deletion review", "删除审阅") : pick("Edit review", "修改审阅")}</strong><span>{pick(`${changeSet.items.length} affected cases`, `涉及 ${changeSet.items.length} 条用例`)}</span></div>
          <p>{pick("Check each field before applying. Unchecked changes will be kept as they are.", "请逐项检查；未勾选的变更不会应用。")}</p>
          <div className="collection-changes__items">{changeSet.items.map((item) => (
            <details key={item.ref} open={isDeleteChange || changeSet.items.length === 1}>
              <summary>{String(item.base_snapshot.case_key ?? cases.find((testCase) => testCase.id === item.ref)?.case_key ?? item.ref)} · {String(item.base_snapshot.title ?? "")}</summary>
              {item.field_diff.map((diff) => (
                <div className="collection-changes__field" key={diff.field}>
                  <label><input type="checkbox" disabled={busy} checked={acceptedFields[item.ref]?.includes(diff.field) ?? false} onChange={() => onToggleField(item.ref, diff.field)} />{diff.field === "delete" ? pick("Soft delete this case", "软删除此用例") : diff.field}</label>
                  {diff.field !== "delete" && <div className="collection-changes__comparison"><div><small>{pick("Before", "原内容")}</small><pre>{formatValue(diff.before)}</pre></div><div><small>{pick("After", "修改后")}</small><pre>{formatValue(diff.after)}</pre></div></div>}
                </div>
              ))}
            </details>
          ))}</div>
          <div className="collection-changes__actions"><button type="button" disabled={busy} onClick={() => void onReject()}>{pick("Cancel changes", "取消变更")}</button><button type="button" className={isDeleteChange ? "is-danger" : "is-primary"} disabled={busy || !changeSet.items.some((item) => (acceptedFields[item.ref] ?? []).length > 0)} onClick={() => void onApply()}>{isDeleteChange ? pick("Apply selected deletions", "确认删除已选用例") : pick("Apply selected changes", "应用已选修改")}</button></div>
        </div>
      )}
    </details>
  );
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map((item, index) =>
    typeof item === "string"
      ? `${index + 1}. ${item}`
      : typeof item === "object" && item !== null && "action" in item
        ? `${index + 1}. ${String(item.action)}\n   → ${String("expected" in item ? item.expected : "")}`
        : `${index + 1}. ${JSON.stringify(item)}`,
  ).join("\n");
  return JSON.stringify(value, null, 2);
}
