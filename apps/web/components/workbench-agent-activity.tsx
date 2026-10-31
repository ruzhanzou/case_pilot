"use client";
import { parseAgentActivity, verifiedAgentEffect } from "@/lib/workbench-agent-activity";
import { agentToolLabels } from "@/lib/workbench-agent-tool-labels";
import { useI18n } from "@/lib/i18n";

export function WorkbenchAgentActivity({ value }: { value: unknown }) {
  const { pick } = useI18n();
  const activity = parseAgentActivity(value);
  if (!activity) return null;
  const effect = verifiedAgentEffect(activity);
  const domainStatus = activity.durable_run?.status ?? activity.domain_status ?? activity.status;
  const interrupted = ["failed", "cancelled", "invalidated", "budget_exhausted"].includes(domainStatus);
  const names = agentToolLabels(pick);
  return <details className="workbench-agent-activity" open={interrupted}>
    <summary>{pick("Agent activity", "Agent 执行记录")} · {interrupted ? pick("Incomplete", "未完成") : domainStatus === "paused" ? pick("Temporarily paused", "暂时暂停") : ["awaiting_input", "waiting_approval"].includes(domainStatus) ? pick("Awaiting confirmation or input", "等待确认或补充") : pick("Recorded steps", "已记录步骤")}</summary>
    {["queued", "running", "active", "waiting_job"].includes(domainStatus) && <p role="status">{domainStatus === "queued" ? pick("Draft computation queued. Final changes still require review.", "草稿计算已排队，正式变更仍需审阅。") : pick("Draft computation is running. The agent turn ending does not mean the task is finished.", "草稿正在计算；本轮对话处理结束不代表任务完成。")}</p>}
    {activity.durable_run && <p>{pick(`Durable plan: ${activity.durable_run.cursor}/${activity.durable_run.plan.steps.length} steps traversed.`, `持久计划游标：${activity.durable_run.cursor}/${activity.durable_run.plan.steps.length}。`)}</p>}
    <small>{pick("Recorded tool actions, not a live token stream. Domain review controls remain authoritative.", "已记录的工具操作，非实时逐字输出；请以任务审阅状态为准。")}</small>
    <ol>{activity.events.filter(event => event.type.startsWith("tool_")).map(event => <li key={event.sequence}><span>{names[event.tool ?? ""] ?? pick("Tool operation", "工具操作")}</span><small>{event.type === "tool_completed" ? pick("Returned", "已返回") : event.type === "tool_failed" ? pick("Failed", "失败") : event.type === "tool_rejected" ? pick("Needs correction", "需修正") : event.type === "tool_replayed" ? pick("Reused result", "复用结果") : pick("Started", "已开始")}</small></li>)}</ol>
    {effect && <p>{effect === "read" ? pick("Read operation verified by its receipt. No formal cases were saved by this receipt.", "读取操作已由回执核验；该回执不代表正式用例已保存。") : pick("Preparation receipt verified. Computation may still be pending; review the ready result before saving.", "已核验准备回执，计算可能尚未结束；结果就绪后仍需审阅确认才能保存。")}</p>}
    {interrupted && <p>{pick("The task did not finish. Prepared proposals, if any, still require review.", "任务尚未完成；如已准备方案，仍需审阅确认。")}</p>}
  </details>;
}
