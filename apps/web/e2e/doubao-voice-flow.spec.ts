import { expect, test, type Page } from "@playwright/test";

const requirement =
  "为豆包 App 实时语音通话生成测试用例。范围：用户点击语音通话，首次请求麦克风权限；建立低延迟双向流式会话；说话时实时显示聆听、思考、回答状态并支持打断播报；支持听筒、扬声器、蓝牙和有线耳机切换；覆盖来电、闹钟、耳机插拔、切后台、锁屏、弱网、断网、抖动、重连与超时；结束后释放麦克风并按隐私策略保存文本摘要。验收阈值：首包音频不超过 800ms，端到端语音响应不超过 1500ms，重连不超过 3 秒，重复点击不创建多个会话。请覆盖正常、权限、异常、边界、性能、兼容性、稳定性与隐私场景。";
const apiUrl =
  process.env.CASEPILOT_E2E_API_URL ?? "http://localhost:8000";

async function demoPause(page: Page, duration = 650) {
  if (process.env.CASEPILOT_E2E_VIDEO === "1") {
    await page.waitForTimeout(duration);
  }
}

test("doubao realtime voice requirement generates reviewed cases and hands off to management", async ({
  page,
}) => {
  const browserErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
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
  await expect(
    page.getByRole("heading", { name: "今天想测试什么？" }),
  ).toBeVisible();
  await demoPause(page);
  browserErrors.length = 0;

  const composer = page.getByLabel("写给 CasePilot");
  await composer.fill(requirement);
  await demoPause(page);
  await page.getByRole("button", { name: "发送" }).click();

  await expect(
    page.getByRole("heading", { name: "结构化测试说明" }),
  ).toBeVisible({ timeout: 60_000 });
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

  const commitButton = page.getByRole("button", { name: "纳入正式集合" });
  await expect(commitButton).toBeVisible({ timeout: 120_000 });
  await expect(page.getByLabel("标题")).toHaveValue(
    "授权后建立实时语音通话并满足时延阈值",
  );
  await demoPause(page, 1100);

  await page.getByRole("button", { name: "用例列表" }).click();
  await expect(page.getByText("弱网抖动后在 3 秒内恢复且不重复播报")).toBeVisible();
  await demoPause(page);
  await commitButton.click();

  const search = page.getByPlaceholder("搜索用例名称、编号、模块或标签");
  await search.fill("弱网抖动");
  await expect(
    page.getByRole("button", {
      name: /弱网抖动后在 3 秒内恢复且不重复播报/,
    }),
  ).toBeVisible();
  await page
    .getByRole("button", {
      name: /弱网抖动后在 3 秒内恢复且不重复播报/,
    })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "弱网抖动后在 3 秒内恢复且不重复播报",
    }),
  ).toBeVisible();
  await expect(page.getByText(/3 秒内完成重连/)).toBeVisible();
  await demoPause(page, 1200);

  await page.reload();
  await page.getByRole("button", { name: "用例管理" }).click();
  const collectionButton = page
    .locator(".collection-item")
    .filter({ hasText: collectionName })
    .last();
  await expect(collectionButton).toBeVisible();
  await collectionButton.click();
  await page
    .getByPlaceholder("搜索用例名称、编号、模块或标签")
    .fill("释放资源");
  await expect(
    page.getByRole("button", {
      name: /结束通话后释放资源并按隐私策略保存摘要/,
    }),
  ).toBeVisible();
  await demoPause(page);

  expect(browserErrors).toEqual([]);
});
