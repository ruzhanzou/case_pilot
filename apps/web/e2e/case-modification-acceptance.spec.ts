import { expect, test, type Page } from "@playwright/test";

const apiUrl = process.env.CASEPILOT_E2E_API_URL ?? "http://localhost:8000";

type SeededCase = { id: string; case_key: string; title: string; revision_number: number };
type AcceptanceCollection = { id: string; name: string; cases: SeededCase[] };

async function login(page: Page) {
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
}

async function seedCollection(page: Page): Promise<AcceptanceCollection> {
  const token = Date.now();
  const accountResponse = await page.request.get(`${apiUrl}/api/v1/auth/me`);
  expect(accountResponse.ok()).toBeTruthy();
  const account = (await accountResponse.json()) as { spaces: { id: string }[] };
  const name = `用例修改端到端验收-${token}`;
  const collectionResponse = await page.request.post(
    `${apiUrl}/api/v1/spaces/${account.spaces[0].id}/collections`,
    { data: { name, description: "对话目标映射、差异审阅、应用与拒绝的隔离验收" } },
  );
  expect(collectionResponse.status()).toBe(201);
  const { id } = (await collectionResponse.json()) as { id: string };
  const cases: SeededCase[] = [];
  for (const [suffix, title] of [["A", "验证码登录成功"], ["B", "验证码过期提示"]] as const) {
    const created = await page.request.post(`${apiUrl}/api/v1/collections/${id}/test-cases`, {
      data: {
        case_key: `MOD-${token}-${suffix}`,
        title: `${title}-${token}`,
        module: "登录",
        priority: "P1",
        case_type: "功能验收",
        tags: ["修改验收"],
        preconditions: ["测试账号可用"],
        steps: [{ action: "输入手机号和短信验证码", expected: title }],
        source: "用例修改端到端验收",
        source_refs: [],
      },
    });
    expect(created.status()).toBe(201);
    cases.push((await created.json()) as SeededCase);
  }
  return { id, name, cases };
}

async function readCases(page: Page, collectionId: string): Promise<SeededCase[]> {
  const response = await page.request.get(`${apiUrl}/api/v1/collections/${collectionId}/test-cases`);
  expect(response.ok()).toBeTruthy();
  return (await response.json()) as SeededCase[];
}

async function cleanup(page: Page, seeded: AcceptanceCollection | undefined) {
  if (!seeded) return;
  for (const item of seeded.cases) {
    await page.request.delete(`${apiUrl}/api/v1/test-cases/${item.id}`);
  }
  await page.request.delete(`${apiUrl}/api/v1/collections/${seeded.id}`);
}

test("未勾选目标时按用例编号映射，审阅拒绝后资产不变", async ({ page }) => {
  test.setTimeout(240_000);
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await login(page);
  let seeded: AcceptanceCollection | undefined;
  try {
    seeded = await seedCollection(page);
    const [target, other] = seeded.cases;
    await page.goto(`/workbench/collections/${seeded.id}`);
    await expect(page.locator(".principle-workbench")).toBeVisible();
    await expect(page.getByLabel("用自然语言修改选中目标")).toBeEnabled();
    await expect(page.getByLabel("AI 修改目标")).toHaveCount(0);

    await page.getByLabel("用自然语言修改选中目标").fill(
      `请将用例 ${target.case_key} 的预期结果改为“登录成功并返回唯一会话标识”。`,
    );
    await page.getByRole("button", { name: "发送" }).click();
    const review = page.locator(".principle-change-set");
    await expect(review).toBeVisible({ timeout: 180_000 });
    await expect(review).toContainText(target.title);
    await expect(review).not.toContainText(other.title);
    expect((await readCases(page, seeded.id)).find((item) => item.id === target.id)?.revision_number)
      .toBe(target.revision_number);

    const rejection = page.waitForResponse((response) =>
      response.url().includes("/case-change-sets/") && response.url().endsWith("/reject"),
    );
    await review.getByRole("button", { name: "拒绝变更" }).click();
    expect((await rejection).ok()).toBeTruthy();
    await expect(page.getByText("已拒绝变更，正式用例未修改")).toBeVisible();
    await page.reload();
    await expect(page.locator(".principle-change-set")).toHaveCount(0);
    const after = await readCases(page, seeded.id);
    expect(after.find((item) => item.id === target.id)?.revision_number).toBe(target.revision_number);
    expect(after.find((item) => item.id === other.id)?.revision_number).toBe(other.revision_number);
    expect(pageErrors).toEqual([]);
  } finally {
    await cleanup(page, seeded);
  }
});

test("不勾选用例时修改当前用例，确认后只生成目标用例的新版本且脑图可见", async ({ page }) => {
  test.setTimeout(240_000);
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await login(page);
  let seeded: AcceptanceCollection | undefined;
  try {
    seeded = await seedCollection(page);
    const [target, other] = seeded.cases;
    const updatedTitle = `${target.title}-会话唯一`;
    await page.goto(`/workbench/collections/${seeded.id}`);
    await expect(page.locator(".principle-workbench")).toBeVisible();
    await expect(page.getByLabel("用自然语言修改选中目标")).toBeEnabled();
    await expect(page.getByLabel("AI 修改目标")).toHaveCount(0);

    await page.getByLabel("用自然语言修改选中目标").fill(
      `请把当前用例的标题改为「${updatedTitle}」，并在预期结果中补充“只创建一个会话”。`,
    );
    await page.getByRole("button", { name: "发送" }).click();
    const review = page.locator(".principle-change-set");
    await expect(review).toBeVisible({ timeout: 180_000 });
    await expect(review).toContainText(target.title);
    await expect(review).not.toContainText(other.title);
    await review.getByRole("button", { name: "确认应用" }).click();
    await expect(page.getByText("变更已应用并记录审计")).toBeVisible({ timeout: 30_000 });
    const after = await readCases(page, seeded.id);
    expect(after.find((item) => item.id === target.id)?.title).toBe(updatedTitle);
    expect(after.find((item) => item.id === target.id)?.revision_number).toBeGreaterThan(target.revision_number);
    expect(after.find((item) => item.id === other.id)?.revision_number).toBe(other.revision_number);
    await page.getByRole("button", { name: "用例脑图" }).click();
    await expect(page.getByLabel(`${seeded.name} 用例脑图`).locator(".case-map-node--case")
      .filter({ hasText: updatedTitle })).toBeVisible();
    expect(pageErrors).toEqual([]);
  } finally {
    await cleanup(page, seeded);
  }
});

test("多个用例但没有可解析目标时要求选择，不修改正式资产", async ({ page }) => {
  test.setTimeout(60_000);
  await login(page);
  let seeded: AcceptanceCollection | undefined;
  try {
    seeded = await seedCollection(page);
    await page.goto(`/workbench/collections/${seeded.id}`);
    await expect(page.locator(".principle-workbench")).toBeVisible();
    await expect(page.getByLabel("用自然语言修改选中目标")).toBeEnabled();
    await page.getByLabel("用自然语言修改选中目标").fill("请把预期结果写得更明确。");
    await page.getByRole("button", { name: "发送" }).click();
    await expect(page.getByText("请先选择要修改的当前用例或当前模块。")).toBeVisible();
    await expect(page.locator(".principle-change-set")).toHaveCount(0);
    const after = await readCases(page, seeded.id);
    expect(after.map((item) => item.revision_number)).toEqual(seeded.cases.map((item) => item.revision_number));
  } finally {
    await cleanup(page, seeded);
  }
});
