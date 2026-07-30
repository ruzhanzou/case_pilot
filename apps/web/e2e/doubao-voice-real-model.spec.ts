import { expect, test, type Locator, type Page } from "@playwright/test";

const requirement =
  "为豆包 App 实时语音通话生成测试用例。范围：用户点击语音通话，首次请求麦克风权限；建立低延迟双向流式会话；说话时实时显示聆听、思考、回答状态并支持打断播报；支持听筒、扬声器、蓝牙和有线耳机切换；覆盖来电、闹钟、耳机插拔、切后台、锁屏、弱网、断网、抖动、重连与超时；结束后释放麦克风并按隐私策略保存文本摘要。验收阈值：首包音频不超过 800ms，端到端语音响应不超过 1500ms，重连不超过 3 秒，重复点击不创建多个会话。请覆盖正常、权限、异常、边界、性能、兼容性、稳定性与隐私场景。";
const apiUrl =
  process.env.CASEPILOT_E2E_API_URL ?? "http://localhost:8000";
const expectedModel =
  process.env.CASEPILOT_E2E_MODEL_LABEL ?? "doubao-seed-2.0-lite";

test.skip(
  process.env.CASEPILOT_E2E_REAL_MODEL !== "1",
  "Set CASEPILOT_E2E_REAL_MODEL=1 to run the external-provider smoke test.",
);

async function demoPause(page: Page, duration = 900) {
  if (process.env.CASEPILOT_E2E_VIDEO === "1") {
    await page.waitForTimeout(duration);
  }
}

async function waitForRealGeneration(page: Page): Promise<Locator> {
  const commitButton = page.getByRole("button", { name: "纳入正式集合" });
  const deadline = Date.now() + 720_000;

  while (Date.now() < deadline) {
    if (await commitButton.isVisible().catch(() => false)) return commitButton;

    await page.waitForTimeout(1000);
  }

  throw new Error("真实模型在 12 分钟内未返回可写入的候选用例");
}

test("a real model completes the Doubao voice requirement-to-library journey", async ({
  page,
}) => {
  const browserErrors: string[] = [];
  page.on("console", (message) => {
    if (
      message.type() === "error" &&
      !message.text().includes("ERR_NETWORK_IO_SUSPENDED")
    ) {
      browserErrors.push(message.text());
    }
  });

  const loginResponse = await page.request.post(
    `${apiUrl}/api/v1/auth/login`,
    {
      data: {
        email: "demo@casepilot.local",
        password: "CasePilot123!",
      },
    },
  );
  expect(loginResponse.ok()).toBeTruthy();

  await page.goto("/");
  const loginButton = page.getByRole("button", { name: "登录并进入工作台" });
  if (await loginButton.isVisible().catch(() => false)) {
    await demoPause(page, 1000);
    await loginButton.click();
  }
  await expect(
    page.getByRole("heading", { name: "今天想测试什么？" }),
  ).toBeVisible();
  await demoPause(page);
  browserErrors.length = 0;

  const modelSelect = page.getByRole("combobox", { name: "生成模型" });
  await modelSelect.selectOption({ label: expectedModel });
  await page.getByLabel("写给 CasePilot").fill(requirement);
  await demoPause(page, 1400);

  await page.getByRole("button", { name: "发送" }).click();
  await expect(
    page.getByRole("heading", { name: "结构化测试说明" }),
  ).toBeVisible({ timeout: 720_000 });
  const collectionName =
    (
      await page
        .locator(".principle-canvas > header h1")
        .textContent()
    )?.trim() ?? "";
  expect(collectionName).not.toBe("");

  const confirmBriefButton = page.getByRole("button", {
    name: "确认并生成用例",
  });
  await expect(confirmBriefButton).toBeEnabled();
  await confirmBriefButton.click();

  const commitButton = await waitForRealGeneration(page);
  const generatedCount = await page.locator(".principle-case-row").count();
  expect(generatedCount).toBeGreaterThan(0);
  await demoPause(page, 1800);

  await page.getByRole("button", { name: "用例列表" }).click();
  await expect(page.getByText(/弱网|网络抖动|重连/).first()).toBeVisible();
  await demoPause(page, 1200);
  await commitButton.click();

  const search = page.getByPlaceholder("搜索用例名称、编号、模块或标签");
  await search.fill("弱网");
  const weakNetworkCase = page.getByRole("button", {
    name: /弱网|网络抖动|重连/,
  }).first();
  await expect(weakNetworkCase).toBeVisible();
  await weakNetworkCase.click();
  await expect(page.getByRole("heading", { name: /弱网|网络抖动|重连/ })).toBeVisible();
  await demoPause(page, 1800);

  await page.reload();
  await page.getByRole("button", { name: "用例管理" }).click();
  const collectionButton = page
    .locator(".collection-item")
    .filter({ hasText: collectionName });
  await expect(collectionButton).toHaveCount(1);
  await collectionButton.click();
  await page
    .getByPlaceholder("搜索用例名称、编号、模块或标签")
    .fill("实时语音");
  await expect(
    page.getByRole("button", { name: /实时语音|语音通话/ }).first(),
  ).toBeVisible();
  await demoPause(page, 1200);

  expect(browserErrors).toEqual([]);
});
