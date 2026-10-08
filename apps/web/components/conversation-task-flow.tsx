"use client";

import type { ConversationIntent } from "@/lib/casepilot-api";
import type { WorkspaceTask } from "@/lib/workspace-tasks";
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
  return <details className="conversation-task-flow" open>
    <summary>{pick("Task flow", "任务流")} · {tasks.length}</summary>
    <ol>{tasks.slice().reverse().map((task) => {
      const steps = task.message.metadata.action === "module_created"
        ? [pick("Define module", "确定模块"), pick("Create module", "创建模块")]
        : task.message.intent === "CASE_GENERATE"
          ? [pick("Define scope", "明确范围"), pick("Generate", "生成用例"), pick("Review", "审阅结果"), pick("Add to collection", "纳入集合")]
          : ["CASE_MODIFY", "CASE_DELETE"].includes(task.message.intent ?? "")
            ? [pick("Resolve targets", "确定目标"), pick("Prepare changes", "准备变更"), pick("Review in workstation", "工作区确认"), pick("Apply", "应用变更")]
            : [pick("Resolve scope", "确定范围"), pick("Process", "执行任务"), pick("Result", "结果摘要")];
      const stepIndex = task.status === "completed" ? steps.length - 1
        : task.status === "awaiting_confirmation" ? (task.message.intent === "CASE_GENERATE" && !(task.operation?.result.candidate_ids as string[] | undefined)?.length ? 0 : 2)
          : task.status === "running" ? (task.workflow?.operation === "draft_brief" ? 0 : 1) : 0;
      const status = task.waitingOn ? pick("Waiting for previous task", "等待前置任务") : statusLabels[task.status] ?? ({
        superseded: pick("Superseded", "已被新方案替代"),
        conflict: pick("Version conflict", "版本冲突"),
    not_applied: pick("Not applied", "未应用"),
        awaiting_target: pick("Needs details", "待补充信息"),
        awaiting_clarification: pick("Needs details", "待补充信息"),
        awaiting_collection: pick("Choose collection", "待选择集合"),
      }[task.status] ?? task.status);
      const plan = task.operation?.payload.plan as { target_text?: string; constraints?: string[] } | undefined;
      return <li key={task.id}>
        <div className="conversation-task-flow__heading"><strong>{task.message.metadata.action === "module_created" ? pick("Create module", "创建模块") : labels[task.message.intent!]}</strong><span role="status">{status}</span></div>
        <p>{String(task.operation?.payload.instruction ?? task.request?.content ?? "")}</p>
        {plan?.target_text && <p>{pick("Scope", "范围")}：{plan.target_text}</p>}
        {!!plan?.constraints?.length && <p>{pick("Preserve", "约束")}：{plan.constraints.join("；")}</p>}
        <div className="task-workflow" aria-label={pick("Task workflow", "任务工作流")}>{steps.map((label, index) => <div key={label} aria-current={index === stepIndex && task.status !== "completed" ? "step" : undefined} data-state={index < stepIndex || task.status === "completed" ? "done" : index === stepIndex ? "current" : "pending"}><span>{index + 1}</span>{label}</div>)}</div>
        <div className="conversation-task-flow__actions">
          {!["KNOWLEDGE_QA", "UNRESOLVED"].includes(task.message.intent ?? "") && <button type="button" onClick={() => onResult(task.id)}>{pick("View result", "查看结果")}</button>}
          {task.operation && ["failed", "awaiting_target", "queued"].includes(task.status) && !task.waitingOn && <button type="button" disabled={busy} onClick={() => onResume(task)}>{task.status === "failed" ? pick("Retry", "重试任务") : task.status === "queued" ? pick("Continue", "继续任务") : pick("Provide details", "补充信息")}</button>}
        </div>
      </li>;
    })}</ol>
  </details>;
}
