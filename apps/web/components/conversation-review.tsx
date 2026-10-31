"use client";

import type { CaseChangeSetDto } from "@/lib/casepilot-api";
import { reviewableChangeRefs, selectedReviewFields } from "@/lib/workbench-review";
import { useI18n } from "@/lib/i18n";

/** Exact current proposal, not a natural-language approval or inferred scope. */
export function ConversationReview({ changeSet, selection, busy, onApply, onInspect }: {
  changeSet: CaseChangeSetDto; selection: Record<string, string[]>; busy: boolean;
  onApply: () => Promise<void>; onInspect: () => void;
}) {
  const { pick } = useI18n();
  const fields = selectedReviewFields(changeSet, selection);
  const refs = reviewableChangeRefs(changeSet);
  const selected = Object.entries(fields).filter(([, values]) => values.length);
  if (!refs.length) return null;
  return <details className="conversation-review">
    <summary>{pick("Review this proposal in chat", "在对话中审阅这版变更")} · {selected.length}/{refs.length}</summary>
    <p>{changeSet.instruction}</p>
    <small>{pick("Shares the result pane’s field selection. Unselected pending cases are rejected when you confirm. Formal revisions are checked by the server.", "与结果面板共享字段选择；确认时，未选择字段的待审阅用例将被拒绝。服务器会校验正式用例版本。")}</small>
    <div className="conversation-review__items">{changeSet.items.filter(item => refs.includes(item.ref)).map(item => <details key={item.ref}>
      <summary>{String(item.base_snapshot.case_key ?? item.proposed_snapshot.case_key ?? "")} · {String(item.proposed_snapshot.title ?? item.base_snapshot.title ?? item.ref)} · V{item.proposal_version ?? 1}</summary>
      {item.field_diff.filter(diff => fields[item.ref]?.includes(diff.field)).map(diff => <div key={diff.field} className="conversation-review__diff"><strong>{diff.field}</strong><del>{typeof diff.before === "string" ? diff.before : JSON.stringify(diff.before)}</del><ins>{typeof diff.after === "string" ? diff.after : JSON.stringify(diff.after)}</ins></div>)}
      {!fields[item.ref]?.length && <p>{pick("No fields selected: reject this proposal for this case.", "未选择字段：本条用例的建议将被拒绝。")}</p>}
    </details>)}</div>
    <div className="conversation-review__actions"><button type="button" onClick={onInspect}>{pick("Adjust field selection", "调整字段选择")}</button><button type="button" disabled={busy} onClick={() => void onApply()}>{pick(`Confirm these ${refs.length} review decisions`, `确认这 ${refs.length} 条审阅决定`)}</button></div>
  </details>;
}
