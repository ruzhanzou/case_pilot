import { expect, test } from "@playwright/test";
import * as XLSX from "xlsx";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const api = process.env.CASEPILOT_E2E_API_URL ?? "http://localhost:8000";
const output = path.resolve("../../output/excel-e2e-20261014");

for (const format of ["xlsx", "xls"] as const) {
  test(`${format}: upload, local parsing, grounded answer and refresh`, async ({ page }) => {
    test.setTimeout(240_000);
    await mkdir(output, { recursive: true });
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.addInitScript(() => localStorage.setItem("casepilot.locale.v1", "zh-CN"));
    const registration = await page.request.post(`${api}/api/v1/auth/register`, { data: {
      email: `excel-${format}-${Date.now()}@casepilot.test`, password: "CasePilot123!", display_name: "Excel端到端验收",
    } });
    expect(registration.status()).toBe(201);
    const account = await registration.json();
    let entry = "/workbench";
    if (format === "xls") {
      const created = await page.request.post(`${api}/api/v1/spaces/${account.spaces[0].id}/collections`, {
        data: { name: `旧版Excel验收-${Date.now()}` },
      });
      expect(created.status()).toBe(201);
      entry = `/workbench/collections/${(await created.json()).id}`;
    }
    await page.goto(entry);
    const composer = page.locator(format === "xlsx" ? ".new-conversation__composer" : ".principle-composer");
    await expect(composer).toBeVisible();
    await expect(composer.locator("textarea")).toBeEnabled();
    await expect(composer.locator('input[type="file"]')).toHaveAttribute("accept", /\.xlsx,\.xls/);
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet([
      ["需求编号", "业务规则"],
      ["00073", "星桥验证码登录系统：验证码有效期为7分钟，过期返回 E731。"],
      [],
      ["00074", "同一手机号连续输错4次验证码后锁定19分钟，锁定期间返回 E419。"],
    ]), "登录规则");
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet([
      ["字段", "含义"], ["NULL", "这是字面量，不代表空值"], ["NA", "这是业务状态，不代表空值"],
    ]), "字典");
    const name = `登录需求.${format}`;
    const buffer = XLSX.write(workbook, { type: "buffer", bookType: format === "xls" ? "biff8" : "xlsx" });
    await writeFile(path.join(output, name), buffer);
    const pendingUpload = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith("/attachments"));
    await composer.locator('input[type="file"]').setInputFiles({ name, buffer,
      mimeType: format === "xls" ? "application/vnd.ms-excel" : "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const uploaded = await pendingUpload;
    expect(uploaded.status()).toBe(202);
    const upload = await uploaded.json();
    const conversationUrl = uploaded.url().replace(/\/attachments$/, "");
    await expect(composer.locator('.principle-attachment[data-status="ready"]')).toContainText(name, { timeout: 90_000 });
    const source = await (await page.request.get(`${api}/api/v1/knowledge-sources/${upload.source.id}`)).json();
    expect(source.status).toBe("ready");
    expect(source.documents[0].status).toBe("ready");
    await page.screenshot({ path: path.join(output, `${format}-uploaded.png`), fullPage: true });
    const sent = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith("/messages"));
    await composer.locator("textarea").fill("请只根据刚上传的Excel回答：星桥验证码登录的验证码有效期是多少？过期错误码是什么？连续输错几次会锁定，锁定多久？请引用原始工作表和行号。这次只回答问题。" );
    await composer.getByRole("button", { name: "发送", exact: true }).click();
    expect((await sent).status()).toBe(202);
    let saved: any;
    await expect.poll(async () => {
      saved = await (await page.request.get(conversationUrl)).json();
      return saved.messages.some((m: any) => m.role === "assistant" && m.status === "completed" && m.metadata?.retrieval_performed);
    }, { timeout: 120_000, intervals: [1000, 2000] }).toBe(true);
    const answer = saved.messages.findLast((m: any) => m.role === "assistant" && m.metadata?.retrieval_performed);
    expect(answer.content).toMatch(/7\s*分钟|七分钟/);
    expect(answer.content).toContain("E731");
    expect(answer.content).toMatch(/4\s*次|四次/);
    expect(answer.content).toMatch(/19\s*分钟|十九分钟/);
    expect(JSON.stringify(answer)).toContain("登录规则");
    expect(JSON.stringify(answer)).toContain("行 1-4");
    expect(saved.context.pending_attachments).toHaveLength(0);
    await expect(page.getByLabel("对话附件").filter({ hasText: name }).first()).toBeVisible();
    await page.screenshot({ path: path.join(output, `${format}-answered.png`), fullPage: true });
    await page.reload();
    await expect(page.getByLabel("对话附件").filter({ hasText: name }).first()).toBeVisible();
    await expect(page.locator("body")).toContainText("E731");
    await page.screenshot({ path: path.join(output, `${format}-refreshed.png`), fullPage: true });
    await writeFile(path.join(output, `${format}-evidence.json`), JSON.stringify({ source, conversation: saved, errors }, null, 2));
    expect(errors).toEqual([]);
  });
}

