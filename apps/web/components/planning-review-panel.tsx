"use client";

import { useEffect, useState } from "react";
import { decidePlanningReview, listPlanningReviews, startPlanningReview,
  type PlanningReviewRecord, type TestPlanningDto } from "../lib/casepilot-api";

const labels: Record<string, string> = {audit_pending: "等待审核", auditing: "正在审核",
  reviewed: "审核意见待审阅", revision_pending: "等待修订提案", revising: "正在拟订修订",
  proposed: "修订提案待你确认", applied: "已接受修订，仍待独立复核", cancelled: "已取消",
  invalidated: "原规划或来源已变化，请查看最新版本", failed: "本轮未完成，已停止调用"};

export function PlanningReviewPanel({workspaceId, version, planning, onApplied}: {
  workspaceId: string; version: number; planning: TestPlanningDto; onApplied: () => void;
}) {
  const [record, setRecord] = useState<PlanningReviewRecord | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [countConfirmed, setCountConfirmed] = useState(false);
  useEffect(() => {
    let disposed = false;
    const refresh = () => listPlanningReviews(workspaceId).then(rows => {
      if (!disposed) setRecord(rows.filter(r => r.base_version === version).at(-1) ?? null);
    }).catch(() => { if (!disposed) setError("无法读取审核状态，请稍后刷新。"); });
    void refresh();
    const timer = setInterval(() => void refresh(), 2000);
    const listener = () => void refresh();
    window.addEventListener("planning-review-updated", listener);
    return () => { disposed = true; clearInterval(timer); window.removeEventListener("planning-review-updated", listener); };
  }, [workspaceId, version]);
  async function act(action: "start" | "revise" | "apply" | "cancel") {
    setBusy(true); setError("");
    try {
      const result = action === "start" ? await startPlanningReview(workspaceId, version)
        : await decidePlanningReview(workspaceId, record!, action, selected, countConfirmed);
      setRecord(result);
      window.dispatchEvent(new Event("planning-review-updated"));
      if (action === "apply") onApplied();
    } catch { setError("操作未完成；规划或确认可能已变化，请刷新查看。未自动重试。"); }
    finally { setBusy(false); }
  }
  return <PlanningReviewCard version={version} planning={planning} record={record}
    selected={selected} setSelected={setSelected} busy={busy} error={error}
    countConfirmed={countConfirmed} setCountConfirmed={setCountConfirmed} act={act} />;
}

export function PlanningReviewCard({version, planning, record, selected, setSelected, busy, error,
  countConfirmed, setCountConfirmed, act}: {
  version: number; planning: TestPlanningDto; record: PlanningReviewRecord | null;
  selected: string[]; setSelected: (value: string[] | ((ids: string[]) => string[])) => void;
  busy: boolean; error: string; countConfirmed: boolean; setCountConfirmed: (value: boolean) => void;
  act: (action: "start" | "revise" | "apply" | "cancel") => Promise<void>;
}) {
  const delta = (record?.proposal?.points ?? []).reduce((n, p) => n + (p.action === "delete" ? -1 : p.point_id.startsWith("new:") ? 1 : 0), 0);
  return <section aria-label="全计划审核与修订" className="planning-coverage-summary">
    <strong>全计划审核与修订 · V{version}</strong>
    <p>审核意见由模型提出，不是独立质量证明。全计划审核与一次修订合计最多 2 次请求；未知事项仍需复核。</p>
    {error && <p role="alert">{error}</p>}
    {!record ? <button disabled={busy} onClick={() => void act("start")}>审核完整规划</button> : <>
      <p role="status">{labels[record.status] ?? "等待状态更新"} · 已用 {record.requests_used}/2 次请求</p>
      {record.review?.findings.map(f => <article key={f.id}>
        <label><input type="checkbox" disabled={record.status !== "reviewed" || busy}
          checked={selected.includes(f.id)} onChange={e => setSelected(ids => e.target.checked ? [...ids, f.id] : ids.filter(id => id !== f.id))} />{f.explanation}</label>
        <p>涉及测试点：{f.point_ids.join("、") || "缺失场景"}；义务：{f.obligation_keys.join("、") || "待补充"}</p>
        {f.citations.map((c, i) => <blockquote key={i}>{c.quote}<small> — {record.sources[c.source]?.label} {record.sources[c.source]?.locator}</small></blockquote>)}
      </article>)}
      {record.review?.unresolved.map((text, i) => <p key={i}>待确认：{text}</p>)}
      {record.status === "reviewed" && <button disabled={busy || !selected.length} onClick={() => void act("revise")}>为选中问题拟订一次修订</button>}
      {record.proposal && <div>
        <h4>修订预览</h4>
        {record.proposal.points.map(p => <article key={p.point_id}>
          <strong>{p.action === "delete" ? "删除" : p.point_id.startsWith("new:") ? "新增" : "修改"}：{p.title || p.point_id}</strong>
          <p>原场景：{planning.test_points.find(old => old.id === p.point_id)?.scenario || "无"}</p>
          <p>原预期：{planning.test_points.find(old => old.id === p.point_id)?.objective || "无"}</p>
          <p>原主要功能：{planning.test_points.find(old => old.id === p.point_id)?.primary_feature_id || "无"}</p>
          {p.sources.map((index, i) => <blockquote key={i}>拟议依据：{record.sources[index]?.excerpt}</blockquote>)}
          {p.action !== "delete" && <><p>拟议场景：{p.scenario}</p><p>拟议预期：{p.objective}</p><p>主要功能：{p.primary_feature_id}</p></>}
        </article>)}
        {record.proposal.obligations.map(o => <p key={o.key}>义务 {o.key} → {o.point_ids.join("、")}；依据：{o.basis}；待确认：{o.clarification}</p>)}
        {record.proposal.unresolved.map((text, i) => <p key={i}>仍未解决：{text}</p>)}
        {record.status === "proposed" && <><p>接受只创建新版本规划草稿，不生成或采纳正式用例，未核警告保留。</p>
          {delta !== 0 && <label><input type="checkbox" checked={countConfirmed} onChange={e => setCountConfirmed(e.target.checked)} />我确认测试点数量从 {planning.test_points.length} 改为 {planning.test_points.length + delta}</label>}
          <button disabled={busy || (delta !== 0 && !countConfirmed)} onClick={() => void act("apply")}>确认接受此修订提案</button></>}
      </div>}
      {["audit_pending", "auditing", "reviewed", "revision_pending", "revising", "proposed"].includes(record.status) &&
        <button disabled={busy} onClick={() => void act("cancel")}>取消本轮</button>}
    </>}
  </section>;
}
