import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import test from "node:test";
import { PlanningCoverageReview } from "../components/planning-coverage-review";
import type { TestPlanningDto, PlanningCoverageReviewDto } from "../lib/casepilot-api";

const batch = (): PlanningCoverageReviewDto["batches"][number] => ({
  batch_index: 0,
  obligations: [
    {id: "boundary", feature_point_ids: ["f1"], dimension: "boundary", basis: "上限为 10，小于、等于、大于分别核验", point_ids: [], clarification: ""},
    {id: "state", feature_point_ids: ["f1"], dimension: "state", basis: "规则提到重置", point_ids: [], clarification: "何时重置计数？"},
  ],
  uncovered_ids: ["boundary"], clarifications: ["何时重置计数？"],
  duplicate_suggestions: [], completion_attempted: true, warnings: [],
});
const planning = (overrides: Partial<PlanningCoverageReviewDto> = {}): TestPlanningDto => ({
  feature_points: [], test_points: [{id: "p1", title: "小于阈值", objective: "边界", feature_point_ids: ["f1"]}],
  coverage_review: {status: "pending_independent_review", source: "model_proposed", batches: [batch()],
    limits: {max_points: 240, max_batches: 32, max_completion_rounds: 1}, warnings: [], ...overrides},
});
const render = (value?: TestPlanningDto) => renderToStaticMarkup(createElement(PlanningCoverageReview, {planning: value}));

test("legacy or absent planning adds no misleading assessment", () => {
  assert.equal(render(), "");
  assert.equal(render({feature_points: [], test_points: []}), "");
});
test("unmet obligations and deduplicated clarification are visible as model suggestions", () => {
  const html = render(planning());
  assert.match(html, /模型覆盖建议 · 待独立复核/);
  assert.match(html, /不是质量验收结论/);
  assert.match(html, /模型标记待补充 1 项 · 待澄清 1 项/);
  assert.match(html, /边界条件 · boundary/);
  assert.match(html, /上限为 10，小于、等于、大于分别核验/);
  assert.match(html, /何时重置计数？/);
  assert.match(html, /<details open=""><summary>需要澄清的规则/);
  assert.doesNotMatch(html, /<button|<input|PASS|质量通过|疑似重复建议/);
});
test("exact budget and bounded completion warnings retain explicit gaps", () => {
  const value = planning({warnings: ["coverage_scope_limit"]});
  value.coverage_review!.batches[0].warnings = ["coverage_budget_limited", "coverage_gap_remaining", "coverage_not_assessed"];
  const html = render(value);
  for (const text of ["指定数量限制阻止追加测试点", "仍有覆盖缺口", "尚未提出覆盖检查项", "达到范围或批次上限", "查看未覆盖检查项"]) assert.ok(html.includes(text));
});
test("all model-linked points still require independent review, never a quality pass", () => {
  const value = planning();
  const entry = value.coverage_review!.batches[0];
  entry.obligations = [{...entry.obligations[0], point_ids: ["p1"]}];
  entry.uncovered_ids = []; entry.clarifications = [];
  const html = render(value);
  assert.match(html, /待独立复核/);
  assert.match(html, /已有测试点关联也不代表业务规则已充分验证/);
  assert.doesNotMatch(html, /查看未覆盖检查项|需要澄清的规则|PASS|全部覆盖|质量通过|评分/);
});
test("duplicate suggestions appear only when provided and never offer automatic mutation", () => {
  const value = planning();
  value.coverage_review!.batches[0].duplicate_suggestions = [{point_ids: ["p1", "p2"], reason: "相同前提、输入和预期，仍需核对"}];
  const before = JSON.stringify(value);
  const html = render(value);
  assert.match(html, /疑似重复建议 · 仅供人工复核（1）/);
  assert.match(html, /p1 · 小于阈值/);
  assert.match(html, /p2 · 测试点暂不可定位/);
  assert.match(html, /不同阈值边界、状态前提或预期结果必须分别保留/);
  assert.doesNotMatch(html, /<button|<form|<input/);
  assert.equal(JSON.stringify(value), before);
});
test("unknown warning cannot inject a quality verdict and text stays escaped", () => {
  const value = planning({warnings: ["PASS"]});
  value.coverage_review!.batches[0].obligations[0].basis = "<script>bad()</script>";
  const html = render(value);
  assert.match(html, /未识别的覆盖检查提示/);
  assert.match(html, /&lt;script&gt;bad\(\)&lt;\/script&gt;/);
  assert.doesNotMatch(html, /PASS|<script>/);
});
test("shared brief renders review outside map/text condition; standalone map retains its panel", () => {
  const source = readFileSync(new URL("../components/case-workbench.tsx", import.meta.url), "utf8");
  const map = readFileSync(new URL("../components/test-planning-map.tsx", import.meta.url), "utf8");
  const panel = source.indexOf("<PlanningCoverageReview planning={selectedBrief.content.planning} />");
  const mapStart = source.indexOf('{briefView === "map" && !!selectedBrief.content.planning?.test_points?.length && <TestPlanningMap');
  assert.ok(panel > 0 && panel < mapStart);
  assert.equal(source.match(/<PlanningCoverageReview /g)?.length, 1);
  assert.match(source.slice(mapStart), /showCoverageReview=\{false\}/);
  assert.match(map, /showCoverageReview = true/);
  assert.match(map, /showCoverageReview && <PlanningCoverageReview planning=\{planning\}/);
});
