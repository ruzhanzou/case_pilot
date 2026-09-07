import assert from "node:assert/strict";
import test from "node:test";

import * as XLSX from "xlsx";

import { parseTestCaseExcel } from "../lib/test-case-excel";

function excelFile(rows: unknown[][], name = "cases.xlsx") {
  const sheet = XLSX.utils.aoa_to_sheet(rows);
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, sheet, "Cases");
  const bytes = XLSX.write(workbook, { type: "array", bookType: "xlsx" });
  return new File([bytes], name);
}

test("parses required fields and pairs multiline procedures with validations", async () => {
  const result = await parseTestCaseExcel(
    excelFile([
      [
        "Test_Case_Name",
        "Test Setup",
        "Test Procedure",
        "Test Validation",
        "Level",
      ],
      [
        "账号密码登录成功",
        "1. 打开登录页\n2. 已有可用账号",
        "1. 输入账号密码\n2. 点击登录",
        "1. 表单接受输入\n2. 进入首页",
        "High",
      ],
    ]),
  );

  assert.deepEqual(result.errors, []);
  assert.equal(result.sheetName, "Cases");
  assert.equal(result.cases.length, 1);
  assert.equal(result.cases[0].title, "账号密码登录成功");
  assert.equal(result.cases[0].priority, "P0");
  assert.deepEqual(result.cases[0].preconditions, ["打开登录页", "已有可用账号"]);
  assert.deepEqual(result.cases[0].steps, [
    { action: "输入账号密码", expected: "表单接受输入" },
    { action: "点击登录", expected: "进入首页" },
  ]);
});

test("reports missing required columns", async () => {
  const result = await parseTestCaseExcel(
    excelFile([["Test_Case_Name", "Test Procedure"], ["登录", "点击登录"]]),
  );

  assert.equal(result.cases.length, 0);
  assert.deepEqual(result.errors, ["缺少必填列：Test Validation"]);
});

test("reports row-level required values and unsupported levels", async () => {
  const result = await parseTestCaseExcel(
    excelFile([
      ["Test_Case_Name", "Test Procedure", "Test Validation", "Level"],
      ["缺少校验", "点击提交", "", "P1"],
      ["非法级别", "点击提交", "显示成功", "P3"],
    ]),
  );

  assert.equal(result.cases.length, 0);
  assert.deepEqual(result.errors, [
    "第 2 行缺少：Test Validation",
    "第 3 行 Level 无法识别：P3",
  ]);
});
