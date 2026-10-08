"use client";

import { useState, type ReactNode } from "react";
import { CheckCircle2, CircleAlert, Clock3, History, LoaderCircle, MessageSquare } from "lucide-react";
import type { ConversationIntent } from "@/lib/casepilot-api";
import { useI18n } from "@/lib/i18n";
import { workspaceTasks } from "@/lib/workspace-tasks";

type Task = ReturnType<typeof workspaceTasks>[number];
type Props = {
  tasks: Task[];
  selectedId: string;
  onSelect: (id: string) => void;
  labels: Record<ConversationIntent, string>;
  statusLabels: Record<string, string>;
  running: boolean;
  onConversation: (id?: string) => void;
  onArtifact: (task: Task) => void;
  onDiscard?: (task: Task) => void;
  children?: ReactNode;
};

export function CaseTaskWorkspace({ tasks, selectedId, onSelect, labels, statusLabels, running, onConversation, onArtifact, onDiscard, children }: Props) {
  const { pick, locale } = useI18n();
  const [historyOpen, setHistoryOpen] = useState(false);
  const task = tasks.find((item) => item.id === selectedId) ?? tasks[0];
  const isRunning = task && !task.waitingOn && ["queued", "running"].includes(task.status);
  const taskLabel = (item: Task) => item.message.metadata.action === "module_created" ? pick("Create module", "创建模块") : labels[item.message.intent!];
  const sourceTask = tasks.find((item) => item.id === task?.sourceTaskId);
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
          <nav hidden={!historyOpen} id="case-task-history" className="case-task-history" aria-label={pick("Task history", "历史任务")}>
            <h3><History size={15} />{pick("Case results", "用例结果")}</h3>
            {tasks.map((item, index) => <button type="button" key={item.id} aria-pressed={item.id === task.id} onClick={() => { onSelect(item.id); setHistoryOpen(false); }}>
              <span className="case-task-history__title"><strong>{taskLabel(item)}</strong><small>#{tasks.length - index}</small></span>
              <span className="case-task-history__request">{String(item.operation?.payload.instruction ?? item.request?.content ?? item.message.content) || labels[item.message.intent!]}</span>
              <span className="case-task-status" data-status={item.status}>{icon(item.status)}{item.waitingOn ? pick("Waiting for previous task", "等待前置任务") : statusLabel(item.status)}</span>
            </button>)}
          </nav>
          <div className="case-task-detail" key={task.id}>
            <header><div><h3>{taskLabel(task)}</h3>{task.message.created_at && <time dateTime={task.message.created_at}>{new Date(task.message.created_at).toLocaleString(locale === "en" ? "en-US" : "zh-CN")}</time>}</div><div className="case-task-detail__actions"><span className="case-task-status" data-status={task.status}>{icon(task.status)}{statusLabel(task.status)}</span><button type="button" aria-expanded={historyOpen} aria-controls="case-task-history" onClick={() => setHistoryOpen(!historyOpen)}><History size={15} />{pick("Result history", "历史结果")} · {tasks.length}</button></div></header>
            {(task.waitingOn || isRunning || task.status.startsWith("awaiting_") && task.status !== "awaiting_confirmation" || ["failed", "cancelled"].includes(task.status)) && <div className="case-task-running" role="status"><p>{pick("Results will appear here. Follow progress or provide details in the conversation.", "结果将在这里展示，请在对话区查看进度或补充信息。")}</p><button type="button" onClick={() => onConversation(task.messageIds.at(-1))}>{pick("View conversation", "查看对话")}</button></div>}
            {task.message.metadata.action === "module_created" && <button type="button" onClick={() => onArtifact(task)}>{pick("View module", "查看模块")}</button>}
            {onDiscard && task.operation && task.message.intent === "CASE_GENERATE" && task.status === "awaiting_confirmation" && <button type="button" disabled={running} onClick={() => onDiscard(task)}>{pick("Discard this proposal", "放弃本次方案")}</button>}
            {children}
            <div className="case-task-context">
              <button type="button" onClick={() => onConversation(task.request?.id ?? task.messageIds.at(-1))}><MessageSquare size={14} />{pick("View request in conversation", "在对话区查看需求")}</button>
              {sourceTask && <button type="button" className="task-source-link" onClick={() => onSelect(sourceTask.id)}>{pick("Source result", "来源结果")} · {taskLabel(sourceTask)}</button>}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
