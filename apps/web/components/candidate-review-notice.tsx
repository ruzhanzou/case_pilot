"use client";

import type { ConversationDto, WorkspaceCandidateDto } from "@/lib/casepilot-api";
import { candidateReviewGroups } from "@/lib/candidate-generation-review";
import { useI18n } from "@/lib/i18n";

/** Visible at every candidate-adoption entry, without introducing another workflow. */
export function CandidateReviewNotice({ conversation, candidates }: {
  conversation: Pick<ConversationDto, "generation_reviews" | "messages">;
  candidates: WorkspaceCandidateDto[];
}) {
  const { pick } = useI18n();
  const groups = candidateReviewGroups(conversation, candidates);
  if (!groups.length) return null;
  return <aside role="note" className="task-generation-notes" data-testid="candidate-review-notice">
    <strong>{pick("Business content needs independent review", "业务内容尚待独立复核")}</strong>
    <p>{pick("Accepting saves cases; it does not certify business expectations or coverage. Review the content and sources before accepting.", "采纳仅保存用例，不代表业务预期或覆盖已认证。请先审阅内容与原始依据。")}</p>
    {groups.map(group => <div key={group.key}>
      <p>{group.count} {pick("candidate(s)", "条候选")} · {group.status === "pending_manual"
        ? pick("Pending manual review", "待人工评审")
        : pick("Review status unavailable; treat as unreviewed", "缺少可核实的复核记录，按未评审内容处理")}</p>
      {group.notes.length > 0 && <details open>
        <summary>{pick("Notes recorded at generation", "生成时记录的说明")} · {group.notes.length}</summary>
        <p>{pick("Editing or accepting does not clear these notes or verify the edited case.", "编辑或采纳不会自动清除这些记录，也不代表编辑后的内容已获验证。")}</p>
        <ul>{group.notes.map((note, index) => <li key={`${note.code}:${index}`}>{note.severity === "error" && <strong>{pick("Recorded error", "记录的错误")} · </strong>}{note.objectId && <span>{pick("Linked item", "关联项")} {note.objectId} · </span>}{note.message}</li>)}</ul>
      </details>}
    </div>)}
  </aside>;
}
