import type { TestPlanningDto } from "../lib/casepilot-api";

const positionLabels = { before: "阈值前", at: "阈值处", after: "阈值后" };
const roleLabels = { primary: "主要断言", secondary: "关联断言" };

/** Display server-persisted coordinates; never derive values or join batch-local obligation IDs. */
export function PlanningPointSamples({ point }: { point: TestPlanningDto["test_points"][number] }) {
  if (!point.boundary_samples?.length) return null;
  return <section className="planning-coverage-summary" aria-label={`${point.title}的结构化边界样例`}>
    <strong>{point.title} · 结构化边界样例 · 待复核</strong>
    <p>以下为已保存的样例与断言。数值和来源关联检查不代表业务预期正确，也不证明测量维度、时间原点或比较关系正确；请对照原始需求人工审阅。</p>
    <ul>{point.boundary_samples.map((sample, index) => <li key={`${point.id}:${index}`}>
      <strong>{positionLabels[sample.position]}：{sample.value} {sample.unit}</strong>
      <p>测量维度（拟议/待人审）：{sample.axis} · 时间原点（拟议/待人审）：{sample.time_origin === "not_applicable" ? "不适用" : sample.time_origin}</p>
      {sample.quantity_axis_id ? <p>数值来源关系标识（只读）：<code>{sample.quantity_axis_id}</code> · 仅绑定来源中的数值关系，不代表语义已核实。</p> : null}
      <p>初始状态：{sample.initial_state}</p>
      <p>{roleLabels[sample.assertion_role]}（功能 {sample.assertion_feature_id}）：{sample.assertion}</p>
      <details><summary>断言依据 · 检查项 {sample.obligation_id}</summary>
        <p>{sample.assertion_source_ref.label} {sample.assertion_source_ref.locator}</p>
        <p>{sample.assertion_source_ref.excerpt}</p>
      </details>
    </li>)}</ul>
  </section>;
}

export function PlanningBoundarySamples({ planning }: { planning?: TestPlanningDto }) {
  return <>{planning?.test_points.filter(point => point.boundary_samples?.length)
    .map(point => <PlanningPointSamples key={point.id} point={point} />)}</>;
}
