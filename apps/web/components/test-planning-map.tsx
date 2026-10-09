"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Background, Controls, Position, ReactFlow, type Node, type Edge, type ReactFlowInstance } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { TestPlanningDto } from "@/lib/casepilot-api";

export function TestPlanningMap({ planning, title, busy, editable, onGenerate, onSavePoint, generatedPointIds }: {
  planning: TestPlanningDto;
  generatedPointIds: string[];
  title: string;
  busy: boolean;
  editable: boolean;
  onGenerate: (ids: string[]) => void;
  onSavePoint: (id: string, title: string, scenario: string) => Promise<void>;
}) {
  const surface = useRef<HTMLElement>(null);
  const flow = useRef<ReactFlowInstance | null>(null);
  useEffect(() => {
    let frame = 0;
    const fit = () => {
      frame = requestAnimationFrame(() => {
        frame = requestAnimationFrame(() => {
          void flow.current?.fitView({ minZoom: 0.65, maxZoom: 1, padding: 0.12 });
        });
      });
    };
    document.addEventListener("fullscreenchange", fit);
    return () => { cancelAnimationFrame(frame); document.removeEventListener("fullscreenchange", fit); };
  }, []);
  const [selected, setSelected] = useState<string[]>([]);
  const [depth, setDepth] = useState(2);
  const [search, setSearch] = useState("");
  const [focused, setFocused] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const { nodes, edges } = useMemo(() => {
    const nodes: Node[] = [];
    const edges: Edge[] = [];
    const entries = new Map<string, { label: string; level: number; ids: string[]; parent: string | null }>();
    entries.set("root", { label: title, level: 0, ids: [], parent: null });
    const features = new Map(planning.feature_points.map((item) => [item.id, item]));
    for (const point of planning.test_points) {
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
            <button type="button" aria-pressed={checked} disabled={busy}
              onClick={() => { setSelected(checked ? selected.filter((ref) => !entry.ids.includes(ref)) : [...new Set([...selected, ...entry.ids])]); if (id.startsWith("point:")) setDetailId(entry.ids[0]); }}>
              {entry.label}
            </button>
            <small>{id.startsWith("point:") ? (generatedPointIds.includes(entry.ids[0]) ? "测试点 · 已生成候选" : "测试点 · 待生成") : `${entry.ids.length} 个测试点`}</small>
            {!id.startsWith("point:") && id !== "root" && <button type="button" onClick={() => { setFocused(id); setDepth(20); }}>聚焦分支</button>}
          </div>
        ) } });
      if (entry.parent && visibleIds.has(entry.parent)) edges.push({ id: `${entry.parent}-${id}`, source: entry.parent, target: id });
    }
    return { nodes, edges };
  }, [planning, title, selected, depth, focused, busy, generatedPointIds, search]);
  const detail = planning.test_points.find((point) => point.id === detailId);
  return <section ref={surface} className="test-planning" aria-label="测试规划脑图">
    <div className="test-planning-toolbar">
      <strong>测试规划 · {planning.test_points.length} 个测试点 · {generatedPointIds.length ? `${new Set(generatedPointIds).size} 个已生成候选` : "尚未生成用例"}</strong>
      <input aria-label="搜索测试规划" placeholder="搜索功能、场景、测试点" value={search} onChange={(event) => setSearch(event.target.value)} />
      <label>展开层级 <select aria-label="规划展开层级" value={depth} onChange={(event) => setDepth(Number(event.target.value))}>
        <option value={2}>功能概览</option><option value={3}>业务场景</option><option value={5}>测试点</option><option value={20}>全部层级</option>
      </select></label>
      <button type="button" onClick={() => { setFocused(null); setDepth(2); setSearch(""); }}>返回全局</button>
      <button type="button" onClick={() => setSelected([])}>清除选择</button>
      <button type="button" onClick={() => { if (document.fullscreenElement) void document.exitFullscreen(); else void surface.current?.requestFullscreen(); }}>切换全屏</button>
      {editable && <button type="button" disabled={busy || !selected.length} onClick={() => onGenerate(selected)}>生成选中范围（{selected.length}）</button>}
    </div>
    <div className="test-planning-canvas">
      <ReactFlow key={`${focused}:${depth}:${search}`} nodes={nodes} edges={edges} onInit={(instance) => { flow.current = instance; }} fitView fitViewOptions={{ minZoom: 0.65, maxZoom: 1, padding: 0.12 }} minZoom={0.15} maxZoom={1.5} nodesDraggable={false} nodesConnectable={false}>
        <Background /><Controls showInteractive={false} />
      </ReactFlow>
    </div>
    {detail && editable && <PlanningPointEditor key={detail.id} point={detail} busy={busy} onSave={onSavePoint} />}
    {detail && <aside className="test-planning-detail"><strong>{detail.title}</strong><p>{planning.feature_points.find((feature) => detail.feature_point_ids.includes(feature.id))?.module} / {planning.feature_points.find((feature) => detail.feature_point_ids.includes(feature.id))?.name} / {detail.scenario} / {detail.title}</p><p>{detail.objective}</p>
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
