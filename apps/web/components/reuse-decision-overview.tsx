"use client";

import { useState } from "react";
import type { TestPlanningDto } from "@/lib/casepilot-api";
import { pointAction } from "@/lib/planning-consumption";
import { useI18n } from "@/lib/i18n";

export function ReuseDecisionOverview({ planning, onInspect }: { planning: TestPlanningDto; onInspect: (id: string) => void }) {
  const { pick } = useI18n();
  const [filter, setFilter] = useState("all");
  const labels = { reuse: pick("Direct reuse", "直接复用"), modify: pick("Adapt", "需要改写"), new: pick("Generate new", "全新生成"), copy: pick("Copy original", "复制原文"), exclude: pick("Excluded", "不纳入"), pending: pick("Pending decision", "待判断") };
  const rows = planning.test_points.map(point => {
    const decision = planning.reuse?.decisions.find(item => item.point_id === point.id);
    const choice = planning.reuse?.user_choices?.[point.id];
    const action: keyof typeof labels = decision || choice ? pointAction(planning, point.id) : "pending";
    return { point, decision, action, reason: choice ? pick("User override; open details to compare the model suggestion.", "用户已调整处理方式，可查看原建议与依据。") : decision?.reason ?? pick("No decision has been recorded yet.", "尚未记录处理判断。") };
  });
  return <section className="reuse-decision-overview" aria-label={pick("Reuse decisions", "复用处理建议")}>
    <strong>{pick("Review how each test point will be handled", "确认每个测试点如何处理")}</strong>
    <p>{pick("Direct reuse keeps the original content. Adaptation creates a reviewable proposal. New cases use the current requirements. Source assets stay unchanged.", "直接复用保留原文；改写会生成可审阅的新建议；新增依据当前需求生成。来源资产不会被修改。")}</p>
    <div className="reuse-decision-filters" role="group" aria-label={pick("Filter decisions", "筛选处理建议")}>
      <button type="button" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>{pick("All", "全部")} · {rows.length}</button>
      {Object.entries(labels).map(([action, label]) => { const count = rows.filter(row => row.action === action).length; return count ? <button type="button" key={action} aria-pressed={filter === action} onClick={() => setFilter(action)}>{label} · {count}</button> : null; })}
    </div>
    <div className="reuse-decision-rows">
      {rows.filter(row => filter === "all" || row.action === filter).map(({ point, decision, action, reason }) => <article key={point.id}>
        <div><strong>{point.title}</strong><span>{labels[action]}</span></div>
        <p>{reason}</p>
        {decision?.source && <small>{pick("Source: ", "来源：")}{decision.source.collections?.map(collection => collection.name).join("、") || decision.source.label} · {decision.source.locator}</small>}
        <button type="button" onClick={() => onInspect(point.id)}>{pick("Inspect source and adjust", "查看依据与调整")}</button>
      </article>)}
    </div>
  </section>;
}
