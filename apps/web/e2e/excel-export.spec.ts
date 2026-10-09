import { expect, test, type Page, type APIRequestContext } from "@playwright/test";
import * as XLSX from "xlsx";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const api = process.env.CASEPILOT_E2E_API_URL ?? "http://localhost:8000";
const artifacts = path.resolve("../../artifacts/excel-export-e2e");
test.use({ viewport: { width: 1600, height: 1000 } });

async function post(request: APIRequestContext, endpoint: string, data: unknown) {
  const response = await request.post(`${api}/api/v1${endpoint}`, { data });
  expect(response.ok(), `${endpoint}: ${await response.text()}`).toBeTruthy();
  return response.json();
}
async function download(page: Page, file: string) {
  const pending = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出 Excel", exact: true }).click();
  const result = await pending;
  expect(result.suggestedFilename()).toMatch(/\.xlsx$/);
  expect(await result.failure()).toBeNull();
  await result.saveAs(path.join(artifacts, file));
  return XLSX.read(await readFile(path.join(artifacts, file)), { type: "buffer" });
}

test("真实接口：用例资产和执行任务下载 Excel、分页完整性与失败重试", async ({ page, request }) => {
  test.setTimeout(120_000);
  page.setDefaultTimeout(15_000);
  await mkdir(artifacts, { recursive: true });
  const email = `excel-e2e-${Date.now()}@casepilot.local`;
  const password = "ExcelExport2026!";
  const account = await post(request, "/auth/register", { email, password, display_name: "Excel导出验收" });
  const collection = await post(request, `/spaces/${account.spaces[0].id}/collections`, {
    name: "Excel导出验收 · 登录与权限", description: "25 条真实用例，验证跨页导出、中文、多步骤及执行结果。",
  });
  const cases = await post(request, `/collections/${collection.id}/test-cases/batch`, {
    cases: Array.from({ length: 25 }, (_, i) => ({
      title: `登录与权限校验 ${String(i + 1).padStart(2, "0")}`,
      description: "验证账号登录与页面权限\n包含正常及异常路径", module: i < 15 ? "账号/登录" : "账号/权限",
      priority: i % 3 === 0 ? "P0" : "P1", case_type: "功能", tags: ["Excel验收", "回归"],
      preconditions: ["存在有效的测试账号", "测试环境可访问"],
      steps: [{ action: "输入账号和密码", expected: "输入框正常显示" }, { action: "点击登录", expected: "进入工作台并显示正确权限" }],
    })),
  });
  const run = await post(request, `/collections/${collection.id}/execution-runs`, {
    description: "Excel导出验收 · 发布前回归", assignee_ids: [account.id],
  });
  for (const [i, status] of ["failed", "passed", "blocked", "skipped"].entries()) {
    const response = await request.patch(`${api}/api/v1/execution-records/${run.records[i].id}`, { data: {
      status, actual_result: i === 0 ? "登录后页面报错\n错误码 500" : "验收执行记录",
      defect_ref: i === 0 ? "BUG-EXCEL-001" : "", completed_step_ids: [run.records[i].test_case.steps[0].id],
      base_updated_at: run.records[i].updated_at,
    } });
    expect(response.ok(), await response.text()).toBeTruthy();
  }
  await page.addInitScript(() => localStorage.setItem("casepilot.locale.v1", "zh-CN"));
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const failures: string[] = [];
  page.on("response", response => {
    if (response.url().startsWith(api) && response.status() >= 500) failures.push(`${response.status()} ${response.url()}`);
  });
  await page.goto("/");
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "登录并进入工作台" }).click();
  await expect(page.getByRole("heading", { name: "今天想测试什么？" })).toBeVisible();
  await page.goto(`/cases/${collection.id}`);
  await expect(page.locator(".case-table tbody tr")).toHaveCount(20);
  const assetBook = await download(page, "用例资产.xlsx");
  const assetRows = XLSX.utils.sheet_to_json<Record<string, unknown>>(assetBook.Sheets["用例资产"]);
  expect(assetRows).toHaveLength(25);
  expect(assetRows[24].Test_Case_Name).toBe(cases[24].title);
  expect(assetRows[0]["Test Procedure"]).toBe("1. 输入账号和密码\n2. 点击登录");
  await page.screenshot({ path: path.join(artifacts, "01-case-assets.png"), fullPage: true });
  await page.getByLabel("搜索用例资产").fill(cases[0].case_key);
  await expect(page.locator(".case-table tbody tr")).toHaveCount(1);
  const filteredBook = await download(page, "资产搜索后仍导出全部.xlsx");
  expect(XLSX.utils.sheet_to_json(filteredBook.Sheets["用例资产"])).toHaveLength(25);
  // Only the failure branch is injected; successful downloads use the real API.
  const endpoint = `${api}/api/v1/collections/${collection.id}/test-cases`;
  await page.route(endpoint, route => route.abort(), { times: 1 });
  await page.getByRole("button", { name: "导出 Excel", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText("导出失败，请重试。");
  await page.screenshot({ path: path.join(artifacts, "04-export-error.png"), fullPage: true });
  await download(page, "失败后重试.xlsx");
  await expect(page.getByRole("alert")).toHaveCount(0);

  await page.goto("/executions");
  await expect(page.locator(".execution-task-card")).toHaveCount(1);
  const summary = await download(page, "执行任务汇总.xlsx");
  const summaryRows = XLSX.utils.sheet_to_json<Record<string, unknown>>(summary.Sheets["执行任务"]);
  expect(summaryRows).toHaveLength(1);
  expect(summaryRows[0]["用例数"]).toBe(25);
  expect(summaryRows[0]["不通过"]).toBe(1);
  await page.screenshot({ path: path.join(artifacts, "02-execution-summary.png"), fullPage: true });
  await page.locator(".execution-task-card__open").click();
  await expect(page.getByRole("heading", { name: run.description })).toBeVisible();
  const execution = await download(page, "执行任务详情.xlsx");
  const results = XLSX.utils.sheet_to_json<Record<string, unknown>>(execution.Sheets["执行用例"]);
  expect(results).toHaveLength(25);
  expect(results.slice(0, 5).map(row => row["执行状态"])).toEqual(["不通过", "通过", "堵塞", "跳过", "未执行"]);
  expect(results[0]["实际结果"]).toBe("登录后页面报错\n错误码 500");
  expect(results[0]["缺陷链接"]).toBe("BUG-EXCEL-001");
  expect(results[0]["执行人"]).toBe("Excel导出验收");
  await page.screenshot({ path: path.join(artifacts, "03-execution-detail.png"), fullPage: true });
  await page.getByRole("textbox", { name: /^实际结果/ }).fill("更新后的实际结果：已复测");
  await expect(page.getByRole("button", { name: "导出 Excel", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "保存执行记录", exact: true }).click();
  await expect(page.getByRole("button", { name: "记录已保存", exact: true })).toBeVisible();
  const saved = await download(page, "保存后执行任务.xlsx");
  const savedRows = XLSX.utils.sheet_to_json<Record<string, unknown>>(saved.Sheets["执行用例"]);
  expect(savedRows[0]["实际结果"]).toBe("更新后的实际结果：已复测");
  expect(errors).toEqual([]);
  expect(failures).toEqual([]);
  await writeFile(path.join(artifacts, "result.json"), JSON.stringify({
    result: "passed", collectionId: collection.id, runId: run.id,
    assetRows: assetRows.length, executionRows: results.length,
    checks: ["真实注册与登录", "跨页完整导出25条", "资产搜索不截断导出", "中文与多步骤", "失败提示及重试", "任务汇总", "全部执行状态与缺陷", "未保存修改禁用导出", "保存后导出最新结果"],
    browserErrors: errors, serverErrors: failures,
  }, null, 2));
});
