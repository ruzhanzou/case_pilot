import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

const demoPause = async (page: Page) => {
  if (process.env.CASEPILOT_E2E_VIDEO === "1") {
    await page.waitForTimeout(700);
  }
};

test("knowledge clarification candidate review and formal revision survive refresh", async ({
  page,
}) => {
  const browserErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });

  await page.goto("/");
  await page.getByLabel("邮箱").fill("demo@casepilot.local");
  await page.getByLabel("密码").fill("CasePilot123!");
  await page.getByRole("button", { name: "登录并进入工作台" }).click();
  await expect(
    page.getByRole("heading", { name: "今天想测试什么？" }),
  ).toBeVisible();
  await demoPause(page);
  browserErrors.length = 0;

  await page.getByRole("button", { name: "空间知识库" }).click();
  await expect(page.getByRole("heading", { name: "空间知识库" })).toBeVisible();
  const sourceName = `Playwright 支付需求 ${Date.now()}`;
  await page.getByLabel("来源名称").fill(sourceName);
  await page.locator('input[type="file"]').setInputFiles(
    path.resolve(
      "../agent/tests/fixtures/blocking-payment-requirement.md",
    ),
  );
  await page.getByRole("button", { name: "上传并建立索引" }).click();
  const sourceCard = page
    .locator("article.knowledge-source")
    .filter({ hasText: sourceName });
  await expect(sourceCard.getByText("可检索")).toBeVisible();
  await demoPause(page);

  await page.getByRole("button", { name: "AI 用例工作台" }).click();
  await expect(
    page.getByRole("heading", { name: "今天想测试什么？" }),
  ).toBeVisible();
  const landingComposer = page.getByLabel("写给 CasePilot");
  await landingComposer.fill("请生成测试用例");
  await page.getByRole("button", { name: "发送" }).click();

  await expect(
    page.getByRole("heading", { name: "结构化测试说明" }),
  ).toBeVisible({ timeout: 60_000 });
  const collectionName =
    (await page.locator(".principle-canvas > header h1").textContent())?.trim() ??
    "";
  expect(collectionName).not.toBe("");
  await expect(
    page.getByText("尚未明确测试对象，请先通过对话补充，再生成用例。"),
  ).toBeVisible();
  await demoPause(page);

  const workspaceComposer = page.getByPlaceholder(
    "继续修改测试说明、维护当前用例，或询问需求内容…",
  );
  await workspaceComposer.fill(
    "测试对象是支付文档中的订单支付成功流程：目标用户为已登录商户，订单状态变为 paid 且可查询即为成功。",
  );
  await page.getByRole("button", { name: "发送" }).click();

  const confirmBriefButton = page.getByRole("button", {
    name: "确认并生成用例",
  });
  await expect(confirmBriefButton).toBeEnabled({ timeout: 60_000 });
  await confirmBriefButton.click();

  const commitButton = page.getByRole("button", { name: "纳入正式集合" });
  await expect(commitButton).toBeVisible({ timeout: 120_000 });
  const firstCandidate = page.locator(".principle-case-row button").first();
  await expect(firstCandidate).toBeVisible();
  const firstCandidateTitle =
    (await firstCandidate.locator("strong").textContent())?.trim() ?? "";
  expect(firstCandidateTitle).not.toBe("");
  await demoPause(page);
  await commitButton.click();

  await expect(page.getByText("用例资产管理", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: firstCandidateTitle, exact: true }),
  ).toBeVisible();
  await demoPause(page);

  await page.reload();
  await page.getByRole("button", { name: "用例管理" }).click();
  const collectionButton = page
    .locator(".collection-item")
    .filter({ hasText: collectionName })
    .last();
  await expect(collectionButton).toBeVisible();
  await collectionButton.click();
  await expect(
    page.getByRole("heading", { name: firstCandidateTitle, exact: true }),
  ).toBeVisible();
  await demoPause(page);
  expect(browserErrors).toEqual([]);
});
