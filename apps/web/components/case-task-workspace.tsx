"use client";

import { useState, type ReactNode } from "react";
import { CheckCircle2, CircleAlert, Clock3, History, LoaderCircle, MessageSquare } from "lucide-react";
import type { ConversationIntent } from "@/lib/casepilot-api";
import { useI18n } from "@/lib/i18n";
import { workspaceScopeLabel, workspaceTasks } from "@/lib/workspace-tasks";

type Task = ReturnType<typeof workspaceTasks>[number];
type Props = {
  tasks: Task[];
  selectedId: string;
  displayedVersion?: Task;
  onSelect: (id: string) => void;
  labels: Record<ConversationIntent, string>;
  statusLabels: Record<string, string>;
  running: boolean;
  hasLiveResults?: boolean;
  onConversation: (id?: string) => void;
  onArtifact: (task: Task) => void;
  onDiscard?: (task: Task) => void;
  activeTaskId?: string;
  children?: ReactNode;
};

export function CaseTaskWorkspace({ tasks, selectedId, displayedVersion, onSelect, labels, statusLabels, running, hasLiveResults, onConversation, onArtifact, onDiscard, activeTaskId, children }: Props) {
  const { pick } = useI18n();
  const [historyOpen, setHistoryOpen] = useState(false);
  const task = tasks.find((item) => item.id === selectedId) ?? tasks[0];
  const displayedTask = displayedVersion ?? task;
  const historical = Boolean(task && displayedTask?.operation?.id !== task.operation?.id);
  const versionNumber = task?.versions ? task.versions.findIndex(item => item.operation?.id === displayedTask?.operation?.id) + 1 : 0;
  const isRunning = task && !task.waitingOn && ["queued", "running"].includes(task.status);
  const needsDetails = task && ["awaiting_target", "awaiting_clarification"].includes(task.status);
  const failed = task?.status === "failed";
  const cancelled = task?.status === "cancelled";
  const taskLabel = (item: Task) => item.message.metadata.action === "module_created" ? pick("Create module", "创建模块") : labels[(item.operation?.intent ?? item.message.intent) as ConversationIntent];
  const resultTitle = displayedTask?.message.metadata.change_set_id
    ? (displayedTask.operation?.intent === "CASE_DELETE" || displayedTask.message.intent === "CASE_DELETE"
      ? (displayedTask.status === "awaiting_confirmation" ? pick("Confirm deletion", "删除确认") : pick("Deletion result", "删除结果")) : pick("Review changes", "修改审阅"))
    : displayedTask?.message.intent === "CASE_QUERY" ? pick("Query results", "查询结果")
    : displayedTask?.message.intent === "CASE_GENERATE" ? pick("Generation results", "生成结果")
    : displayedTask ? taskLabel(displayedTask) : "";
  const plan = displayedTask?.operation?.payload.plan as { target_text?: string; constraints?: string[] } | undefined;
  const scopeLabel = workspaceScopeLabel(displayedTask?.operation?.payload);
  const sourceTask = tasks.find((item) => item.id === task?.sourceTaskId);
  const canDiscard = Boolean(
    !historical && onDiscard && task?.operation &&
    (task.id === activeTaskId || task.message.intent === "CASE_GENERATE" && task.status === "awaiting_confirmation")
  );
  const statusLabel = (status: string) => statusLabels[status] ?? ({
    superseded: pick("Superseded", "已被新方案替代"),
    conflict: pick("Version conflict", "版本冲突"),
    not_applied: pick("Not applied", "未应用"),
    awaiting_target: pick("Needs details", "待补充信息"),
    awaiting_clarification: pick("Needs details", "待补充信息"),
    awaiting_collection: pick("Choose collection", "待选择集合"),
  }[status]) ?? status;
  const icon = (status: string) => ["queued", "running"].includes(status)
    ? <LoaderCircle size={16} className="auth-spinner" />
    : status === "completed" ? <CheckCircle2 size={16} />
    : ["failed", "cancelled", "conflict"].includes(status) ? <CircleAlert size={16} /> : <Clock3 size={16} />;
  return (
    <section className="case-task-workspace" aria-label={pick("Case workstation", "用例工作区")}>
      {!task ? <div className="case-task-empty"><MessageSquare size={30} /><h3>{pick("Case results appear here", "在这里查看用例结果")}</h3><p>{pick("Ask to generate, modify, query or review cases. Results will be saved here.", "在左侧描述生成、修改、查询或评审用例的需求，生成、查询和修改结果将保留在这里。")}</p><button type="button" disabled={running} onClick={() => onConversation()}>{pick("Go to conversation", "前往对话区")}</button>{children}</div> : (
        <div className="case-task-layout" data-history-open={historyOpen}>
          <nav hidden={!historyOpen} id="case-task-history" onKeyDown={event => { if (event.key === "Escape") { event.preventDefault(); setHistoryOpen(false); document.querySelector<HTMLElement>('[aria-controls="case-task-history"]')?.focus(); } }} className="case-task-history" aria-label={pick("Task history", "历史任务")}>
            <h3><History size={15} />{pick("Case results", "用例结果")}</h3>
            {tasks.map((item, index) => <button type="button" key={item.id} aria-pressed={item.id === task.id} onClick={() => { onSelect(item.id); setHistoryOpen(false); }}>
              <span className="case-task-history__title"><strong>{taskLabel(item)}</strong><small>#{tasks.length - index}</small></span>
              <span className="case-task-history__request">{String(item.operation?.payload.instruction ?? item.request?.content ?? item.message.content) || labels[item.message.intent!]}</span>
              <span className="case-task-status" data-status={item.status}>{icon(item.status)}{item.waitingOn ? pick("Waiting for previous task", "等待前置任务") : statusLabel(item.status)}</span>
            </button>)}
          </nav>
          <div className="case-task-detail" key={task.id} tabIndex={-1} role="region" aria-label={pick("Current task result", "当前任务结果")}>
            <header><div><h3>{resultTitle}{versionNumber > 0 && <small> · V{versionNumber}</small>}</h3></div><div className="case-task-detail__actions"><span className="case-task-status" data-status={historical ? "superseded" : task.status}>{historical ? pick("Historical · read only", "历史版本 · 只读") : displayedTask.message.metadata.change_set_id && task.status === "awaiting_confirmation" ? pick("Awaiting review", "待审阅") : statusLabel(task.status)}</span><button type="button" onClick={() => onConversation(displayedTask.request?.id ?? displayedTask.messageIds.at(-1))}><MessageSquare size={14} />{pick("View request in conversation", "在对话区查看需求")}</button><button type="button" aria-expanded={historyOpen} aria-controls="case-task-history" onClick={() => { setHistoryOpen(!historyOpen); if (!historyOpen) requestAnimationFrame(() => document.querySelector<HTMLElement>('#case-task-history button[aria-pressed="true"]')?.focus()); }}><History size={15} />{pick("Result history", "历史结果")} · {tasks.length}</button></div></header>
            {scopeLabel && <p data-testid="task-requested-scope">{pick("Requested scope", "请求范围")}：{scopeLabel}</p>}
            {!!plan?.constraints?.length && <p>{pick("Preserve", "保留约束")}：{plan.constraints.join("；")}</p>}
            {!historical && !hasLiveResults && (task.waitingOn || isRunning || task.status.startsWith("awaiting_") && task.status !== "awaiting_confirmation" || ["failed", "cancelled"].includes(task.status)) && <div className="case-task-running" role="status"><p>{needsDetails
              ? task.message.content || pick("Confirm the affected cases and requirements in the conversation. Suggestions will appear here.", "请在对话区确认影响范围和修改要求，变更建议将在这里展示。")
              : failed
                ? pick("This task did not complete, so there are no changes to review. Retry it in the conversation.", "本次任务未完成，没有可审阅的变更。请在对话区重试。")
                : cancelled
                  ? pick("This task was stopped. No changes were applied.", "本次任务已停止，未应用任何变更。")
                  : pick("Results will appear here. Follow progress or provide details in the conversation.", "结果将在这里展示，请在对话区查看进度或补充信息。")}</p><button type="button" onClick={() => onConversation(task.messageIds.at(-1))}>{needsDetails ? pick("Provide details", "补充信息") : failed ? pick("Retry in conversation", "前往对话区重试") : pick("View conversation", "查看对话")}</button></div>}
            {task.message.metadata.action === "module_created" && <button type="button" onClick={() => onArtifact(task)}>{pick("View module", "查看模块")}</button>}
            {children}
            {(canDiscard || sourceTask) && <details className="case-task-context"><summary>{pick("Task actions", "任务操作")}</summary>
            {canDiscard && onDiscard && <button type="button" disabled={running} onClick={() => onDiscard(task)}>{pick("Abandon this task", "放弃当前任务")}</button>}
              {sourceTask && <button type="button" onClick={() => onSelect(sourceTask.id)}>{pick("Source result", "来源结果")} · {taskLabel(sourceTask)}</button>}
            </details>}
          </div>
        </div>
      )}
    </section>
  );
}
