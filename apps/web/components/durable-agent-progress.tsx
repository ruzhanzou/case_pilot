"use client";
import { useEffect, useRef, useState } from "react";
import { DurableSegmentActivity } from "@/components/durable-segment-activity";
import { Square } from "lucide-react";
import { cancelWorkbenchAgentRun, getConversation } from "@/lib/casepilot-api";
import { acceptsDurableProjection, budgetKeys, durableIsTerminal, parseDurableRun, watchDurableRun, type DurableRun } from "@/lib/workbench-durable-run";
import { useI18n } from "@/lib/i18n";

export function DurableAgentProgress({ conversationId, value, onRefresh }: { conversationId: string; value: unknown; onRefresh: (id: string, isCurrent?: () => boolean) => Promise<void> }) {
  const { pick } = useI18n();
  const projected = parseDurableRun(value);
  // A prop projection change invalidates in-flight reads from the previous phase.
  const scope = `${conversationId}:${projected?.id}:${projected?.epoch}:${projected?.cursor}:${projected?.status}`;
  const [observed, setObserved] = useState<{ scope: string; run: DurableRun; reconnecting: boolean } | null>(null);
  const [cancellation, setCancellation] = useState<{ scope: string; state: "sending" | "requested" | "failed" } | null>(null);
  const refresh = useRef(onRefresh);
  useEffect(() => { refresh.current = onRefresh; }, [onRefresh]);
  const owner = useRef<object | null>(null);
  const initial = useRef(projected);
  useEffect(() => { initial.current = projected; });
  useEffect(() => {
    const run = initial.current;
    if (!run) return;
    const token = {}; owner.current = token;
    let reconnecting = false, last = run;
    const close = watchDurableRun({ conversationId, initial: run, read: getConversation,
      onConnection: state => { reconnecting = state === "reconnecting"; if (owner.current === token) setObserved({ scope, run: last, reconnecting }); },
      onProjection: next => {
        if (owner.current !== token) return;
        setObserved({ scope, run: next, reconnecting });
        if (next.epoch !== last.epoch || next.cursor !== last.cursor || next.status !== last.status) void refresh.current(conversationId, () => owner.current === token).catch(() => undefined);
        last = next;
      },
    });
    return () => { close(); if (owner.current === token) owner.current = null; };
  }, [conversationId, scope]);
  if (!projected) return null;
  const run = observed?.scope === scope && acceptsDurableProjection(projected, observed.run) ? observed.run : projected;
  const terminal = durableIsTerminal(run);
  const status = {
    paused: pick("Plan temporarily paused", "计划暂时暂停"),
    active: pick("Plan active", "计划已启动"), running: pick("Executing plan", "正在执行计划"),
    waiting_job: pick("Waiting for draft computation", "等待草稿计算"), waiting_approval: pick("Waiting for your review", "等待人工审阅"),
    completed: pick("Plan completed", "计划已完成"), failed: pick("Plan failed", "计划失败"), cancelled: pick("Plan stopped", "计划已停止"),
    invalidated: pick("Plan scope invalidated", "计划范围已失效"), budget_exhausted: pick("Execution budget exhausted", "执行预算已用尽"),
  }[run.status];
  const stopState = cancellation?.scope === scope ? cancellation.state : null;
  const cancel = async () => {
    const token = owner.current;
    if (!token || terminal || stopState === "sending" || stopState === "requested") return;
    setCancellation({ scope, state: "sending" });
    try {
      await cancelWorkbenchAgentRun(conversationId, run.id);
      if (owner.current !== token) return;
      setCancellation({ scope, state: "requested" });
      await refresh.current(conversationId, () => owner.current === token);
    } catch { if (owner.current === token) setCancellation({ scope, state: "failed" }); }
  };
  const stepLabels: Record<string, string> = {
    pending: pick("Pending", "待执行"), running: pick("Running", "执行中"), completed: pick("Completed", "已完成"),
    waiting_job: pick("Waiting for worker", "等待后台计算"), waiting_approval: pick("Awaiting review", "等待审阅"),
    failed: pick("Failed", "失败"), cancelled: pick("Stopped", "已停止"), skipped: pick("Skipped", "已跳过"),
  };
  return <section className="live-agent-progress" aria-label={pick("Durable plan progress", "持久计划进度")}>
    <strong role="status">{status}</strong>
    <DurableSegmentActivity conversationId={conversationId} run={run} />
    <p>{pick(`Plan cursor ${run.cursor}/${run.plan.steps.length} · revision ${run.epoch}`, `计划游标 ${run.cursor}/${run.plan.steps.length} · 版本 ${run.epoch}`)}</p>
    <ol>{run.plan.steps.map((step, index) => <li key={`${index}:${step.action}`} aria-current={!terminal && index === run.cursor ? "step" : undefined}>
      <span>{step.description || step.action}</span> · <small>{stepLabels[step.status] ?? pick("Status recorded", "状态已记录")}</small>
      {step.depends_on.length > 0 && <small> · {pick("Dependencies", "依赖步骤")}: {step.depends_on.join(", ")}</small>}
    </li>)}</ol>
    {run.status === "paused" && <p role="status">{pick("Paused while another instruction is processed. If that request was interrupted, recovery requires retrying the same request. Refresh only reads saved progress; it does not resume execution.", "处理另一条指令时暂时暂停。若该请求中断，恢复需要重试同一请求；刷新只读取已保存进度，不会恢复执行。")}</p>}
    {run.reason === "scope_requires_selection" && <p role="status">{pick("The original exact targets can no longer be safely resumed. Select the intended cases and give the next instruction; nothing is applied automatically.", "原精确目标已无法安全续跑。请重选目标用例并给出下一条指令，不会自动应用任何变更。")}</p>}
    {run.status === "invalidated" && <p role="status">{pick("The prior plan was stopped because a new instruction or target changed its authority. Existing proposals still require their original exact review; they are not applied to the new target.", "新指令或目标变更已停止原计划。既有提案仍须按原精确范围审阅，不会套用到新目标。")}</p>}
    <small>{pick("The agent segment may finish while the plan waits for workers or approval. Only explicit review applies changes.", "单轮 Agent 结束不代表整个计划完成；计划可能等待后台计算或人工审批，只有明确审阅才会应用变更。")}</small>
    <details><summary>{pick("Reserved execution budget", "已预留执行预算")}</summary><small>{pick("Conservative reservations, not measured provider usage.", "保守预留额度，不代表实测模型调用用量。")}</small><ul>{budgetKeys.filter(key => run.budget[key] !== undefined).map(key => <li key={key}>{key}: {run.used[key] ?? 0}/{run.budget[key]}</li>)}</ul></details>
    {observed?.scope === scope && observed.reconnecting && <p role="status">{pick("Reconnecting to saved progress; no new task is submitted.", "正在重新读取已保存进度，不会重新提交任务。")}</p>}
    {stopState === "requested" && !terminal && <p role="status">{pick("Stop requested; waiting for persisted confirmation.", "已请求停止，等待服务端持久化确认。")}</p>}
    {stopState === "failed" && <p role="alert">{pick("Stop was not confirmed. Retry if needed.", "停止尚未确认，可重试。")}</p>}
    {!terminal && <button type="button" onClick={() => void cancel()} disabled={stopState === "sending" || stopState === "requested"}><Square size={13} />{pick("Stop plan", "停止计划")}</button>}
  </section>;
}
