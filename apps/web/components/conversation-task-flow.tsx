"use client";

import type { ConversationIntent } from "@/lib/casepilot-api";
import { workspaceScopeLabel, type WorkspaceTask } from "@/lib/workspace-tasks";
import { useI18n } from "@/lib/i18n";

type Props = {
  tasks: WorkspaceTask[];
  labels: Record<ConversationIntent, string>;
  statusLabels: Record<string, string>;
  busy: boolean;
  onResume: (task: WorkspaceTask) => void;
  onResult: (id: string) => void;
};

/** Conversation owns task orchestration; the workstation owns its artifacts. */
export function ConversationTaskFlow({ tasks, labels, statusLabels, busy, onResume, onResult }: Props) {
  const { pick } = useI18n();
  if (!tasks.length) return null;
  return <section className="conversation-task-flow" aria-label={pick("Task plan and progress", "任务计划与进度")}>
    <ol>{tasks.slice().reverse().map((task) => {
      const generationReview = task.status === "awaiting_confirmation"
        && task.operation?.status === "completed"
        && task.versions?.some((round) => round.message.intent === "CASE_GENERATE");
      const displayIntent = generationReview ? "CASE_GENERATE" : task.message.intent;
      const generationRound = generationReview
        ? task.versions?.find((round) => round.message.intent === "CASE_GENERATE")
        : undefined;
      const steps = task.message.metadata.action === "module_created"
        ? [pick("Define module", "确定模块"), pick("Create module", "创建模块")]
        : displayIntent === "CASE_GENERATE"
          ? [pick("Define scope", "明确范围"), pick("Generate", "生成用例"), pick("Review", "审阅结果"), pick("Add to collection", "纳入集合")]
          : ["CASE_MODIFY", "CASE_DELETE"].includes(task.message.intent ?? "")
            ? [pick("Resolve targets", "确定目标"), pick("Prepare changes", "准备变更"), pick("Review in workstation", "工作区确认"), pick("Apply", "应用变更")]
            : [pick("Resolve scope", "确定范围"), pick("Process", "执行任务"), pick("Result", "结果摘要")];
      const terminalFailure = ["failed", "cancelled", "superseded", "conflict", "not_applied"].includes(task.status);
      const scopeConfirmation = task.message.metadata.modification_confirmation === true;
      const stepIndex = generationReview ? 2 : task.status === "completed" ? steps.length - 1
        : task.status === "awaiting_confirmation" ? (scopeConfirmation || (task.message.intent === "CASE_GENERATE" && !(task.operation?.result.candidate_ids as string[] | undefined)?.length) ? 0 : 2)
          : task.status === "running" ? (task.workflow?.operation === "draft_brief" ? 0 : 1) : 0;
      const status = task.waitingOn ? pick("Waiting for previous task", "等待前置任务")
        : generationReview ? pick("Candidates awaiting review", "候选待评审") : statusLabels[task.status] ?? ({
        superseded: pick("Superseded", "已被新方案替代"),
        conflict: pick("Version conflict", "版本冲突"),
    not_applied: pick("Not applied", "未应用"),
        awaiting_target: pick("Needs details", "待补充信息"),
        awaiting_clarification: pick("Needs details", "待补充信息"),
        awaiting_collection: pick("Choose collection", "待选择集合"),
      }[task.status] ?? task.status);
      const plan = (generationRound?.operation?.payload.plan ?? task.operation?.payload.plan) as { target_text?: string; constraints?: string[] } | undefined;
      return <li key={task.id} data-status={task.status}>
        <div className="conversation-task-flow__heading"><strong>{task.message.metadata.action === "module_created" ? pick("Create module", "创建模块") : labels[displayIntent!]}</strong><span role="status">{status}</span></div>
        <details className="conversation-task-flow__plan"><summary>{pick("Scope & plan", "范围与计划")}</summary>
        <p>{String(generationRound?.operation?.payload.instruction ?? generationRound?.request?.content ?? task.operation?.payload.instruction ?? task.request?.content ?? "")}</p>
        {plan?.target_text && <p>{pick("Scope", "范围")}：{workspaceScopeLabel(generationRound?.operation?.payload ?? task.operation?.payload)}</p>}
        {!!plan?.constraints?.length && <p>{pick("Preserve", "约束")}：{plan.constraints.join("；")}</p>}
        </details>
        <div className="task-workflow" aria-label={pick("Task workflow", "任务工作流")}>{steps.map((label, index) => <div key={label} aria-current={index === stepIndex && !terminalFailure && task.status !== "completed" ? "step" : undefined} data-state={terminalFailure ? "pending" : index < stepIndex || task.status === "completed" ? "done" : index === stepIndex ? "current" : "pending"}><span>{index + 1}</span>{label}</div>)}</div>
        {task.status === "awaiting_confirmation" && <p className="conversation-task-flow__boundary">{pick("Pending changes are previews. Only confirmed changes are saved.", "待确认变更仅为预览，确认后才会保存。")}</p>}
        <div className="conversation-task-flow__actions">
          {!["KNOWLEDGE_QA", "UNRESOLVED"].includes(task.message.intent ?? "") && <button type="button" onClick={() => onResult(task.id)}>{pick("View result", "查看结果")}</button>}
          {task.operation && ["failed", "awaiting_target", "queued"].includes(task.status) && !task.waitingOn && <button type="button" disabled={busy} onClick={() => onResume(task)}>{task.status === "failed" ? pick("Retry", "重试任务") : task.status === "queued" ? pick("Continue", "继续任务") : pick("Provide details", "补充信息")}</button>}
        </div>
      </li>;
    })}</ol>
  </section>;
}
