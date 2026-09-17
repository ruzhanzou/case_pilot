import { expect, test, type Page } from "@playwright/test";

const apiUrl = process.env.CASEPILOT_E2E_API_URL ?? "http://localhost:8000";

async function showStage(page: Page, text: string) {
  await page.evaluate((label) => {
    document.getElementById("casepilot-recording-stage")?.remove();
    const stage = document.createElement("div");
    stage.id = "casepilot-recording-stage";
    stage.textContent = label;
    Object.assign(stage.style, {
      position: "fixed",
      zIndex: "2147483647",
      top: "18px",
      left: "50%",
      transform: "translateX(-50%)",
      padding: "10px 18px",
      borderRadius: "999px",
      color: "white",
      background: "rgba(30, 64, 175, .94)",
      boxShadow: "0 8px 28px rgba(15, 23, 42, .24)",
      font: "600 14px/1.4 system-ui, sans-serif",
      pointerEvents: "none",
    });
    document.body.appendChild(stage);
  }, text);
  await page.waitForTimeout(900);
}

test("录屏验收：选定用例后通过 AI 对话自然语言修改", async ({ page }) => {
  test.setTimeout(180_000);
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  const token = Date.now();
  const caseKey = `AI-REWRITE-${token}`;
  const collectionName = `AI-改写验收-${token}`;
  const initialTitle = `AI 改写验收：登录令牌校验 ${token}`;
  const updatedTitle = `AI 改写验收：登录令牌与会话唯一性 ${token}`;
  let caseId = "";
  let collectionId = "";

  await page.goto("/");
  if (await page.getByRole("button", { name: "Display language: English" }).isVisible()) {
    await page.getByRole("button", { name: "Display language: English" }).click();
  }
  if (await page.getByLabel("邮箱").isVisible()) {
    await page.getByLabel("邮箱").fill("demo@casepilot.local");
    await page.getByLabel("密码").fill("CasePilot123!");
    await page.getByRole("button", { name: "登录并进入工作台" }).click();
  }
  await expect(page.getByRole("heading", { name: "今天想测试什么？" })).toBeVisible();

  const me = await page.request.get(`${apiUrl}/api/v1/auth/me`);
  expect(me.ok()).toBeTruthy();
  const account = (await me.json()) as { spaces: { id: string }[] };
  try {
    const collectionResponse = await page.request.post(
      `${apiUrl}/api/v1/spaces/${account.spaces[0].id}/collections`,
      { data: { name: collectionName, description: "AI 改写独立验收集合" } },
    );
    expect(collectionResponse.status()).toBe(201);
    collectionId = ((await collectionResponse.json()) as { id: string }).id;
    const created = await page.request.post(
      `${apiUrl}/api/v1/collections/${collectionId}/test-cases`,
      {
        data: {
          case_key: caseKey,
          title: initialTitle,
          module: "登录接口",
          priority: "P1",
          case_type: "功能验收",
          tags: ["AI改写", "录屏验收"],
          preconditions: ["存在有效测试账号"],
          steps: [
            {
              action: "输入正确账号密码并提交登录",
              expected: "登录成功并返回有效认证令牌",
            },
          ],
          source: "Codex AI 自然语言改写验收",
          source_refs: [],
        },
      },
    );
    expect(created.status()).toBe(201);
    caseId = ((await created.json()) as { id: string }).id;

    await showStage(page, "步骤 1 / 4 · 打开已有用例集");
    await page.goto(`/workbench/collections/${collectionId}`);
    await expect(page.locator(".principle-workbench")).toBeVisible();
    await page.getByRole("button", { name: "用例列表" }).click();

    await showStage(page, "步骤 2 / 4 · 点击用例，直接设为 AI 修改目标");
    const caseRow = page.locator(".principle-case-row").filter({ hasText: initialTitle });
    await expect(caseRow).toBeVisible();
    await caseRow.getByRole("button").first().click();
    const targetContext = page.getByLabel("AI 修改目标");
    await expect(targetContext).toContainText("修改目标");
    await expect(targetContext).toContainText(initialTitle);
    expect((await targetContext.boundingBox())!.height).toBeLessThanOrEqual(60);
    expect(
      await targetContext.evaluate(
        (element) => element.scrollWidth <= element.clientWidth + 1,
      ),
      "长用例名称不应溢出对话区",
    ).toBeTruthy();
    await page.getByRole("button", { name: "用例脑图" }).click();
    const mindMap = page.getByLabel(`${collectionName} 用例脑图`);
    const mapNode = mindMap.locator(".case-map-node--case").filter({ hasText: initialTitle });
    await expect(mapNode).toBeVisible();
    await expect(mapNode).toHaveClass(/is-ai-target/);

    await showStage(page, "步骤 3 / 4 · 在对话区输入自然语言修改要求");
    const composer = page.getByLabel("用自然语言修改选中目标");
    await expect(composer).toHaveAttribute("placeholder", new RegExp(initialTitle));
    await composer.fill(
      `把这个用例的名称改为「${updatedTitle}」，并把预期结果补充为“登录成功、返回有效认证令牌，且只创建一个会话”。`,
    );
    const rewriteStartedAt = Date.now();
    await page.getByRole("button", { name: "让 AI 修改" }).click();
    const rewriteStatus = page.getByLabel("AI 改写状态");
    await showStage(page, "AI 正在理解指令并生成可审阅变更…");
    const review = page.locator(".principle-change-set");
    await expect(review).toBeVisible({ timeout: 180_000 });
    expect(Date.now() - rewriteStartedAt).toBeLessThan(180_000);
    await expect(review).toContainText("变更审阅");
    await expect(rewriteStatus).toContainText("改写完成，等待审阅");
    await expect(mapNode).toHaveClass(/is-ai-review/);
    await expect(mapNode).toContainText("等待审阅");

    await showStage(page, "步骤 4 / 4 · 人工确认后应用 AI 修改");
    await review.getByRole("button", { name: "确认应用" }).click();
    await expect(page.getByText("变更已应用并记录审计")).toBeVisible({
      timeout: 30_000,
    });
    await expect(rewriteStatus).toContainText("修改已应用");
    const updatedNode = mindMap.locator(".case-map-node--case").filter({ hasText: updatedTitle });
    await expect(updatedNode).toBeVisible();
    await expect(updatedNode).toHaveClass(/is-ai-applied/);
    await showStage(page, "验收通过 · 选定用例 → 自然语言修改 → 人工确认应用");
    await page.waitForTimeout(1800);

    const casesResponse = await page.request.get(
      `${apiUrl}/api/v1/collections/${collectionId}/test-cases`,
    );
    expect(casesResponse.ok()).toBeTruthy();
    const cases = (await casesResponse.json()) as { id: string; title: string }[];
    expect(cases.find((item) => item.id === caseId)?.title).toBe(updatedTitle);
    expect(pageErrors, "改写期间不应产生浏览器脚本错误").toEqual([]);
  } finally {
    if (caseId) {
      await page.request.delete(`${apiUrl}/api/v1/test-cases/${caseId}`);
    }
    if (collectionId) {
      await page.request.delete(`${apiUrl}/api/v1/collections/${collectionId}`);
    }
  }
});