test("Excel requirements generate traceable test-case candidates through the UI", async ({ page }) => {
  test.setTimeout(360_000);
  await page.addInitScript(() => localStorage.setItem("casepilot.locale.v1", "zh-CN"));
  const registered = await page.request.post(`${api}/api/v1/auth/register`, { data: {
    email: `excel-generation-${Date.now()}@casepilot.test`, password: "CasePilot123!", display_name: "Excel生成验收",
  } });
  expect(registered.status()).toBe(201);
  const account = await registered.json();
  const created = await page.request.post(`${api}/api/v1/spaces/${account.spaces[0].id}/collections`, { data: { name: "Excel登录需求生成验收" } });
  expect(created.status()).toBe(201);
  const collection = await created.json();
  await page.goto(`/workbench/collections/${collection.id}`);
  const composer = page.locator(".principle-composer");
  await expect(composer).toBeVisible();
    await expect(composer.locator("textarea")).toBeEnabled();
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet([
    ["需求编号", "规则"],
    ["00073", "星桥验证码登录系统：验证码有效期为7分钟，过期登录失败，返回 E731。"],
    ["00074", "同一手机号连续输错4次验证码后锁定19分钟，锁定期间登录失败，返回 E419。"],
  ]), "登录规则");
  const uploadResponse = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith("/attachments"));
  await composer.locator('input[type="file"]').setInputFiles({ name: "生成需求.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: XLSX.write(workbook, { type: "buffer", bookType: "xlsx" }) });
  const uploaded = await uploadResponse;
  expect(uploaded.status()).toBe(202);
  const conversationUrl = uploaded.url().replace(/\/attachments$/, "");
  await expect(composer.locator('.principle-attachment[data-status="ready"]')).toContainText("生成需求.xlsx", { timeout: 90_000 });
  await composer.locator("textarea").fill("请根据刚上传的Excel为星桥验证码登录系统生成测试用例，恰好两个测试点：验证码过期返回E731、连续输错后锁定返回E419。测试环境已有已注册手机号、可控制时钟和验证码的测试接口；每个测试点一条用例。直接制定测试规划，保留附件引用，不要增加其他范围。");
  await composer.getByRole("button", { name: "发送", exact: true }).click();
  let saved: any;
  await expect.poll(async () => {
    saved = await (await page.request.get(conversationUrl)).json();
    return saved.test_briefs.at(-1)?.content.planning?.test_points?.length ?? 0;
  }, { timeout: 150_000, intervals: [1000, 3000] }).toBeGreaterThan(0);
  await page.screenshot({ path: path.join(output, "generation-plan.png"), fullPage: true });
  await page.getByRole("button", { name: "确认规划并生成用例", exact: true }).click();
  await expect.poll(async () => {
    saved = await (await page.request.get(conversationUrl)).json();
    return saved.candidates.length;
  }, { timeout: 150_000, intervals: [1000, 3000] }).toBeGreaterThan(0);
  const cases = JSON.stringify(saved.candidates);
  expect(cases).toContain("E731");
  expect(cases).toContain("E419");
  expect(cases).toContain("登录规则");
  await expect(page.locator("body")).toContainText("E731");
  await page.screenshot({ path: path.join(output, "generated-candidates.png"), fullPage: true });
  await page.reload();
  await expect(page.locator("body")).toContainText("E731");
  await writeFile(path.join(output, "generation-evidence.json"), JSON.stringify(saved, null, 2));
});
