"use client";

import { Streamdown } from "streamdown";
import type { ConversationDto, TestCaseDto, WorkspaceCandidateDto } from "@/lib/casepilot-api";
import { candidatesForTask, type WorkspaceTask } from "@/lib/workspace-tasks";
import { useI18n } from "@/lib/i18n";

type Props = {
  task: WorkspaceTask;
  conversation: ConversationDto;
  busy: boolean;
  cases: TestCaseDto[];
  onLocate: (id: string) => void;
  onToggleCandidate: (candidate: WorkspaceCandidateDto) => void;
  onCommit: () => void;
  onBrief: (version: number) => void;
  onGenerate: () => void;
};

export function CaseTaskArtifacts({ task, conversation, busy, cases, onLocate, onToggleCandidate, onCommit, onBrief, onGenerate }: Props) {
  const { pick } = useI18n();
  if (task.message.intent === "CASE_QUERY") {
    const snapshots = (task.operation?.result.query_cases ?? []) as TestCaseDto[];
    if (!snapshots.length) return null;
    return <section className="task-result-cases" aria-label={pick("Query results", "查询结果")}>
      <h4>{pick(`${snapshots.length} matching cases`, `匹配 ${snapshots.length} 条用例`)}</h4>
      {snapshots.map((item) => <article key={item.id}><div><strong>{item.case_key} · {item.title}</strong><small>{item.module} · {item.priority}</small></div><button type="button" disabled={!cases.some((current) => current.id === item.id)} onClick={() => onLocate(item.id)}>{pick("Locate case", "定位用例")}</button></article>)}
    </section>;
  }
  if (task.message.intent !== "CASE_GENERATE") return null;
  const candidates = candidatesForTask(task, conversation);
  const brief = conversation.test_briefs.filter((item) => item.source_operation_id === task.operation?.id).at(-1);
  const currentBrief = conversation.test_briefs.at(-1);
  const canConfirmBrief = brief && brief.id === currentBrief?.id && conversation.context.phase === "brief_review" && !brief.content.open_questions.some((item) => item.blocking);
  const canCommit = candidates.some((item) => item.status === "candidate" && item.included) && task.operation?.id === conversation.context.active_operation_id;
  return <div className="task-generation-results">
    {brief && <section className="task-brief-result"><header><strong>{pick("Test scope", "测试范围")} · V{brief.version}</strong><button type="button" onClick={() => onBrief(brief.version)}>{pick("View full brief", "查看完整说明")}</button></header><p>{brief.content.test_object}</p><p>{brief.content.scope.join(" · ")}</p>{brief.content.open_questions.length > 0 && <ul>{brief.content.open_questions.map((item, index) => <li key={item.id ?? index}>{item.question}</li>)}</ul>}{canConfirmBrief && <button type="button" disabled={busy} onClick={onGenerate}>{pick("Confirm scope and generate", "确认范围并生成用例")}</button>}</section>}
    {candidates.length > 0 && <section className="task-result-cases" aria-label={pick("Candidate results", "候选结果")}><header><h4>{pick(`${candidates.length} candidate cases`, `${candidates.length} 条候选用例`)}</h4>{canCommit && <button type="button" disabled={busy} onClick={onCommit}>{pick("Add selected candidates", "纳入已选候选")}</button>}</header>
      {candidates.map((candidate) => <details key={candidate.id}><summary>{candidate.status === "candidate" && <input type="checkbox" aria-label={pick(`Include ${candidate.ref}`, `纳入 ${candidate.ref}`)} checked={candidate.included} disabled={busy} onClick={(event) => event.stopPropagation()} onChange={() => onToggleCandidate(candidate)} />}<strong>{candidate.ref} · {String(candidate.snapshot.title ?? "")}</strong><small>{candidate.status === "incorporated" ? pick("Added", "已纳入") : candidate.status === "excluded" ? pick("Not included", "未纳入") : candidate.status === "archived" ? pick("Historical candidate", "历史候选") : pick("Awaiting review", "待审阅")}</small></summary><p>{String(candidate.snapshot.module ?? "")}</p><Streamdown>{((candidate.snapshot.steps ?? []) as { action: string; expected: string }[]).map((step, index) => `${index + 1}. ${step.action}\n\n   ${pick("Expected", "预期")}：${step.expected}`).join("\n\n")}</Streamdown>{candidate.status === "candidate" && <button type="button" onClick={() => onLocate(candidate.id)}>{pick("Edit candidate", "编辑候选")}</button>}</details>)}
    </section>}
  </div>;
}
