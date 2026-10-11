import assert from "node:assert/strict";
import test from "node:test";
import { matchesExecutionFilters, type ExecutionFilter } from "../lib/execution-filters";
import type { ExecutionRecordDto } from "../lib/casepilot-api";
const record = {
  test_case: { title: "登录 Smoke 回归", case_key: "TC-001", module: "账户", priority: "P0", tags: ["登录", "smoke"], case_type: "functional" },
  status: "not_run", assignee_name: null, actual_result: "", defect_ref: "BUG-12",
} as ExecutionRecordDto;
const filter = (field: ExecutionFilter["field"], value: string, operator: ExecutionFilter["operator"] = "contains"): ExecutionFilter => ({ id: 1, field, value, operator });
test("contains normalizes Unicode and case, keeps phrases and literal characters", () => {
  assert.equal(matchesExecutionFilters(record, [filter("title", " ＳＭＯＫＥ ")], "and"), true);
  assert.equal(matchesExecutionFilters(record, [filter("title", "登录 Smoke")], "and"), true);
  assert.equal(matchesExecutionFilters(record, [filter("title", "%")], "and"), false);
});
test("multiple filters combine with AND or OR; empty conditions never match on their own", () => {
  const filters = [filter("title", "登录"), filter("priority", "P1", "equals")];
  assert.equal(matchesExecutionFilters(record, filters, "and"), false);
  assert.equal(matchesExecutionFilters(record, filters, "or"), true);
  assert.equal(matchesExecutionFilters(record, [filter("title", "missing"), filter("title", "  ")], "or"), false);
  for (const mode of ["and", "or"] as const) {
    assert.equal(matchesExecutionFilters(record, [], mode), true);
    assert.equal(matchesExecutionFilters(record, [filter("title", " ", "not_contains")], mode), true);
  }
});
test("negative operators, exact equality, arrays, and nullable assignee", () => {
  for (const [condition, expected] of [
    [filter("title", "登录", "not_contains"), false],
    [filter("title", "注册", "not_contains"), true],
    [filter("priority", "P", "equals"), false],
    [filter("priority", "P1", "not_equals"), true],
    [filter("tags", "SMOKE", "equals"), true],
    [filter("tags", "smoke", "not_contains"), false],
    [filter("assignee_name", "张三", "contains"), false],
    [filter("assignee_name", "张三", "not_contains"), true],
    [filter("status", "not_run", "equals"), true],
    [filter("defect_ref", "BUG-12", "equals"), true],
  ] as const) assert.equal(matchesExecutionFilters(record, [condition], "and"), expected);
});
