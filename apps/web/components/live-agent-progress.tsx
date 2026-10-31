"use client";
import { LoaderCircle, Square } from "lucide-react";
import { agentToolLabels } from "@/lib/workbench-agent-tool-labels";
import { useI18n } from "@/lib/i18n";
import type { DurableRun } from "@/lib/workbench-durable-run";
import type { LiveAgentRun } from "@/lib/use-workbench-agent-run";

export function LiveAgentProgress({ run, onCancel, durableRun }: { run: LiveAgentRun | null; onCancel: () => void; durableRun?: DurableRun | null }) {
  const { pick } = useI18n();
  if (!run) return null;
  const terminal = run.events.findLast(event => event.type.startsWith("run_") && event.type !== "run_started");
  const stopping = ["sending", "requested", "already_terminal"].includes(run.cancellation);
  const labels: Record<string, string> = {
    run_started: pick("Run started", "任务已开始"), model_started: pick("Model working", "模型处理中"),
    tool_started: pick("Tool started", "工具已开始"), tool_completed: pick("Tool returned", "工具已返回"),
    tool_failed: pick("Tool failed", "工具失败"), tool_rejected: pick("Tool call needs correction", "工具调用需修正"),
    tool_replayed: pick("Reused tool result", "复用工具结果"), plan_continuation: pick("Continuing the plan", "继续执行计划"),
    final_correction: pick("Checking the response against tool results", "核对回复与工具结果"),
    run_completed: pick("Agent turn finished · checking task state", "本轮对话处理结束 · 正在核对任务状态"),
    run_awaiting_input: pick("Awaiting confirmation or input", "等待确认或补充"),
    run_failed: pick("Run did not finish", "任务未完成"), run_cancelled: pick("Run stopped", "任务已停止"),
  };
  const tools = agentToolLabels(pick);
  const latest = run.events.at(-1);
  const segmentOnly = terminal && durableRun && ["active", "running", "waiting_job", "paused"].includes(durableRun.status);
  return <section className="live-agent-progress" aria-label={pick("Live agent progress", "Agent 实时进度")}>
    <div role="status"><LoaderCircle size={14} className={terminal ? undefined : "auth-spinner"} /><strong>{segmentOnly ? pick("Agent segment ended · see saved plan below", "本轮 Agent 已结束 · 请查看下方保存的计划") : terminal ? labels[terminal.type] : latest ? labels[latest.type] : pick("Connecting to task updates…", "正在连接任务进度…")}</strong></div>
    <details><summary>{pick(`Execution events · ${run.events.length}`, `执行事件 · ${run.events.length}`)}</summary><ol>{run.events.slice(-12).map(event => <li key={event.sequence}><span>{labels[event.type]}</span>{event.tool && <small>{tools[event.tool] ?? pick("Authorized tool", "授权工具")}</small>}</li>)}</ol></details>
    <small>{pick("Live server events, not generated token animation. Tool completion does not mean formal changes were saved.", "真实服务器事件，非逐字动画；工具完成不代表正式变更已保存。")}</small>
    {run.connection === "reconnecting" && <p role="status">{pick("Reconnecting to progress. The task may still be running.", "正在重连进度，任务可能仍在执行。")}</p>}
    {run.connection === "unavailable" && <p role="status">{pick("Live updates unavailable. Waiting for the authoritative response; saved activity remains available after refresh.", "实时进度不可用，正在等待正式响应；刷新后仍可查看已保存的执行记录。")}</p>}
    {run.cancellation === "requested" && <p role="status">{pick("Stop requested. The current model/tool call may finish before the run stops.", "已请求停止；当前模型或工具调用可能完成后才会停止。")}</p>}
    {run.cancellation === "already_terminal" && <p role="status">{pick("The server says this agent turn has ended. Draft computation may still be running.", "服务器确认本轮对话处理已结束；草稿计算可能仍在运行。")}</p>}
    {run.cancellation === "failed" && <p role="alert">{pick("Stop request was not confirmed. The task may still be running; you can retry.", "停止请求未获确认，任务可能仍在执行，可重试。")}</p>}
    {!terminal && <button type="button" disabled={stopping} onClick={onCancel}><Square size={13} />{stopping ? pick("Stopping…", "等待停止…") : pick("Stop agent run", "停止 Agent 任务")}</button>}
  </section>;
}
