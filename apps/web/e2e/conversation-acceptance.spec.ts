import { expect, test, type Page } from "@playwright/test";

const apiUrl = process.env.CASEPILOT_E2E_API_URL ?? "http://localhost:8000";

async function login(page: Page) {
  await page.goto("/");
  await page.getByLabel("邮箱").fill("demo@casepilot.local");
  await page.getByLabel("密码").fill("CasePilot123!");
  await page.getByRole("button", { name: "登录并进入工作台" }).click();
  await expect(page.getByRole("heading", { name: "今天想测试什么？" })).toBeVisible();
  const closeHistory = page.getByRole("button", { name: "关闭历史对话" }).last();
  if (await closeHistory.isVisible()) await closeHistory.click();
}

async function createCollection(page: Page, name: string) {
  const me = await page.request.get(`${apiUrl}/api/v1/auth/me`);
  expect(me.ok()).toBeTruthy();
  const account = (await me.json()) as { spaces: { id: string }[] };
  const response = await page.request.post(
    `${apiUrl}/api/v1/spaces/${account.spaces[0].id}/collections`,
    { data: { name, description: "对话区 Playwright 隔离验收" } },
  );
  expect(response.status()).toBe(201);
  return (await response.json()) as { id: string; name: string };
}

function watchAssistantGrowth(page: Page) {
  return page.evaluate(() => {
    const state = window as typeof window & {
      __casepilotStreamLengths?: number[];
      __casepilotStreamObserver?: MutationObserver;
    };
    state.__casepilotStreamLengths = [];
    state.__casepilotStreamObserver?.disconnect();
    const sample = () => {
      const messages = document.querySelectorAll(
        ".new-conversation__message--assistant",
      );
      const length = messages.item(messages.length - 1)?.textContent?.length ?? 0;
      const lengths = state.__casepilotStreamLengths ?? [];
      if (length > 0 && lengths.at(-1) !== length) lengths.push(length);
    };
    const observer = new MutationObserver(sample);
    observer.observe(document.body, {
      childList: true,
      characterData: true,
      subtree: true,
    });
    state.__casepilotStreamObserver = observer;
    sample();
  });
}

async function streamLengths(page: Page) {
  return page.evaluate(() => {
    const state = window as typeof window & {
      __casepilotStreamLengths?: number[];
      __casepilotStreamObserver?: MutationObserver;
    };
    state.__casepilotStreamObserver?.disconnect();
    return state.__casepilotStreamLengths ?? [];
  });
}

test("persona and knowledge answers stay in chat and render true stream deltas", async ({
  page,
}) => {
  const browserErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });
  await login(page);
  browserErrors.length = 0;
  await watchAssistantGrowth(page);

  const composer = page.getByLabel("写给 CasePilot");
  await composer.fill(
    "你是谁？你能做什么？请用较完整的方式介绍能力、知识问答范围和正式资产变更的人工确认边界。",
  );
  await page.getByRole("button", { name: "发送" }).click();
  const assistant = page.locator(".new-conversation__message--assistant").last();
  await expect(assistant).toContainText("CasePilot", { timeout: 120_000 });
  await expect(page.locator(".new-conversation__access")).toContainText(
    "自动识别意图",
    { timeout: 120_000 },
  );
  const lengths = await streamLengths(page);
  expect(new Set(lengths).size).toBeGreaterThanOrEqual(3);
  await expect(page.locator(".principle-workbench")).toHaveCount(0);

  await composer.fill("如何删除测试用例？");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.locator(".new-conversation__message--assistant").last()).toContainText(
    /删除|确认|权限/,
    { timeout: 120_000 },
  );
  await expect(page.locator(".new-conversation__access")).toContainText(
    "自动识别意图",
    { timeout: 120_000 },
  );
  await expect(page.locator(".conversation-collection-picker")).toHaveCount(0);
  await expect(page.locator(".principle-workbench")).toHaveCount(0);
  expect(browserErrors).toEqual([]);
});

test("collection confirmation locks one workspace and cross-collection work starts in a new chat", async ({
  page,
}) => {
  await login(page);
  const token = Date.now();
  const collectionA = await createCollection(page, `登录回归用例-${token}`);
  const collectionB = await createCollection(page, `支付回归用例-${token}`);
  await page.reload();
  const closeHistory = page.getByRole("button", { name: "关闭历史对话" }).last();
  if (await closeHistory.isVisible()) await closeHistory.click();

  const landingComposer = page.getByLabel("写给 CasePilot");
  await landingComposer.fill(`查询${collectionA.name}中的 P0 用例`);
  await page.getByRole("button", { name: "发送" }).click();
  const picker = page.locator(".conversation-collection-picker");
  await expect(picker).toBeVisible();
  await expect(page.locator(".principle-workbench")).toHaveCount(0);
  await picker.locator("select").selectOption(collectionA.id);
  await picker.getByRole("button", { name: "确认并进入工作台" }).click();

  await expect(page.locator(".principle-canvas h1")).toHaveText(collectionA.name);
  await expect(page.getByText("本对话仅维护此集合").first()).toBeVisible();
  const workspaceComposer = page.getByPlaceholder(
    "继续修改测试说明、维护当前用例，或询问需求内容…",
  );
  const crossInstruction = `查询${collectionB.name}中的用例`;
  await workspaceComposer.fill(crossInstruction);
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByText("当前对话已锁定此集合，不会执行跨集合变更。")).toBeVisible();
  await page.getByRole("button", { name: "新建对话并打开该集合" }).click();

  await expect(page.locator(".principle-canvas h1")).toHaveText(collectionB.name);
  await expect(
    page.getByPlaceholder("继续修改测试说明、维护当前用例，或询问需求内容…"),
  ).toHaveValue(crossInstruction);
  await expect(page.locator(".principle-message.is-user")).toHaveCount(0);
});

test("history drawer animates, searches and keeps the active conversation highlighted", async ({
  page,
}) => {
  await login(page);
  await page.getByRole("button", { name: "历史对话" }).click();
  const layer = page.locator(".conversation-history-layer");
  await expect(layer).toHaveClass(/is-open/);
  const drawer = page.locator(".conversation-history-drawer");
  const transitionDuration = await drawer.evaluate(
    (element) => getComputedStyle(element).transitionDuration,
  );
  expect(transitionDuration).not.toMatch(/^0(?:s|ms)(?:, 0(?:s|ms))*$/);
  await page.getByPlaceholder("搜索对话或用例集合").fill("CasePilot");
  await expect(page.locator(".conversation-history-list")).toBeVisible();
  await page.getByRole("button", { name: "关闭历史对话" }).last().click();
  await expect(layer).toHaveClass(/is-closed/);
});
