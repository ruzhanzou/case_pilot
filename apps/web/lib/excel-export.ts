import type { ExecutionRunDto, ExecutionRunSummaryDto, TestCaseDto } from "@/lib/casepilot-api";
import type { WorkBook } from "xlsx";

type Row = Record<string, string | number>;

function caseRow(item: TestCaseDto): Row {
  return {
    "用例编号": item.case_key,
    Test_Case_Name: item.title,
    "Case Description": item.description ?? "",
    Module: item.module,
    Priority: item.priority,
    "用例类型": item.case_type,
    Tag: item.tags.join("; "),
    "Test Setup": item.preconditions.join("\n"),
    "Test Procedure": item.steps.map((step, index) => `${index + 1}. ${step.action}`).join("\n"),
    "Test Validation": item.steps.map((step, index) => `${index + 1}. ${step.expected}`).join("\n"),
    "来源": item.source,
    "创建人": item.creator?.display_name ?? "",
    "创建时间": item.created_at,
    "版本": item.revision_number,
  };
}

async function workbookFromSheets(sheets: { name: string; rows: Row[] }[]) {
  const XLSX = await import("xlsx");
  const workbook = XLSX.utils.book_new();
  for (const { name, rows } of sheets) {
    const sheet = XLSX.utils.json_to_sheet(rows);
    const headers = Object.keys(rows[0] ?? {});
    sheet["!cols"] = headers.map((header) => ({ wch: /Procedure|Validation|Description|实际结果|描述/.test(header) ? 60 : 24 }));
    if (sheet["!ref"]) sheet["!autofilter"] = { ref: sheet["!ref"] };
    XLSX.utils.book_append_sheet(workbook, sheet, name);
  }
  return workbook;
}

export function createCaseWorkbook(cases: TestCaseDto[]) {
  return workbookFromSheets([{ name: "用例资产", rows: cases.map(caseRow) }]);
}

const statuses: Record<string, string> = {
  active: "执行中", completed: "已完成", aborted: "已终止",
  not_run: "未执行", passed: "通过", failed: "不通过", skipped: "跳过", blocked: "堵塞",
};

function runRow(run: ExecutionRunDto | ExecutionRunSummaryDto): Row {
  return {
    "任务编号": run.id, "任务描述": run.description, "来源": run.source_name,
    "任务状态": statuses[run.status] ?? run.status, "创建人": run.creator_name,
    "执行人": run.assignee_names.join("、"), "创建时间": run.created_at,
    "最近活动时间": run.last_activity_at, "完成时间": run.completed_at ?? "",
  };
}

export function createExecutionWorkbook(run: ExecutionRunDto) {
  return workbookFromSheets([
    { name: "执行用例", rows: run.records.map((record) => ({
      ...caseRow(record.test_case),
      "执行状态": statuses[record.status] ?? record.status,
      "执行人": record.assignee_name ?? "",
      "实际结果": record.actual_result,
      "缺陷链接": record.defect_ref,
      "已完成步骤数": record.completed_step_ids.length,
      "更新人": record.updated_by_name ?? "",
      "更新时间": record.updated_at,
    })) },
    { name: "任务信息", rows: [{ ...runRow(run), "用例数": run.records.length }] },
  ]);
}

export function createExecutionSummaryWorkbook(runs: ExecutionRunSummaryDto[]) {
  return workbookFromSheets([{ name: "执行任务", rows: runs.map((run) => ({
    ...runRow(run), "用例数": run.total_count, "未执行": run.not_run_count,
    "通过": run.passed_count, "不通过": run.failed_count,
    "跳过": run.skipped_count, "堵塞": run.blocked_count,
  })) }]);
}

export function excelFileName(name: string) {
  const safeName = name.replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_").replace(/[. ]+$/g, "").trim().slice(0, 100) || "export";
  return `${safeName}.xlsx`;
}

export async function downloadExcel(workbook: WorkBook, name: string) {
  const XLSX = await import("xlsx");
  XLSX.writeFile(workbook, excelFileName(name), { bookType: "xlsx", compression: true });
}
