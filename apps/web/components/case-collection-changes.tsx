"use client";

import { useState } from "react";
import type { CaseChangeSetDto, TestCaseDto } from "@/lib/casepilot-api";
import { useI18n } from "@/lib/i18n";

type Props = {
  cases: TestCaseDto[];
  changeSet: CaseChangeSetDto;
  acceptedFields: Record<string, string[]>;
  busy: boolean;
  onToggleField: (ref: string, field: string) => void;
  onSelectFields?: (selection: Record<string, string[]>) => void;
  onApply: () => Promise<void>;
  onAcceptAll?: () => Promise<void>;
  onReviewItem?: (ref: string, accept: boolean) => Promise<void>;
  onReject: () => Promise<void>;
  onRefine?: () => void;
  onCandidates?: () => void;
};

export function CaseCollectionChanges({ cases, changeSet, acceptedFields, busy, onToggleField, onSelectFields, onApply, onAcceptAll, onReviewItem, onReject, onRefine, onCandidates }: Props) {
  const { pick } = useI18n();
  const [comparePrevious, setComparePrevious] = useState(false);
  const [query, setQuery] = useState("");
  const filteredItems = changeSet.items.filter((item) => [item.base_snapshot.case_key,
    cases.find((testCase) => testCase.id === item.ref)?.case_key, item.ref,
    item.base_snapshot.title, item.proposed_snapshot.title, item.base_snapshot.module,
    item.proposed_snapshot.module].some((value) => String(value ?? "").toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())));
  const version = Math.max(1, ...changeSet.items.map((item) => item.proposal_version ?? 1));
  const hasPrevious = changeSet.items.some((item) => item.previous_snapshot);
  const readOnly = changeSet.status !== "ready";
  const isDeleteChange = Boolean(changeSet?.items.some((item) => item.operation === "delete"));
  const pendingItems = changeSet.items.filter((item) => !["applied", "rejected"].includes(item.status ?? ""));
  const reviewedCount = changeSet.items.length - pendingItems.length;
  const selectedItems = pendingItems.filter((item) => item.field_diff.some((diff) =>
    acceptedFields[item.ref]?.includes(diff.field)));
  const selectedCount = selectedItems.reduce((count, item) => count + item.field_diff.filter((diff) =>
    acceptedFields[item.ref]?.includes(diff.field)).length, 0);

  return (
    <section className="collection-changes collection-changes--inline" aria-label={pick("Review pending case changes", "审阅待确认用例变更")}>
      <div className="collection-changes__heading"><strong>{readOnly ? pick("Change result", "变更结果") : pick("Pending changes", "待确认变更")}</strong><span className="collection-changes__badge">{changeSet.status === "superseded" ? pick("Superseded", "已有新版本") : changeSet.status === "no_changes" ? pick("No changes needed", "无需修改") : changeSet.status === "applied" ? pick("Applied", "已应用") : changeSet.status === "rejected" ? pick("Not applied", "未应用") : changeSet.status === "conflict" ? pick("Version conflict", "版本冲突") : pick("Pending confirmation", "待确认")}</span></div>
      {changeSet.status === "conflict" && <p role="alert">{pick("Cases changed after this proposal was created. Start a new rewrite using current versions.", "用例在方案生成后发生了变化，请基于最新版本重新发起改写。")}</p>}
      {changeSet && (
        <div className="collection-changes__review">
          <div><strong>{isDeleteChange ? pick("Deletion review", "删除审阅") : pick("Edit review", "修改审阅")}</strong><span>{pick(`${changeSet.items.length} affected cases`, `涉及 ${changeSet.items.length} 条用例`)}</span></div>
          {!isDeleteChange && <p>{pick(`Proposal V${version}`, `修改方案 V${version}`)} · {pick("Changes remain drafts until applied.", "确认应用前，原用例保持不变。")}</p>}
          {changeSet.items.some((item) => item.target_type === "candidate") && <p>{pick("Candidate changes stay in review. Add the reviewed candidates separately to save official cases.", "候选修改后仍待审阅；只有另行确认纳入，才会创建正式用例。")}</p>}
          {hasPrevious && <div className="collection-changes__actions"><button type="button" aria-pressed={!comparePrevious} onClick={() => setComparePrevious(false)}>{pick("All pending changes", "累计待应用变化")}</button><button type="button" aria-pressed={comparePrevious} onClick={() => setComparePrevious(true)}>{pick("Changes since previous proposal", "相对上一版变化")}</button></div>}
          <p>{readOnly ? pick("Saved proposal and processing record. Historical results cannot be applied again.", "以下为保存的变更方案与处理记录，历史结果不可重复应用。") : pick("Check each field before applying. Unchecked changes will be kept as they are.", "请逐项检查；未勾选的变更不会应用。")}</p>
          {!readOnly && !isDeleteChange && onReviewItem && <p>{pick("Accept saves all suggestions for that case; discard keeps the original. For individual fields, use Apply selected changes.", "采纳此用例会保存该条的全部建议；丢弃保留原用例。仅需部分字段时，请勾选后使用“应用已选修改”。")}</p>}
          {!readOnly && <p role="status">{pick(`Selected ${selectedItems.length} of ${changeSet.items.length} cases · ${selectedCount} changes`, `已选 ${selectedItems.length}/${changeSet.items.length} 条用例 · ${selectedCount} 项变更`)}</p>}
          {reviewedCount > 0 && <p>{pick(`Accepted ${changeSet.items.filter(item => item.status === "applied").length} · Discarded ${changeSet.items.filter(item => item.status === "rejected").length} · Pending ${pendingItems.length}`, `已采纳 ${changeSet.items.filter(item => item.status === "applied").length} 条 · 已丢弃 ${changeSet.items.filter(item => item.status === "rejected").length} 条 · 待审阅 ${pendingItems.length} 条`)}</p>}
          {changeSet.items.length > 1 && <div className="collection-changes__actions">
            <input aria-label={pick("Find changes by case or module", "按编号、标题或模块查找变更")} placeholder={pick("Case number, title or module", "编号、标题或模块")} value={query} onChange={(event) => setQuery(event.target.value)} />
            <span>{pick(`${filteredItems.length} results`, `${filteredItems.length} 条匹配`)}</span>
            {!readOnly && !comparePrevious && onSelectFields && <>
              <button type="button" disabled={busy || !filteredItems.length} onClick={() => onSelectFields(Object.fromEntries(filteredItems.filter(item => !["applied", "rejected"].includes(item.status ?? "")).map((item) => [item.ref, item.field_diff.map((diff) => diff.field)])))}>{pick("Select matching changes", "选中匹配项的全部变更")}</button>
              <button type="button" disabled={busy || !filteredItems.length} onClick={() => onSelectFields(Object.fromEntries(filteredItems.filter(item => !["applied", "rejected"].includes(item.status ?? "")).map((item) => [item.ref, []])))}>{pick("Clear matching changes", "取消匹配项的全部变更")}</button>
            </>}
          </div>}
          {query && <p>{pick("Filtering does not change selections outside these results. Applying includes all selected changes.", "筛选不会取消其他用例的选择；确认时将应用所有已选变更。")}</p>}
          {!filteredItems.length && <p>{pick("No matching changes. Clear the search to see all cases.", "没有匹配的变更，清空搜索可查看全部用例。")}</p>}
          <div className="collection-changes__items">{filteredItems.map((item) => {
            const itemReadOnly = readOnly || ["applied", "rejected"].includes(item.status ?? "");
            const diffs = comparePrevious && item.previous_snapshot
              ? ["title", "module", "priority", "case_type", "tags", "preconditions", "steps", "source_refs"].filter((field) => JSON.stringify(item.previous_snapshot?.[field]) !== JSON.stringify(item.proposed_snapshot[field])).map((field) => ({ field, before: item.previous_snapshot?.[field], after: item.proposed_snapshot[field] }))
              : item.field_diff;
            return (
            <details key={item.ref} open={isDeleteChange || changeSet.items.length === 1}>
              <summary>{String(item.base_snapshot.case_key ?? cases.find((testCase) => testCase.id === item.ref)?.case_key ?? item.ref)} · {String(item.base_snapshot.title ?? "")}{item.status === "applied" ? pick(" · Accepted", " · 已采纳") : item.status === "rejected" ? pick(" · Discarded", " · 已丢弃") : ""}</summary>
              <p>{pick("Module", "所属模块")}：{String(item.base_snapshot.module ?? "—")} · {pick("Base version", "基准版本")} V{String(item.base_snapshot.revision_number ?? item.base_version ?? 1)}</p>
              {itemReadOnly && <p>{item.status === "applied" ? pick("Accepted — saved", "已采纳，已保存") : pick("Discarded — original kept", "已丢弃建议，原用例未改变")}</p>}
              {item.reason && <p>{item.reason}</p>}
              {!diffs.length && <p>{pick("No changes needed for this case.", "此用例无需修改。")}</p>}
              {diffs.map((diff) => (
                <div className="collection-changes__field" key={diff.field}>
                  <label><input type="checkbox" disabled={busy || itemReadOnly || comparePrevious} checked={itemReadOnly ? item.status === "applied" && (!item.accepted_fields || item.accepted_fields.includes(diff.field)) : acceptedFields[item.ref]?.includes(diff.field) ?? false} onChange={() => onToggleField(item.ref, diff.field)} />{diff.field === "delete" ? pick("Soft delete this case", "软删除此用例") : fieldLabel(diff.field, pick)}</label>
                  {diff.field !== "delete" && <div className="collection-changes__comparison"><div><small>{comparePrevious ? pick("Previous proposal", "上一版方案") : pick("Before", "原内容")}</small><ReviewValue value={diff.before} label={`${comparePrevious ? pick("Previous proposal", "上一版方案") : pick("Before", "原内容")} · ${fieldLabel(diff.field, pick)}`} /></div><div><small>{itemReadOnly ? item.status === "applied" && (!item.accepted_fields || item.accepted_fields.includes(diff.field)) ? pick("Applied result", "已应用结果") : pick("Unapplied suggestion", "未应用的建议") : pick("Proposed change", "建议修改后")}</small><ReviewValue value={diff.after} label={`${pick("Proposed content", "建议内容")} · ${fieldLabel(diff.field, pick)}`} /></div></div>}
                </div>
              ))}
              {!itemReadOnly && !isDeleteChange && !comparePrevious && onReviewItem && <div className="collection-changes__actions">
                <button type="button" disabled={busy || !item.field_diff.length} onClick={() => void onReviewItem(item.ref, true)}>{pick("Accept this case", "采纳此用例")}</button>
                <button type="button" disabled={busy} onClick={() => void onReviewItem(item.ref, false)}>{pick("Discard this suggestion", "丢弃此建议")}</button>
              </div>}
            </details>
          ); })}</div>
          {onCandidates && changeSet.status === "applied" && changeSet.items.some((item) => item.target_type === "candidate") && <button type="button" onClick={onCandidates}>{pick("View updated candidates", "查看更新后的候选")}</button>}
          {!isDeleteChange && onRefine && ["ready", "applied", "no_changes"].includes(changeSet.status) && <button type="button" disabled={busy || (!readOnly && reviewedCount > 0)} onClick={onRefine}>{pick("Refine this result", "继续调整这版结果")}</button>}
          {!readOnly && reviewedCount > 0 && <p>{pick("Finish reviewing the remaining cases before refining the saved result.", "请先处理剩余建议，再继续调整已保存的结果。")}</p>}
          {!readOnly && !isDeleteChange && !comparePrevious && onAcceptAll && <button type="button" className="is-primary" disabled={busy || !pendingItems.length} onClick={() => void onAcceptAll()}>{pick(`Accept all remaining (${pendingItems.length})`, `一键采纳全部待审阅用例（${pendingItems.length} 条）`)}</button>}
          {!readOnly && <div className="collection-changes__actions"><button type="button" disabled={busy} onClick={() => void onReject()}>{pick("Cancel changes", "取消变更")}</button>{comparePrevious ? <button type="button" onClick={() => setComparePrevious(false)}>{pick("Review all changes before applying", "返回累计变化并确认")}</button> : <button type="button" className={isDeleteChange ? "is-danger" : "is-primary"} disabled={busy || !selectedItems.length} onClick={() => void onApply()}>{isDeleteChange ? pick("Apply selected deletions", "确认删除已选用例") : pick("Apply selected changes", "应用已选修改")}</button>}</div>}
        </div>
      )}
    </section>
  );
}

function ReviewValue({ value, label }: { value: unknown; label: string }) {
  const { pick } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const text = formatValue(value);
  const long = text.length > 400 || text.split("\n").length > 6;
  return <>
    <pre role="region" aria-label={label} tabIndex={long ? 0 : undefined} style={expanded ? { maxHeight: "none" } : undefined}>{text}</pre>
    {long && <button type="button" aria-expanded={expanded} aria-label={`${expanded ? pick("Collapse content", "收起内容") : pick("Expand full content", "展开完整内容")} · ${label}`} onClick={() => setExpanded(!expanded)}>{expanded ? pick("Collapse content", "收起内容") : pick("Expand full content", "展开完整内容")}</button>}
  </>;
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

function fieldLabel(field: string, pick: (en: string, zh: string) => string): string {
  const labels: Record<string, [string, string]> = {
    title: ["Title", "标题"], module: ["Module", "所属模块"], priority: ["Priority", "优先级"],
    case_type: ["Case type", "用例类型"], tags: ["Tags", "标签"], preconditions: ["Preconditions", "前置条件"],
    steps: ["Steps and expected results", "操作步骤与预期结果"], source_refs: ["Sources", "需求依据"],
  };
  return labels[field] ? pick(...labels[field]) : field;
}
