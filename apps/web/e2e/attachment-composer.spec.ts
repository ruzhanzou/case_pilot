import { expect, test } from "@playwright/test";

const api = process.env.CASEPILOT_E2E_API_URL ?? "http://localhost:8000";

test("uploaded files stay in the composer until the user sends them", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("casepilot.locale.v1", "zh-CN"));
  const registered = await page.request.post(`${api}/api/v1/auth/register`, { data: {
    email: `attachment-composer-${Date.now()}@casepilot.test`, password: "CasePilot123!", display_name: "附件交互验收",
  } });
  expect(registered.ok()).toBeTruthy();
  await page.goto("/workbench");
  const composer = page.locator(".new-conversation__composer");
  await expect(composer).toBeVisible();
  const uploaded = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith("/attachments"));
  await composer.locator('input[type="file"]').setInputFiles({
    name: "doubao_login.txt", mimeType: "text/plain", buffer: Buffer.from("豆包支持手机号登录。验证码有效期为5分钟。"),
  });
  const response = await uploaded;
  expect(response.status()).toBe(202);
  const conversationUrl = response.url().replace(/\/attachments$/, "");
  await expect(composer.getByLabel("待发送附件")).toContainText("doubao_login.txt", { timeout: 90000 });
  await expect(page.locator(".new-conversation__messages")).toHaveCount(0);
  let saved = await (await page.request.get(conversationUrl)).json();
  expect(saved.messages).toHaveLength(0);
  expect(saved.context.pending_attachments).toHaveLength(1);
  await page.screenshot({ path: "../../output/attachment-composer/before-send.png", fullPage: true });
  await page.route("**/api/v1/conversations/*/messages", route => route.continue({
    postData: JSON.stringify({ ...route.request().postDataJSON(), intent_override: "CASE_GENERATE" }),
  }));
  await composer.locator("textarea").fill("根据附件生成登录模块测试用例");
  const sent = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith("/messages"));
  await composer.getByRole("button", { name: "发送", exact: true }).click();
  expect((await sent).status()).toBe(202);
  await expect(page.locator(".new-conversation__message--user").getByLabel("对话附件")).toContainText("doubao_login.txt");
  await expect(composer.getByLabel("待发送附件")).toHaveCount(0);
  await expect(composer.getByLabel("当前引用附件")).toContainText("doubao_login.txt");
  await expect(composer.getByLabel("当前引用附件")).toContainText("后续消息仍会使用这些附件作为依据");
  saved = await (await page.request.get(conversationUrl)).json();
  expect(saved.context.pending_attachments).toHaveLength(0);
  expect(saved.messages.filter((m: { metadata: { attachments?: unknown[] } }) => m.metadata.attachments?.length)).toHaveLength(1);
  await page.reload();
  await expect(composer.getByLabel("当前引用附件")).toContainText("doubao_login.txt");
  await page.screenshot({ path: "../../output/attachment-composer/after-send.png", fullPage: true });
});

test("workspace keeps active evidence visible after refresh and lets the user stop using it", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("casepilot.locale.v1", "zh-CN"));
  const registered = await page.request.post(`${api}/api/v1/auth/register`, { data: {
    email: `attachment-workspace-${Date.now()}@casepilot.test`, password: "CasePilot123!", display_name: "工作区附件验收",
  } });
  expect(registered.ok()).toBeTruthy();
  const account = await registered.json();
  const created = await page.request.post(`${api}/api/v1/spaces/${account.spaces[0].id}/collections`, { data: {
    name: `附件持续引用-${Date.now()}`,
  } });
  expect(created.ok()).toBeTruthy();
  const collection = await created.json();
  await page.goto(`/workbench/collections/${collection.id}`);
  const composer = page.locator(".principle-composer");
  await expect(composer.locator("textarea")).toBeEnabled();
  await expect(composer.locator('input[type="file"]')).toBeEnabled();
  const uploaded = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith("/attachments"));
  await composer.locator('input[type="file"]').setInputFiles({
    name: "active-rules.txt", mimeType: "text/plain", buffer: Buffer.from("验证码满300秒过期，错误码E731。"),
  });
  expect((await uploaded).status()).toBe(202);
  await expect(composer.getByLabel("待发送附件")).toContainText("active-rules.txt", { timeout: 90000 });
  await page.route("**/api/v1/conversations/*/messages", route => route.continue({
    postData: JSON.stringify({ ...route.request().postDataJSON(), intent_override: "CASE_QUERY" }),
  }));
  await composer.locator("textarea").fill("查询当前集合全部正式用例");
  const sent = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith("/messages"));
  await composer.locator('button[type="submit"]').click();
  expect((await sent).status()).toBe(202);
  await expect(composer.getByLabel("当前引用附件")).toContainText("active-rules.txt");
  await page.reload();
  await expect(composer.getByLabel("当前引用附件")).toContainText("active-rules.txt");
  const removed = page.waitForResponse(r => r.request().method() === "DELETE" && r.url().includes("/attachments/"));
  await composer.getByRole("button", { name: "移除 active-rules.txt", exact: true }).click();
  expect((await removed).ok()).toBeTruthy();
  await expect(composer.getByLabel("当前引用附件")).toHaveCount(0);
});
