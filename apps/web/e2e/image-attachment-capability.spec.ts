import { expect, test } from "@playwright/test";
import { writeFileSync } from "node:fs";

const api = process.env.CASEPILOT_E2E_API_URL ?? "http://localhost:8000";

test("image attachment remains reviewable and cannot be sent to a text-only model", async ({ page }, info) => {
  await page.addInitScript(() => localStorage.setItem("casepilot.locale.v1", "zh-CN"));
  const registered = await page.request.post(`${api}/api/v1/auth/register`, { data: {
    email: `image-capability-${Date.now()}@casepilot.test`,
    password: "CasePilot123!",
    display_name: "图片附件能力验收",
  } });
  expect(registered.ok()).toBeTruthy();

  await page.goto("/workbench");
  const composer = page.locator(".new-conversation__composer");
  await expect(composer).toBeVisible();
  const uploaded = page.waitForResponse(response =>
    response.request().method() === "POST" && response.url().endsWith("/attachments"));
  await composer.locator('input[type="file"]').setInputFiles({
    name: "login-screen.png",
    mimeType: "image/png",
    buffer: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
      "base64",
    ),
  });
  const response = await uploaded;
  expect(response.status()).toBe(202);

  await expect(composer.getByLabel("待发送附件")).toContainText("login-screen.png", {
    timeout: 90_000,
  });
  await expect(composer.getByRole("alert")).toContainText("当前模型不支持图片");
  await expect(composer.getByRole("button", { name: "发送", exact: true })).toBeDisabled();
  await composer.locator("textarea").fill("根据截图生成登录用例");
  await expect(composer.getByRole("button", { name: "发送", exact: true })).toBeDisabled();

  const conversationUrl = response.url().replace(/\/attachments$/, "");
  const state = await (await page.request.get(conversationUrl)).json();
  expect(state.messages).toHaveLength(0);
  expect(state.context.pending_attachments).toMatchObject([
    { name: "login-screen.png", mime_type: "image/png", status: "ready" },
  ]);
  writeFileSync(info.outputPath("evidence.json"), JSON.stringify(state, null, 2));
  await page.screenshot({ path: info.outputPath("image-model-warning.png"), fullPage: true });
});
