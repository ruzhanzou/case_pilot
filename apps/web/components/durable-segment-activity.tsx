"use client";
import { useEffect, useRef, useState } from "react";
import { workbenchAgentEventsUrl } from "@/lib/casepilot-api";
import { watchDurableSegments, type DurableSegmentActivity as Activity } from "@/lib/workbench-durable-segments";
import type { DurableRun } from "@/lib/workbench-durable-run";
import { agentToolLabels } from "@/lib/workbench-agent-tool-labels";
import { useI18n } from "@/lib/i18n";

export function DurableSegmentActivity({conversationId, run}: {conversationId: string; run: DurableRun}) {
  const {pick} = useI18n();
  const scope = `${conversationId}:${run.id}:${run.request_id ?? ""}`;
  const [observed, setObserved] = useState<{scope: string; activity: Activity} | null>(null);
  const observer = useRef<ReturnType<typeof watchDurableSegments> | null>(null);
  useEffect(() => {
    const subscription = watchDurableSegments({conversationId, eventsUrl: workbenchAgentEventsUrl,
      onActivity: activity => setObserved({scope, activity}),
    });
    observer.current = subscription;
    return () => { subscription.close(); if (observer.current === subscription) observer.current = null; };
  }, [conversationId, scope]);
  const latest = useRef(run);
  useEffect(() => { latest.current = run; });
  useEffect(() => { observer.current?.update(latest.current); }, [scope, run.status, run.segment_sequence_base]);
  const activity = observed?.scope === scope && observed.activity.base === run.segment_sequence_base ? observed.activity : null;
  if (!run.request_id || run.segment_sequence_base === undefined) return null;
  const names = agentToolLabels(pick);
  const events = activity?.events ?? [];
  const eventLabel = (type: string) => ({
    run_started: pick("Segment started", "执行片段已开始"), model_started: pick("Model working", "模型处理中"),
    tool_started: pick("Started", "已开始"), tool_completed: pick("Returned", "已返回"), tool_failed: pick("Failed", "失败"),
    tool_rejected: pick("Needs correction", "需修正"), tool_replayed: pick("Reused result", "复用结果"),
    plan_continuation: pick("Continuing plan", "继续计划"), final_correction: pick("Checking results", "核对结果"),
    run_completed: pick("Segment finished, not necessarily the plan", "片段结束，不代表计划完成"),
    run_awaiting_input: pick("Segment yielded control; see plan state", "片段已交还控制，请查看计划状态"),
    run_failed: pick("Segment failed", "片段失败"), run_cancelled: pick("Segment stopped", "片段停止"),
  }[type] ?? pick("Recorded event", "已记录事件"));
  return <details open={run.status === "running"} aria-label={pick("Current SDK segment activity", "当前 SDK 片段活动")}>
    <summary>{pick("Actual execution events", "实际执行事件")} · {events.length}</summary>
    {events.length === 0 && <p role="status">{pick("Waiting for recorded segment events; no progress is inferred.", "等待实际片段事件，不推测执行进度。")}</p>}
    <ol>{events.slice(-24).map(event => <li key={event.sequence}>{eventLabel(event.type)}{event.tool && <span> · {names[event.tool] ?? pick("Authorized tool", "授权工具")}</span>}</li>)}</ol>
    {activity?.connection === "reconnecting" && <p role="status">{pick("Reconnecting from the last received event.", "从最后收到的事件位置重连。")}</p>}
    {activity?.connection === "unavailable" && <p role="status">{pick("Segment events unavailable; saved plan polling continues.", "片段事件暂不可用，仍在读取已保存计划状态。")}</p>}
  </details>;
}
