"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Background, Controls, Position, ReactFlow, type Node, type Edge, type ReactFlowInstance } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { consumptionSummary, planningActionLabels, pointAction, type PlanningAction } from "@/lib/planning-consumption";
import type { TestPlanningDto, TestCaseDto, PlanningCaseLinkDto } from "@/lib/casepilot-api";

export function TestPlanningMap({ planning, title, busy, editable, onGenerate, onSavePoint, generatedPointIds, onChooseReuse, caseLinks = [], existingCases = [], onLinkCase, onOpenCase, initialPointId }: {
  initialPointId?: string;
  caseLinks?: PlanningCaseLinkDto[];
  existingCases?: TestCaseDto[];
  onLinkCase?: (pointId: string, testCase: { id: string; current_revision_id: string }, remove?: boolean) => Promise<void>;
  onOpenCase?: (id: string) => void;
  planning: TestPlanningDto;
  generatedPointIds: string[];
  onChooseReuse?: (id: string, choice: "suggested" | "new" | "exclude") => Promise<void>;
  title: string;
  busy: boolean;
  editable: boolean;
  onGenerate: (ids: string[]) => void;
  onSavePoint: (id: string, title: string, scenario: string) => Promise<void>;
}) {
  const surface = useRef<HTMLElement>(null);
  const flow = useRef<ReactFlowInstance | null>(null);
  const canvas = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let frame = 0;
    const fit = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        frame = requestAnimationFrame(() => {
          void flow.current?.fitView({ minZoom: 0.15, maxZoom: 1, padding: 0.12 });
        });
      });
    };
    const observer = new ResizeObserver(fit);
    if (canvas.current) observer.observe(canvas.current);
    document.addEventListener("fullscreenchange", fit);
    return () => { observer.disconnect(); cancelAnimationFrame(frame); document.removeEventListener("fullscreenchange", fit); };
  }, []);
  const [actionFilter, setActionFilter] = useState<PlanningAction | "all">("all");
  const [selected, setSelected] = useState<string[]>([]);
  const [depth, setDepth] = useState(initialPointId ? 20 : 2);
  const [search, setSearch] = useState("");
  const [focused, setFocused] = useState<string | null>(null);
  const [linkCaseId, setLinkCaseId] = useState("");
  const [detailId, setDetailId] = useState<string | null>(initialPointId ?? null);
  const { nodes, edges } = useMemo(() => {
    const nodes: Node[] = [];
    const edges: Edge[] = [];
    const entries = new Map<string, { label: string; level: number; ids: string[]; parent: string | null }>();
    entries.set("root", { label: title, level: 0, ids: [], parent: null });
    const features = new Map(planning.feature_points.map((item) => [item.id, item]));
    const formalPoints = new Set(caseLinks.filter(link => !link.stale).map(link => link.test_point_id));
    const decisionActions = new Map(planning.reuse?.decisions.map(item => [item.point_id, item.action]));
    const actionFor = (id: string) => planning.reuse?.user_choices?.[id] ?? decisionActions.get(id) ?? "new";
    for (const point of planning.test_points) {
      if (actionFilter !== "all" && actionFor(point.id) !== actionFilter) continue;
      const feature = point.feature_point_ids.map((id) => features.get(id)).find(Boolean);
      if (!feature) continue;
      const parts = [...feature.module.split("/").filter(Boolean), feature.name, point.scenario || "业务场景"];
      let parent = "root";
      entries.get(parent)!.ids.push(point.id);
      parts.forEach((label, index) => {
        const id = `${parent}/${encodeURIComponent(label)}`;
        if (!entries.has(id)) entries.set(id, { label, level: index + 1, ids: [], parent });
        entries.get(id)!.ids.push(point.id);
        parent = id;
      });
      entries.set(`point:${point.id}`, { label: point.title, level: parts.length + 1, ids: [point.id], parent });
    }
    const query = search.trim().toLocaleLowerCase();
    const matched = new Set([...entries.values()].filter((entry) => entry.label.toLocaleLowerCase().includes(query)).flatMap((entry) => entry.ids));
    const visible = [...entries].filter(([id, entry]) => {
      const inFocus = !focused || id === "root" || id === focused || entry.ids.some((ref) => entries.get(focused)?.ids.includes(ref));
      return inFocus && (!query || entry.ids.some((ref) => matched.has(ref))) && (query || entry.level <= depth || id === "root");
    });
    const visibleIds = new Set(visible.map(([id]) => id));
    const childrenByParent = new Map<string, string[]>();
    for (const [id, entry] of visible) {
      if (entry.parent) childrenByParent.set(entry.parent, [...(childrenByParent.get(entry.parent) ?? []), id]);
    }
    const selectedIds = new Set(selected);
    let row = 0;
    const positions = new Map<string, number>();
    // Position parents at the center of their descendants, retaining readable labels.
    for (const [id] of [...visible].reverse()) {
      const children = childrenByParent.get(id) ?? [];
      positions.set(id, children.length
        ? children.reduce((sum, child) => sum + (positions.get(child) ?? 0), 0) / children.length
        : row++ * 105);
    }
    for (const [id, entry] of visible) {
      const checked = entry.ids.every((ref) => selectedIds.has(ref));
      nodes.push({ id, position: { x: entry.level * 255, y: positions.get(id) ?? 0 },
        sourcePosition: Position.Right, targetPosition: Position.Left, style: { width: 225 }, data: { label: (
          <div className="planning-node">
            <button type="button" title={entry.label} aria-pressed={checked} disabled={busy}
              onClick={() => { setSelected(checked ? selected.filter((ref) => !entry.ids.includes(ref)) : [...new Set([...selected, ...entry.ids])]); if (id.startsWith("point:")) setDetailId(entry.ids[0]); }}>
              {entry.label}
            </button>
            <small>{id.startsWith("point:") ? (formalPoints.has(entry.ids[0]) ? "测试点 · 已关联正式用例" : generatedPointIds.includes(entry.ids[0]) ? "测试点 · 已加入候选" : planning.reuse ? `测试点 · ${planningActionLabels[actionFor(entry.ids[0])]}` : "测试点 · 待生成") : `${entry.ids.length} 个测试点`}</small>
            {id.startsWith("point:") && <button type="button" aria-label={`查看复用依据：${entry.label}`} onClick={() => setDetailId(entry.ids[0])}>{planning.reuse ? "查看依据与原文" : "查看测试点与关联"}</button>}
            {!id.startsWith("point:") && id !== "root" && <button type="button" onClick={() => { setFocused(id); setDepth(20); }}>聚焦分支</button>}
          </div>
        ) } });
      if (entry.parent && visibleIds.has(entry.parent)) edges.push({ id: `${entry.parent}-${id}`, source: entry.parent, target: id });
    }
    return { nodes, edges };
  }, [planning, title, selected, depth, focused, busy, generatedPointIds, search, actionFilter, caseLinks]);
  const detail = planning.test_points.find((point) => point.id === detailId);
  const summary = consumptionSummary(planning, selected);
  const detailLinks = caseLinks.filter(link => link.test_point_id === detailId);
  const decision = planning.reuse?.decisions.find(item => item.point_id === detailId);
  return <section ref={surface} className="test-planning" aria-label="测试规划脑图">
    <div className="test-planning-toolbar">
      <strong>测试规划 · {planning.test_points.length} 个测试点 · 已关联正式用例 {new Set(caseLinks.filter(link => !link.stale).map(link => link.test_point_id)).size} 个测试点 · {generatedPointIds.length ? `${new Set(generatedPointIds).size} 个已生成候选` : caseLinks.length ? "无待审阅候选" : "尚未生成用例"}</strong>
      <input aria-label="搜索测试规划" placeholder="搜索功能、场景、测试点" value={search} onChange={(event) => setSearch(event.target.value)} />
      {planning.reuse && <label>处理方式 <select aria-label="筛选处理方式" value={actionFilter} onChange={event => { setActionFilter(event.target.value as PlanningAction | "all"); setDepth(20); setFocused(null); }}>
        <option value="all">全部测试点</option>
        {Object.entries(planningActionLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select></label>}
      <label>展开层级 <select aria-label="规划展开层级" value={depth} onChange={(event) => setDepth(Number(event.target.value))}>
        <option value={2}>功能概览</option><option value={3}>业务场景</option><option value={5}>测试点</option><option value={20}>全部层级</option>
      </select></label>
      <button type="button" onClick={() => { setFocused(null); setDepth(2); setSearch(""); setActionFilter("all"); }}>返回全局</button>
      <button type="button" onClick={() => setSelected([])}>清除选择</button>
      <button type="button" onClick={() => { if (document.fullscreenElement) void document.exitFullscreen(); else void surface.current?.requestFullscreen(); }}>切换全屏</button>
      {editable && <button type="button" disabled={busy || !selected.length || !summary.included} onClick={() => onGenerate(selected)}>生成选中范围（{selected.length}）</button>}
    </div>
    {planning.reuse && <p className="planning-consumption-summary" role="status">
      {selected.length ? "选中范围" : "全部范围"}：纳入 {summary.included} 个测试点（直接复用 {summary.reuse} · 修改 {summary.modify} · 新增 {summary.new}），排除 {summary.exclude} 个。
      复用会加入本次候选供审阅，不会覆盖原资产。
    </p>}
    <div className="test-planning-canvas" ref={canvas}>
      <ReactFlow key={`${focused}:${depth}:${search}:${actionFilter}`} nodes={nodes} edges={edges} onInit={(instance) => { flow.current = instance; }} fitView fitViewOptions={{ minZoom: 0.15, maxZoom: 1, padding: 0.12 }} minZoom={0.15} maxZoom={1.5} nodesDraggable={false} nodesConnectable={false}>
        <Background /><Controls showInteractive={false} />
      </ReactFlow>
    </div>
    {detail && editable && <details className="planning-point-edit"><summary>编辑测试点</summary><PlanningPointEditor key={detail.id} point={detail} busy={busy} onSave={onSavePoint} /></details>}
    {detail && <aside className="test-planning-detail" aria-label="测试点详情"><button type="button" onClick={() => setDetailId(null)} aria-label="关闭测试点详情">关闭详情</button><strong>{detail.title}</strong>{!planning.reuse && <p>{planning.feature_points.find((feature) => detail.feature_point_ids.includes(feature.id))?.module} / {planning.feature_points.find((feature) => detail.feature_point_ids.includes(feature.id))?.name} / {detail.scenario} / {detail.title}</p>}<p>{detail.objective}</p>
      <section className="planning-case-links" aria-label="关联用例">
        <strong>关联用例（{detailLinks.length}）</strong>
        <p>关联用于追溯，不会修改用例正文，也不会自动排除生成。已有用例足够覆盖时，可选择“不纳入本次”。</p>
        {detailLinks.length === 0 && <p>尚未关联正式用例，候选采纳后会自动建立关联。</p>}
        <ul>{detailLinks.map(link => <li key={link.test_case_id}>
          <button type="button" onClick={() => onOpenCase?.(link.test_case_id)}>{link.case_key} · {link.title}</button>
          <span>{link.stale ? "版本已变化，需重新确认" : link.origin === "generated" ? "采纳时自动关联" : "手动关联"}</span>
          {editable && onLinkCase && <button type="button" disabled={busy} aria-label={`解除关联：${link.case_key}`} onClick={() => void onLinkCase(detail.id, { id: link.test_case_id, current_revision_id: link.revision_id }, true)}>解除关联</button>}
        </li>)}</ul>
        {editable && onLinkCase && <form onSubmit={event => { event.preventDefault(); const item = existingCases.find(c => c.id === linkCaseId); if (item) void onLinkCase(detail.id, item); }}>
          <label>本集合已有用例 <select aria-label="选择关联已有用例" value={linkCaseId} disabled={busy} onChange={event => setLinkCaseId(event.target.value)}>
            <option value="">请选择用例</option>{existingCases.map(item => <option key={item.id} value={item.id}>{item.case_key} · {item.title}</option>)}
          </select></label><button type="submit" disabled={busy || !linkCaseId}>关联已有用例</button>
        </form>}
      </section>
      {planning.reuse && <div className="planning-reuse-detail">
        <p><strong>建议：{planningActionLabels[decision?.action ?? "new"]}</strong> · {decision?.reason ?? "没有匹配的历史用例"}</p>
        {onChooseReuse && <label>本次处理方式 <select aria-label="本次处理方式" disabled={busy || !editable}
          value={planning.reuse.user_choices?.[detail.id] ?? "suggested"}
          onChange={event => void onChooseReuse(detail.id, event.target.value as "suggested" | "new" | "exclude")}>
          <option value="suggested">使用建议：{planningActionLabels[decision?.action ?? "new"]}</option>
          <option value="new">重新生成，不复用正文</option><option value="exclude">不纳入本次</option>
        </select></label>}
        <p>当前选择：{planningActionLabels[pointAction(planning, detail.id)]}。修改选择会保存为新的规划版本。</p>
        {decision?.source && <details open><summary>历史用例原文 · {decision.source.label} / {decision.source.locator}</summary>
          <p><strong>{decision.source.snapshot?.title}</strong></p>
          <p>前置条件：{decision.source.snapshot?.preconditions.join("；")}</p>
          <ol>{decision.source.snapshot?.steps.map((step, index) => <li key={index}>
            <p>操作：{step.action || "—"}</p><p>预期：{step.expected || "—"}</p>
          </li>)}</ol>
        </details>}
      </div>}
      {detail.source_refs?.map((ref, index) => <p key={index}>{ref.label} {ref.locator}：{ref.excerpt}</p>)}
    </aside>}
  </section>;
}

function PlanningPointEditor({ point, busy, onSave }: {
  point: TestPlanningDto["test_points"][number]; busy: boolean;
  onSave: (id: string, title: string, scenario: string) => Promise<void>;
}) {
  const [title, setTitle] = useState(point.title);
  const [scenario, setScenario] = useState(point.scenario || "");
  return <form className="test-planning-toolbar" onSubmit={(event) => { event.preventDefault(); if (title.trim()) void onSave(point.id, title.trim(), scenario.trim()); }}>
    <label>测试点 <input aria-label="测试点名称" value={title} maxLength={300} onChange={(event) => setTitle(event.target.value)} /></label>
    <label>业务场景 <input aria-label="业务场景名称" value={scenario} maxLength={300} onChange={(event) => setScenario(event.target.value)} /></label>
    <button disabled={busy || !title.trim()} type="submit">保存规划新版本</button>
  </form>;
}
