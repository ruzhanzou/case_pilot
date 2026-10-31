import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import test from "node:test";
import { PlanningBoundarySamples, PlanningPointSamples } from "../components/planning-point-samples";
import { PlanningCoverageReview } from "../components/planning-coverage-review";
import type { TestPlanningDto, PlanningBoundarySampleDto } from "../lib/casepilot-api";

const source = {label: "原始规则", locator: "requirements:1", excerpt: "持续 60 秒后允许操作。", source_id: "source-id"};
const sample = (position: PlanningBoundarySampleDto["position"], value: number): PlanningBoundarySampleDto => ({
  obligation_id: "batch-local-id", position, value, unit: "秒", axis: "持续时间", time_origin: "计时开始",
  initial_state: "尚未执行操作", assertion: "按明确规则判断是否允许", assertion_role: "primary",
  assertion_feature_id: "FP-main", assertion_source_ref: source,
});
const point = (samples?: PlanningBoundarySampleDto[]): TestPlanningDto["test_points"][number] => ({
  id: "TP-1", title: "计时边界", objective: "检查明确时间边界", feature_point_ids: ["FP-main"],
  ...(samples === undefined ? {} : {boundary_samples: samples}),
});
const render = (value: TestPlanningDto["test_points"][number]) => renderToStaticMarkup(createElement(PlanningPointSamples, {point: value}));

test("legacy missing or empty samples render nothing without altering point content", () => {
  assert.equal(render(point()), ""); assert.equal(render(point([])), "");
  assert.equal(renderToStaticMarkup(createElement(PlanningBoundarySamples, {})), "");
});
test("before/at/after display persisted decimal coordinates, unit, state, assertions and canonical evidence", () => {
  const value = point([sample("before", 59.999), sample("at", 60), sample("after", 60.001)]);
  const before = JSON.stringify(value);
  const html = render(value);
  for (const text of ["阈值前：59.999 秒", "阈值处：60 秒", "阈值后：60.001 秒", "持续时间", "计时开始", "尚未执行操作", "主要断言（功能 FP-main）", "requirements:1", "持续 60 秒后允许操作。", "不代表业务预期正确"]) assert.ok(html.includes(text), text);
  assert.doesNotMatch(html, /<button|<input|PASS|质量通过/);
  assert.equal(JSON.stringify(value), before);
});
test("samples retain explicit feature attribution and use projected units, never batch-local obligation joins", () => {
  const first = {...sample("before", 3), unit: "次", axis: "次数", time_origin: "not_applicable"};
  const second = {...sample("after", 24), assertion_role: "secondary" as const, assertion_feature_id: "FP-secondary"};
  const html = render(point([first, second]));
  assert.match(html, /阈值前：3 次/); assert.match(html, /时间原点（拟议\/待人审）：不适用/);
  assert.match(html, /阈值后：24 秒/); assert.match(html, /关联断言（功能 FP-secondary）/);
  // Same obligation ID deliberately occurs in two different sample coordinate systems.
  assert.equal(first.obligation_id, second.obligation_id);
});
test("text overview and map detail share exactly the same point renderer", () => {
  const value = point([sample("at", 0)]);
  const planning: TestPlanningDto = {feature_points: [], test_points: [point(), value]};
  assert.equal(renderToStaticMarkup(createElement(PlanningBoundarySamples, {planning})), render(value));
  const workbench = readFileSync(new URL("../components/case-workbench.tsx", import.meta.url), "utf8");
  const map = readFileSync(new URL("../components/test-planning-map.tsx", import.meta.url), "utf8");
  assert.match(workbench, /briefView === "text"\) && <PlanningBoundarySamples planning=\{selectedBrief.content.planning\}/);
  assert.match(map, /<PlanningPointSamples point=\{detail\} \/>/);
});
test("sample text is escaped and no additional numeric samples are inferred", () => {
  const html = render(point([{...sample("at", 10.25), quantity_axis_id: "<script>identity()</script>", axis: "<b>axis</b>", time_origin: "<b>origin</b>", assertion: "<script>unsafe()</script>", initial_state: "<b>state</b>"}]));
  assert.match(html, /阈值处：10.25 秒/);
  assert.match(html, /&lt;script&gt;identity\(\)&lt;\/script&gt;/);
  assert.match(html, /&lt;b&gt;axis&lt;\/b&gt;/);
  assert.match(html, /&lt;b&gt;origin&lt;\/b&gt;/);
  assert.match(html, /&lt;script&gt;unsafe\(\)&lt;\/script&gt;/);
  assert.doesNotMatch(html, /阈值前：|阈值后：|<script>|<b>/);
});
test("unverified coordinates remain a visible clarification warning, not an automatic pass", () => {
  const planning: TestPlanningDto = {feature_points: [], test_points: [point()], coverage_review: {
    status: "pending_independent_review", source: "model_proposed", batches: [],
    limits: {max_points: 240, max_batches: 32, max_completion_rounds: 1}, warnings: ["coverage_unverified"],
  }};
  const html = renderToStaticMarkup(createElement(PlanningCoverageReview, {planning}));
  assert.match(html, /取样步长或坐标尚未核实/); assert.match(html, /不能视为已覆盖/);
  assert.doesNotMatch(html, /PASS|质量通过/);
});

test("numeric source identity stays read-only while axis and time origin remain proposed", () => {
  const value = point([{...sample("at", 60), quantity_axis_id: "quantity-axis:server-digest"}]);
  const before = JSON.stringify(value);
  const html = render(value);
  for (const text of ["测量维度（拟议/待人审）：持续时间", "时间原点（拟议/待人审）：计时开始", "数值来源关系标识（只读）", "quantity-axis:server-digest", "仅绑定来源中的数值关系，不代表语义已核实", "不证明测量维度、时间原点或比较关系正确", "requirements:1"]) assert.ok(html.includes(text), text);
  assert.doesNotMatch(html, /<button|<input|<select|PASS|质量通过|已确认|全部覆盖/);
  assert.equal(JSON.stringify(value), before);
  assert.doesNotMatch(render(point([sample("at", 60)])), /数值来源关系标识/);
});

test("source-bound semantics warning keeps the independent-review state and never confirms coverage", () => {
  const planning: TestPlanningDto = {feature_points: [], test_points: [point([{...sample("at", 60), quantity_axis_id: "quantity-axis:server-digest"}])], coverage_review: {
    status: "pending_independent_review", source: "model_proposed", batches: [],
    limits: {max_points: 240, max_batches: 32, max_completion_rounds: 1}, warnings: ["boundary_semantics_requires_review"],
  }};
  const before = JSON.stringify(planning);
  const html = renderToStaticMarkup(createElement(PlanningCoverageReview, {planning}));
  assert.match(html, /数值来源关系已绑定，但测量维度、时间原点、比较关系与业务预期仍为拟议\/待人审/);
  assert.match(html, /不能据此视为已覆盖/);
  assert.match(html, /待独立复核/);
  assert.doesNotMatch(html, /<button|<input|PASS|质量通过|全部覆盖/);
  assert.equal(JSON.stringify(planning), before);
});
