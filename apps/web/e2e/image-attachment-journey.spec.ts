/* eslint-disable @typescript-eslint/no-explicit-any -- Real acceptance evidence contains API payloads. */
import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";

test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== "1", "Requires real multimodal services");
test.setTimeout(600_000);

const api = `${process.env.CASEPILOT_E2E_API_URL ?? "http://localhost:8000"}/api/v1`;

test("an image attachment grounds a natural-language rewrite through apply and refresh", async ({ page }, info) => {
  const post = async (path: string, data: unknown) => {
    const response = await page.request.post(api + path, { data, timeout: 180_000 });
    expect(response.ok(), await response.text()).toBeTruthy();
    return response.json();
  };
  const get = async (path: string) => {
    const response = await page.request.get(api + path, { timeout: 180_000 });
    expect(response.ok(), await response.text()).toBeTruthy();
    return response.json();
  };
  const screenshot = info.outputPath("password-reset.png");
  execFileSync(resolve(process.cwd(), "../../.venv/bin/python"), [
    resolve(process.cwd(), "../../scripts/qa/image_acceptance_fixture.py"),
    screenshot,
  ]);

  await page.addInitScript(() => localStorage.setItem("casepilot.locale.v1", "zh-CN"));
  const user = await post("/auth/register", {
    email: `image-journey-${Date.now()}@casepilot.test`, password: "CasePilot123!", display_name: "图片依据验收",
  });
  const collection = await post(`/spaces/${user.spaces[0].id}/collections`, { name: "图片依据验收" });
  const original = await post(`/collections/${collection.id}/test-cases`, {
    title: "重置链接过期处理", module: "密码重置", priority: "P1", preconditions: ["用户已注册"],
    steps: [{ action: "签发后等待420秒并提交重置链接", expected: "返回OLD并重新签发链接" }],
  });
  const workspaceResponse = await page.request.put(`${api}/collections/${collection.id}/workspace`);
  expect(workspaceResponse.ok(), await workspaceResponse.text()).toBeTruthy();

  await page.goto(`/workbench/collections/${collection.id}`);
  const composer = page.locator(".principle-composer");
  await expect(composer.getByLabel("生成模型")).toHaveValue("doubao-seed-2.0-lite");
  await composer.locator('input[type="file"]').setInputFiles(screenshot);
  await expect(composer.locator(".principle-attachment[data-status=ready]")).toContainText("password-reset.png", { timeout: 90_000 });
  await expect(composer.getByRole("alert")).toHaveCount(0);

  await composer.locator("textarea").fill(
    `严格依据附件截图中的 Current production rules 修改用例 ${original.case_key}：把等待时间和错误码改为截图中的当前值，并按截图要求禁止重新签发链接。标题、模块、优先级和前置条件保持不变。先生成建议供我审阅。`,
  );
  const submitted = page.waitForResponse(response => response.url().endsWith("/messages") && response.request().method() === "POST", { timeout: 180_000 });
  await composer.getByRole("button", { name: "发送", exact: true }).click();
  const firstTurn = await (await submitted).json();
  expect(firstTurn.intent).toBe("CASE_MODIFY");

  const confirmedResponse = page.waitForResponse(response => response.url().endsWith("/resume") && response.request().method() === "POST", { timeout: 180_000 });
  await page.getByRole("button", { name: "确认修改并生成建议", exact: true }).last().click();
  const confirmed = await (await confirmedResponse).json();
  expect(confirmed.action.change_set_id).toBeTruthy();

  let change: any;
  await expect.poll(async () => {
    change = await get(`/case-change-sets/${confirmed.action.change_set_id}`);
    if (change.status === "failed") throw new Error(JSON.stringify(change));
    return change.status;
  }, { timeout: 360_000 }).toBe("ready");
  const proposal = change.items[0].proposed_snapshot;
  expect(JSON.stringify(proposal.steps)).toContain("300");
  expect(JSON.stringify(proposal.steps)).toContain("E731");
  expect(JSON.stringify(proposal.steps)).not.toMatch(/420|OLD/);
  expect(proposal.title).toBe(original.title);
  expect(proposal.priority).toBe(original.priority);
  expect(proposal.preconditions).toEqual(original.preconditions);
  expect(proposal.source_refs).toEqual(expect.arrayContaining([
    expect.objectContaining({ label: "password-reset.png", locator: "image" }),
  ]));

  await page.reload();
  const apply = page.locator(".collection-changes__review").getByRole("button", { name: /一键采纳全部待审阅用例/ });
  await expect(apply).toBeEnabled({ timeout: 90_000 });
  const appliedResponse = page.waitForResponse(response => response.url().endsWith("/apply") && response.request().method() === "POST");
  await apply.click();
  expect((await appliedResponse).ok()).toBeTruthy();
  await page.reload();

  const after = (await get(`/collections/${collection.id}/test-cases`))[0];
  expect(after.revision_number).toBe(2);
  expect(JSON.stringify(after.steps)).toContain("300");
  expect(JSON.stringify(after.steps)).toContain("E731");
  expect(JSON.stringify(after.steps)).not.toMatch(/420|OLD/);
  expect(after.title).toBe(original.title);
  expect(after.priority).toBe(original.priority);
  expect(after.preconditions).toEqual(original.preconditions);
  expect(after.source_refs).toEqual(expect.arrayContaining([
    expect.objectContaining({ label: "password-reset.png", locator: "image" }),
  ]));
  await expect(page.locator(".principle-composer textarea")).toBeEnabled({ timeout: 60_000 });
  writeFileSync(info.outputPath("evidence.json"), JSON.stringify({ firstTurn, confirmed, change, after }, null, 2));
  await page.screenshot({ path: info.outputPath("applied-after-refresh.png"), fullPage: true });
});
