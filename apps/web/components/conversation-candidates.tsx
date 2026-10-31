"use client";
import type { WorkspaceCandidateDto } from "@/lib/casepilot-api";
import { useI18n } from "@/lib/i18n";

export function ConversationCandidates({ candidates, busy, onCommit, onInspect }: { candidates: WorkspaceCandidateDto[]; busy: boolean; onCommit: (ids: string[]) => void; onInspect: () => void }) {
  const { pick } = useI18n();
  if (!candidates.length) return null;
  return <details className="conversation-review">
    <summary>{pick(`Review ${candidates.length} selected candidates`, `审阅 ${candidates.length} 条已选候选`)}</summary>
    <small>{pick("Only these selected candidates in this task will be accepted. Their displayed versions are checked by the server.", "仅采纳本任务下列已选候选，服务器会校验当前展示版本。")}</small>
    <div className="conversation-review__items">{candidates.map(candidate => <details key={candidate.id}>
      <summary>{candidate.snapshot.title} · V{candidate.version}</summary>
      <p>{candidate.snapshot.module} · {candidate.snapshot.priority}</p>
      <ul>{candidate.snapshot.preconditions.map((text, index) => <li key={index}>{text}</li>)}</ul>
      <ol>{candidate.snapshot.steps.map((step, index) => <li key={index}><strong>{step.action}</strong><p>{step.expected}</p></li>)}</ol>
    </details>)}</div>
    <div className="conversation-review__actions"><button type="button" onClick={onInspect}>{pick("Change selection in results", "在结果中调整选择")}</button><button type="button" disabled={busy} onClick={() => onCommit(candidates.map(candidate => candidate.id))}>{pick(`Accept these ${candidates.length} candidates`, `采纳这 ${candidates.length} 条候选`)}</button></div>
  </details>;
}
