"use client";

import type { CaseChangeSetDto, TestCaseDto } from "@/lib/casepilot-api";
import { useI18n } from "@/lib/i18n";

type Props = {
  cases: TestCaseDto[];
  changeSet: CaseChangeSetDto;
  acceptedFields: Record<string, string[]>;
  busy: boolean;
  onToggleField: (ref: string, field: string) => void;
  onApply: () => Promise<void>;
  onReject: () => Promise<void>;
};

export function CaseCollectionChanges({ cases, changeSet, acceptedFields, busy, onToggleField, onApply, onReject }: Props) {
  const { pick } = useI18n();
  const readOnly = changeSet.status !== "ready";
  const isDeleteChange = Boolean(changeSet?.items.some((item) => item.operation === "delete"));

  return (
    <section className="collection-changes collection-changes--inline" aria-label={pick("Review pending case changes", "审阅待确认用例变更")}>
      <div className="collection-changes__heading"><strong>{readOnly ? pick("Change result", "变更结果") : pick("Pending changes", "待确认变更")}</strong><span className="collection-changes__badge">{changeSet.status === "no_changes" ? pick("No changes needed", "无需修改") : changeSet.status === "applied" ? pick("Applied", "已应用") : changeSet.status === "rejected" ? pick("Not applied", "未应用") : changeSet.status === "conflict" ? pick("Version conflict", "版本冲突") : pick("Pending confirmation", "待确认")}</span></div>
      {changeSet.status === "conflict" && <p role="alert">{pick("Cases changed after this proposal was created. Start a new rewrite using current versions.", "用例在方案生成后发生了变化，请基于最新版本重新发起改写。")}</p>}
      {changeSet && (
        <div className="collection-changes__review">
          <div><strong>{isDeleteChange ? pick("Deletion review", "删除审阅") : pick("Edit review", "修改审阅")}</strong><span>{pick(`${changeSet.items.length} affected cases`, `涉及 ${changeSet.items.length} 条用例`)}</span></div>
          <p>{readOnly ? pick("Saved proposal and processing record. Historical results cannot be applied again.", "以下为保存的变更方案与处理记录，历史结果不可重复应用。") : pick("Check each field before applying. Unchecked changes will be kept as they are.", "请逐项检查；未勾选的变更不会应用。")}</p>
          <div className="collection-changes__items">{changeSet.items.map((item) => (
            <details key={item.ref} open={isDeleteChange || changeSet.items.length === 1}>
              <summary>{String(item.base_snapshot.case_key ?? cases.find((testCase) => testCase.id === item.ref)?.case_key ?? item.ref)} · {String(item.base_snapshot.title ?? "")}</summary>
              {item.reason && <p>{item.reason}</p>}
              {!item.field_diff.length && <p>{pick("No changes needed for this case.", "此用例无需修改。")}</p>}
              {item.field_diff.map((diff) => (
                <div className="collection-changes__field" key={diff.field}>
                  <label><input type="checkbox" disabled={busy || readOnly} checked={readOnly ? item.status === "applied" && (!item.accepted_fields || item.accepted_fields.includes(diff.field)) : acceptedFields[item.ref]?.includes(diff.field) ?? false} onChange={() => onToggleField(item.ref, diff.field)} />{diff.field === "delete" ? pick("Soft delete this case", "软删除此用例") : diff.field}</label>
                  {diff.field !== "delete" && <div className="collection-changes__comparison"><div><small>{pick("Before", "原内容")}</small><pre>{formatValue(diff.before)}</pre></div><div><small>{pick("After", "修改后")}</small><pre>{formatValue(diff.after)}</pre></div></div>}
                </div>
              ))}
            </details>
          ))}</div>
          {!readOnly && <div className="collection-changes__actions"><button type="button" disabled={busy} onClick={() => void onReject()}>{pick("Cancel changes", "取消变更")}</button><button type="button" className={isDeleteChange ? "is-danger" : "is-primary"} disabled={busy || !changeSet.items.some((item) => (acceptedFields[item.ref] ?? []).length > 0)} onClick={() => void onApply()}>{isDeleteChange ? pick("Apply selected deletions", "确认删除已选用例") : pick("Apply selected changes", "应用已选修改")}</button></div>}
        </div>
      )}
    </section>
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
