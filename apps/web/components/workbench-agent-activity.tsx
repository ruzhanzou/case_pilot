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
  const business = activity.business_outcome;
  const noExecution = business && ["not_executed", "context_observed", "planned"].includes(business.activity);
  const businessLabel = business ? {
    not_executed: pick("No business operation executed", "未执行业务操作"),
    context_observed: pick("Context read only; no task or diff created", "仅观察上下文；未创建任务或差异"),
    read_completed: pick("Read operation recorded; no application proved", "已记录读取操作；不代表已应用变更"),
    workspace_updated: pick("Workspace selection updated; no formal application proved", "工作区选择已更新；不代表已应用正式变更"),
    planned: pick("Plan recorded; execution not verified", "已记录计划；执行尚未核验"),
    preparation_verified: pick("Preparation verified; application requires its own receipt", "已核验准备操作；应用变更需要独立凭据"),
  }[business.activity] : null;
  return <details className="workbench-agent-activity" open={interrupted || Boolean(noExecution)}>
    <summary>{pick("Agent activity", "Agent 执行记录")} · {interrupted ? pick("Incomplete", "未完成") : domainStatus === "paused" ? pick("Temporarily paused", "暂时暂停") : ["awaiting_input", "waiting_approval"].includes(domainStatus) ? pick("Awaiting confirmation or input", "等待确认或补充") : pick("Recorded steps", "已记录步骤")}</summary>
    {["queued", "running", "active", "waiting_job"].includes(domainStatus) && <p role="status">{domainStatus === "queued" ? pick("Draft computation queued. Final changes still require review.", "草稿计算已排队，正式变更仍需审阅。") : pick("Draft computation is running. The agent turn ending does not mean the task is finished.", "草稿正在计算；本轮对话处理结束不代表任务完成。")}</p>}
    {businessLabel && <p role="status">{businessLabel}</p>}
    {business?.activity === "read_completed" && business.plan_coverage === "not_planned" && <p>{pick("This verifies only the read result, not completion of any other requested actions.", "仅核验本次读取结果，不代表其他请求操作已经完成。")}</p>}
    {activity.durable_run && activity.durable_run.plan.steps.length > 0 && <p>{pick(`Durable plan: ${activity.durable_run.cursor}/${activity.durable_run.plan.steps.length} steps traversed.`, `持久计划游标：${activity.durable_run.cursor}/${activity.durable_run.plan.steps.length}。`)}</p>}
    <small>{pick("Recorded tool actions, not a live token stream. Domain review controls remain authoritative.", "已记录的工具操作，非实时逐字输出；请以任务审阅状态为准。")}</small>
    <ol>{activity.events.filter(event => event.type.startsWith("tool_")).map(event => <li key={event.sequence}><span>{names[event.tool ?? ""] ?? pick("Tool operation", "工具操作")}</span><small>{event.type === "tool_completed" ? pick("Returned", "已返回") : event.type === "tool_failed" ? pick("Failed", "失败") : event.type === "tool_rejected" ? pick("Needs correction", "需修正") : event.type === "tool_replayed" ? pick("Reused result", "复用结果") : pick("Started", "已开始")}</small></li>)}</ol>
    {effect && <p>{effect === "read" ? pick("Read operation verified by its receipt. No formal cases were saved by this receipt.", "读取操作已由回执核验；该回执不代表正式用例已保存。") : pick("Preparation receipt verified. Computation may still be pending; review the ready result before saving.", "已核验准备回执，计算可能尚未结束；结果就绪后仍需审阅确认才能保存。")}</p>}
    {interrupted && <p>{pick("The task did not finish. Prepared proposals, if any, still require review.", "任务尚未完成；如已准备方案，仍需审阅确认。")}</p>}
  </details>;
}
