import assert from "node:assert/strict";
import test from "node:test";

import * as XLSX from "xlsx";

import { parseTestCaseExcel } from "../lib/test-case-excel";

for (const count of [100, 101, 147, 1000]) {
  test(`imports all ${count} rows without truncation`, async () => {
    const result = await parseTestCaseExcel(excelFile([
      ["Test_Case_Name", "Test Procedure", "Test Validation"],
      ...Array.from({ length: count }, (_, i) => [`Case ${i + 1}`, "Act", "Expected"]),
    ]));
    assert.deepEqual(result.errors, []);
    assert.equal(result.totalRows, count);
    assert.equal(result.cases.length, count);
    assert.equal(result.cases.at(-1)?.title, `Case ${count}`);
  });
}

test("reports invalid rows after row 100", async () => {
  const result = await parseTestCaseExcel(excelFile([
    ["Test_Case_Name", "Test Procedure", "Test Validation"],
    ...Array.from({ length: 100 }, (_, i) => [`Case ${i}`, "Act", "Expected"]),
    ["Invalid", "Act", ""],
  ]));
  assert.deepEqual(result.errors, ["第 102 行缺少：Test Validation"]);
});

test("reports the limit when a workbook exceeds 1000 rows", async () => {
  const result = await parseTestCaseExcel(excelFile([
    ["Test_Case_Name", "Test Procedure", "Test Validation"],
    ...Array.from({ length: 1001 }, (_, i) => [`Case ${i}`, "Act", "Expected"]),
  ]));
  assert.equal(result.totalRows, 1001);
  assert.deepEqual(result.errors, ["单次最多导入 1000 条用例，当前有 1001 条"]);
});

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

test("imports optional module columns with English and Chinese headers", async () => {
  for (const header of ["Module", "Feature Module", "模块", "功能模块"]) {
    const result = await parseTestCaseExcel(
      excelFile([
        ["Test_Case_Name", "Test Procedure", "Test Validation", header],
        ["登录", "点击登录", "显示首页", " 账号 / 登录 "],
      ]),
    );
    assert.deepEqual(result.errors, []);
    assert.equal(result.cases[0].module, "账号 / 登录");
  }
});

test("rejects modules longer than the case schema limit", async () => {
  const result = await parseTestCaseExcel(
    excelFile([
      ["Test_Case_Name", "Test Procedure", "Test Validation", "模块"],
      ["登录", "点击登录", "显示首页", "模".repeat(161)],
    ]),
  );
  assert.equal(result.cases.length, 0);
  assert.deepEqual(result.errors, ["第 2 行 Module 超过 160 个字符"]);
});

test("imports Priority and Tag columns with aliases, falling back to Level", async () => {
  for (const [priorityHeader, tagHeader] of [
    ["Priority", "Tag"],
    ["优先级", "Tags"],
    ["Priority", "标签"],
  ]) {
    const result = await parseTestCaseExcel(
      excelFile([
        ["Test_Case_Name", "Test Procedure", "Test Validation", "Level", priorityHeader, tagHeader],
        ["登录", "点击登录", "显示首页", "P2", "High", "冒烟, 登录；冒烟\n 核心"],
        ["退出", "点击退出", "返回首页", "Low", "", ""],
      ]),
    );
    assert.deepEqual(result.errors, []);
    assert.equal(result.cases[0].priority, "P0");
    assert.deepEqual(result.cases[0].tags, ["冒烟", "登录", "核心"]);
    assert.equal(result.cases[1].priority, "P2");
    assert.deepEqual(result.cases[1].tags, []);
  }
});

test("rejects invalid Priority and oversized Tag values", async () => {
  const result = await parseTestCaseExcel(
    excelFile([
      ["Test_Case_Name", "Test Procedure", "Test Validation", "Priority", "Tag"],
      ["登录", "点击登录", "显示首页", "P3", "冒烟"],
      ["退出", "点击退出", "返回首页", "P1", "标签".repeat(17)],
      ["搜索", "输入关键词", "显示结果", "P2", Array.from({ length: 21 }, (_, i) => `tag${i}`).join(",")],
    ]),
  );
  assert.equal(result.cases.length, 0);
  assert.deepEqual(result.errors, [
    "第 2 行 Priority 无法识别：P3",
    "第 3 行 Tag 单项超过 32 个字符",
    "第 4 行 Tag 超过 20 项",
  ]);
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
