import type { TestPlanningDto } from "../lib/casepilot-api";

const dimensions = { normal: "正常路径", boundary: "边界条件", exception: "例外与拒绝", state: "状态变化" };
const warningLabels: Record<string, string> = {
  retained_previous_point_coverage: "保留的历史测试点沿用其原证据与取样快照；不表示新需求已覆盖，也不授权新测试点沿用旧取样设置。",
  boundary_semantics_requires_review: "数值来源关系已绑定，但测量维度、时间原点、比较关系与业务预期仍为拟议/待人审；不能据此视为已覆盖。",
  coverage_not_assessed: "尚未提出覆盖检查项，不能据此判断规则是否完整覆盖。",
  coverage_budget_limited: "指定数量限制阻止追加测试点；未覆盖项仍需复核，请明确取舍或调整数量后再补充。",
  coverage_gap_remaining: "本轮补充后仍有覆盖缺口，或已达到补充上限；未覆盖项仍需人工处理。",
  coverage_scope_limit: "本次规划达到范围或批次上限，未处理范围仍需另行检查。",
  coverage_unverified: "边界样例的取样步长或坐标尚未核实，不能视为已覆盖；请先核对原始规则并澄清缺失信息。",
};

/** Model bookkeeping is a review aid, not an independent quality verdict. */
export function PlanningCoverageReview({ planning }: { planning?: TestPlanningDto }) {
  const review = planning?.coverage_review;
  if (!review) return null;
  const warnings = [...new Set([...review.warnings, ...review.batches.flatMap(batch => batch.warnings ?? [])])];
  const gaps = review.batches.flatMap(batch => batch.uncovered_ids.map(id => ({
    batch: batch.batch_index, id, obligation: batch.obligations.find(item => item.id === id),
  })));
  const clarifications = [...new Set(review.batches.flatMap(batch => [
    ...batch.clarifications, ...batch.obligations.map(item => item.clarification),
  ]).filter(text => text.trim()))];
  const duplicates = review.batches.flatMap(batch => batch.duplicate_suggestions.map((item, index) => ({
    ...item, key: `${batch.batch_index}:${index}`,
  })));
  const pointTitles = new Map(planning.test_points.map(point => [point.id, point.title]));
  return <section className="planning-coverage-summary" aria-label="模型覆盖建议，待独立复核">
    <strong>模型覆盖建议 · 待独立复核</strong>
    <p>以下检查项与关联由模型提出，不是质量验收结论。已有测试点关联也不代表业务规则已充分验证，请结合原始需求逐项审阅。</p>
    <p>模型标记待补充 {gaps.length} 项 · 待澄清 {clarifications.length} 项</p>
    {warnings.length > 0 && <ul aria-label="覆盖检查限制">{warnings.map(code => <li key={code}>
      {warningLabels[code] ?? "存在未识别的覆盖检查提示，请人工复核原始需求与规划。"}
    </li>)}</ul>}
    {gaps.length > 0 && <details open><summary>查看未覆盖检查项</summary><ul>{gaps.map(({batch, id, obligation}) => <li key={`${batch}:${id}`}>
      <strong>{obligation ? dimensions[obligation.dimension] : "待补充"} · {id}</strong>
      {obligation ? <p>依据：{obligation.basis}</p> : <p>该检查项依据未提供，请重新核对规划。</p>}
    </li>)}</ul></details>}
    {clarifications.length > 0 && <details open><summary>需要澄清的规则</summary>
      <p>信息不足时不应自行补充业务预期，请先确认规则。</p>
      <ul>{clarifications.map(text => <li key={text}>{text}</li>)}</ul>
    </details>}
    {duplicates.length > 0 && <details><summary>疑似重复建议 · 仅供人工复核（{duplicates.length}）</summary>
      <p>不会自动合并或删除测试点。不同阈值边界、状态前提或预期结果必须分别保留；标题相似不能作为删除依据。</p>
      <ul>{duplicates.map(item => <li key={item.key}>
        <strong>{item.point_ids.map(id => `${id} · ${pointTitles.get(id) ?? "测试点暂不可定位"}`).join("；")}</strong>
        <p>{item.reason}</p>
      </li>)}</ul>
    </details>}
  </section>;
}
