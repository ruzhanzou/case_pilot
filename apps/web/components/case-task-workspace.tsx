"use client";

import type { ReactNode } from "react";
import { CheckCircle2, CircleAlert, Clock3, History, LoaderCircle, MessageSquare } from "lucide-react";
import { Streamdown } from "streamdown";
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
  stageLabels: Record<string, string>;
  running: boolean;
  liveProgress?: { name: string; progress: number; count?: number } | null;
  onConversation: (id?: string) => void;
  onArtifact: (task: Task) => void;
  onResume?: (task: Task) => void;
  onDiscard?: (task: Task) => void;
  children?: ReactNode;
};

export function CaseTaskWorkspace({ tasks, selectedId, onSelect, labels, statusLabels, stageLabels, running, liveProgress, onConversation, onArtifact, onResume, onDiscard, children }: Props) {
  const { pick, locale } = useI18n();
  const task = tasks.find((item) => item.id === selectedId) ?? tasks[0];
  const isRunning = task && !task.waitingOn && ["queued", "running"].includes(task.status);
  const taskLabel = (item: Task) => item.message.metadata.action === "module_created" ? pick("Create module", "创建模块") : labels[item.message.intent!];
  const sourceTask = tasks.find((item) => item.id === task?.sourceTaskId);
  const workflowSteps = task?.message.metadata.action === "module_created" ? [pick("Define module", "确定模块"), pick("Create module", "创建模块")] : task?.message.intent === "CASE_GENERATE"
    ? [pick("Define scope", "明确范围"), pick("Generate candidates", "生成候选"), pick("Review candidates", "审阅候选"), pick("Add to collection", "纳入集合")]
    : ["CASE_MODIFY", "CASE_DELETE"].includes(task?.message.intent ?? "")
      ? [pick("Resolve targets", "确定目标"), pick("Prepare changes", "生成方案"), pick("Review differences", "审阅差异"), pick("Apply changes", "应用变更")]
      : [pick("Resolve scope", "确定范围"), pick("Analyze evidence", "分析依据"), pick("Publish result", "输出结果")];
  const stepIndex = task?.status === "completed" ? workflowSteps.length - 1
    : task?.status === "awaiting_confirmation" ? (task.message.intent === "CASE_GENERATE" && !(task.operation?.result.candidate_ids as string[] | undefined)?.length ? 0 : 2)
    : task?.status === "running" ? (task.workflow?.operation === "draft_brief" ? 0 : 1) : 0;
  const statusLabel = (status: string) => statusLabels[status] ?? ({
    not_applied: pick("Not applied", "未应用"),
    awaiting_target: pick("Needs details", "待补充信息"),
    awaiting_clarification: pick("Needs details", "待补充信息"),
    awaiting_collection: pick("Choose collection", "待选择集合"),
  }[status]) ?? status;
  const reportSummary = (task?.message.metadata.analysis_report as { summary?: string } | undefined)?.summary;
  const icon = (status: string) => ["queued", "running"].includes(status)
    ? <LoaderCircle size={16} className="auth-spinner" />
    : status === "completed" ? <CheckCircle2 size={16} />
    : ["failed", "cancelled"].includes(status) ? <CircleAlert size={16} /> : <Clock3 size={16} />;
  return (
    <section className="case-task-workspace" aria-label={pick("Task workspace", "任务工作区")}>
      <header className="case-task-workspace__header">
        <div><h2>{pick("Tasks & results", "任务与结果")}</h2></div>
        <span className="case-task-count">{pick(`${tasks.length} tasks`, `${tasks.length} 个任务`)}</span>
      </header>
      {!task ? <div className="case-task-empty"><MessageSquare size={30} /><h3>{pick("Start your first task", "从对话开始第一个任务")}</h3><p>{pick("Ask to generate, modify, query or review cases. Results will be saved here.", "在左侧描述生成、修改、查询或评审用例的需求，任务和结果将保留在这里。")}</p><button type="button" disabled={running} onClick={() => onConversation()}>{pick("Go to conversation", "前往对话区")}</button>{children}</div> : (
        <div className="case-task-layout">
          <nav className="case-task-history" aria-label={pick("Task history", "历史任务")}>
            <h3><History size={15} />{pick("Conversation tasks", "对话任务")}</h3>
            {tasks.map((item, index) => <button type="button" key={item.id} aria-pressed={item.id === task.id} onClick={() => onSelect(item.id)}>
              <span className="case-task-history__title"><strong>{taskLabel(item)}</strong><small>#{tasks.length - index}</small></span>
              <span className="case-task-history__request">{String(item.operation?.payload.instruction ?? item.request?.content ?? item.message.content) || labels[item.message.intent!]}</span>
              <span className="case-task-status" data-status={item.status}>{icon(item.status)}{item.waitingOn ? pick("Waiting for previous task", "等待前置任务") : statusLabel(item.status)}</span>
            </button>)}
          </nav>
          <div className="case-task-detail">
            <header><div><h3>{taskLabel(task)}</h3>{task.message.created_at && <time dateTime={task.message.created_at}>{new Date(task.message.created_at).toLocaleString(locale === "en" ? "en-US" : "zh-CN")}</time>}</div><span className="case-task-status" data-status={task.status}>{icon(task.status)}{statusLabel(task.status)}</span></header>
            <details className="case-task-request"><summary>{pick("Original request", "任务来源")}</summary><p>{task.request?.content || pick("Continued from this conversation", "由当前对话继续执行")}</p><button type="button" onClick={() => onConversation(task.request?.id ?? task.messageIds.at(-1))}><MessageSquare size={14} />{pick("View conversation", "定位对话")}</button></details>
            {task.groupId && tasks.filter((item) => item.groupId === task.groupId).length > 1 && <p className="task-finding-basis">{pick("Same request", "同一请求")} · {pick("Step", "步骤")} {(task.operation?.sequence ?? 0) + 1} / {tasks.filter((item) => item.groupId === task.groupId).length}</p>}
            {sourceTask && <button type="button" className="task-source-link" onClick={() => onSelect(sourceTask.id)}>{pick("Source task", "来源任务")} · {taskLabel(sourceTask)}</button>}
            {task.operation && <div className="task-workflow" aria-label={pick("Task workflow", "任务工作流")}>{workflowSteps.map((label, index) => <div key={label} data-state={index < stepIndex || task.status === "completed" ? "done" : index === stepIndex ? "current" : "pending"}><span>{index + 1}</span>{label}</div>)}</div>}
            {task.waitingOn ? <div className="case-task-running"><Clock3 size={22} /><h3>{pick("Waiting for previous task", "等待前置任务")}</h3><p>{pick("This task starts when the previous result has been completed and, if needed, applied.", "前置任务完成并确认需要应用的结果后，将继续执行。")}</p><button type="button" onClick={() => onSelect(task.waitingOn!)}>{pick("View previous task", "查看前置任务")}</button></div> : isRunning ? <div className="case-task-running" role="status"><LoaderCircle className="auth-spinner" size={22} /><h3>{pick("Task is running", "任务正在执行")}</h3><p>{stageLabels[liveProgress?.name ?? task.workflow?.current_stage ?? "queued"] ?? pick("Processing your request", "正在处理你的请求")}</p>{Boolean(liveProgress?.count) && ["test_point.generated", "test_case.generated"].includes(liveProgress?.name ?? "") && <p>{pick(`${liveProgress?.count} batches completed in this stage`, `本阶段已完成 ${liveProgress?.count} 批`)}</p>}<p>{pick("Messaging will resume when the task finishes. The result will appear in the conversation.", "任务结束后恢复发送消息，结果会同步展示在对话区。")}</p></div> : <div className="case-task-result"><h4>{pick("Task result", "任务结果")}</h4><Streamdown>{reportSummary || task.message.content || pick("No result content was returned. Check the conversation for details.", "暂未返回结果内容，请查看对话中的详细状态。")}</Streamdown>{(task.message.intent !== "CASE_GENERATE" && task.message.metadata.change_set_id) ? <button type="button" onClick={() => onArtifact(task)}>{pick("View related result", "查看关联结果")}</button> : null}</div>}
            {onResume && task.operation && ["failed", "awaiting_target", "queued"].includes(task.status) && !task.waitingOn && <button type="button" disabled={running} onClick={() => onResume(task)}>{task.status === "failed" ? pick("Retry task", "重试任务") : task.status === "queued" ? pick("Continue task", "继续任务") : pick("Provide details in conversation", "在对话区补充信息")}</button>}
            {onDiscard && task.operation && task.message.intent === "CASE_GENERATE" && task.status === "awaiting_confirmation" && <button type="button" disabled={running} onClick={() => onDiscard(task)}>{pick("Discard this proposal", "放弃本次方案")}</button>}
            {task.workflow && <details className="case-task-steps"><summary>{pick("Execution steps", "执行过程")} · {task.workflow.stages.length}</summary>{task.workflow.stages.map((stage, index) => <div key={`${stage.stage}-${index}`}><span>{stageLabels[stage.stage] ?? stage.stage}</span><span>{stage.progress}%</span></div>)}</details>}
            {children}
          </div>
        </div>
      )}
    </section>
  );
}
