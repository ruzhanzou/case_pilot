import assert from "node:assert/strict";
import test from "node:test";
import * as XLSX from "xlsx";
import type { ExecutionRunDto, ExecutionRunSummaryDto, TestCaseDto } from "../lib/casepilot-api";
import { createCaseWorkbook, createExecutionWorkbook, createExecutionSummaryWorkbook, excelFileName } from "../lib/excel-export";
import { parseTestCaseExcel } from "../lib/test-case-excel";

const testCase: TestCaseDto = {
  id: "case-1", case_key: "TC-001", collection_ids: ["collection-1"],
  current_revision_id: "rev-1", revision_number: 2,
  title: "中文登录验证", description: "覆盖登录\n和退出", module: "账号/登录",
  priority: "P0", case_type: "功能", tags: ["回归", "冒烟"],
  preconditions: ["账号有效", "已联网"],
  steps: [{ id: "s1", action: "输入账号", expected: "显示账号" }, { id: "s2", action: "提交", expected: "登录成功" }],
  source: "需求文档", source_refs: [], created_at: "2026-10-09T01:00:00Z",
};
const run: ExecutionRunDto = {
  id: "run-1", collection_id: null, collection_name: null,
  playlist_id: "playlist-1", source_type: "playlist", source_name: "登录回归", source_collection_count: 2,
  description: "发布前检查", status: "completed", creator_name: "张三", creator_id: "user-1",
  assignee_ids: ["user-2"], assignee_names: ["李四"], can_manage: false, contributor_names: ["李四"],
  created_at: "2026-10-09T01:00:00Z", last_activity_at: "2026-10-09T02:00:00Z", completed_at: "2026-10-09T02:00:00Z",
  records: [{ id: "record-1", test_case: testCase, status: "failed", completed_step_ids: ["s1"],
    actual_result: "页面报错\n错误码 500", defect_ref: "https://example.test/BUG-1", assignee_id: "user-2", assignee_name: "李四",
    can_edit: false, updated_by_name: "李四", updated_at: "2026-10-09T02:00:00Z" }],
};

function reopen(workbook: XLSX.WorkBook) {
  return XLSX.read(XLSX.write(workbook, { bookType: "xlsx", type: "buffer" }), { type: "buffer" });
}

test("asset export preserves all 1001 cases and writes formula-like titles as text", async () => {
  const cases = Array.from({ length: 1001 }, (_, i) => ({ ...testCase, case_key: `TC-${i}`, title: i === 1000 ? '=HYPERLINK("https://example.test")' : testCase.title }));
  const workbook = reopen(await createCaseWorkbook(cases));
  const sheet = workbook.Sheets["用例资产"];
  const rows = XLSX.utils.sheet_to_json(sheet);
  assert.equal(rows.length, 1001);
  assert.equal(sheet.B1002.t, "s");
  assert.equal(sheet.B1002.f, undefined);
  assert.equal(sheet.B1002.v, cases[1000].title);
});

test("exported case columns remain compatible with the existing Excel importer", async () => {
  const workbook = await createCaseWorkbook([testCase]);
  const bytes = XLSX.write(workbook, { type: "array", bookType: "xlsx" });
  const preview = await parseTestCaseExcel(new File([bytes], "用例.xlsx"));
  assert.deepEqual(preview.errors, []);
  const imported = preview.cases[0];
  for (const key of ["title", "description", "module", "priority", "tags", "preconditions"] as const) {
    assert.deepEqual(imported[key], testCase[key]);
  }
  assert.deepEqual(imported.steps, testCase.steps.map(({ action, expected }) => ({ action, expected })));
});

test("execution export includes saved results, assignment, defects and task context", async () => {
  const workbook = reopen(await createExecutionWorkbook(run));
  assert.deepEqual(workbook.SheetNames, ["执行用例", "任务信息"]);
  const rows = XLSX.utils.sheet_to_json<Record<string, unknown>>(workbook.Sheets["执行用例"]);
  assert.equal(rows[0]["执行状态"], "不通过");
  assert.equal(rows[0]["执行人"], "李四");
  assert.equal(rows[0]["实际结果"], run.records[0].actual_result);
  assert.equal(rows[0]["缺陷链接"], run.records[0].defect_ref);
  assert.equal(rows[0]["已完成步骤数"], 1);
  const info = XLSX.utils.sheet_to_json<Record<string, unknown>>(workbook.Sheets["任务信息"])[0];
  assert.equal(info["任务编号"], run.id);
  assert.equal(info["任务状态"], "已完成");
});

test("summary export includes numeric result counts and empty workbooks stay readable", async () => {
  const summary: ExecutionRunSummaryDto = { ...run, total_count: 5, not_run_count: 1, passed_count: 1, failed_count: 1, skipped_count: 1, blocked_count: 1 };
  const workbook = reopen(await createExecutionSummaryWorkbook([summary]));
  const rows = XLSX.utils.sheet_to_json<Record<string, unknown>>(workbook.Sheets["执行任务"]);
  assert.equal(rows[0]["用例数"], 5);
  assert.equal(rows[0]["堵塞"], 1);
  const empty = reopen(await createCaseWorkbook([]));
  assert.deepEqual(XLSX.utils.sheet_to_json(empty.Sheets["用例资产"]), []);
});

test("download names remove illegal path characters and have one xlsx suffix", () => {
  assert.equal(excelFileName('登录/检查:任务?'), "登录_检查_任务_.xlsx");
  assert.equal(excelFileName(" . "), "export.xlsx");
  assert.ok(excelFileName("长".repeat(200)).length <= 105);
});
