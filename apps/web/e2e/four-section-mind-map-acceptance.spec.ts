import { expect, test } from "@playwright/test";

const apiUrl = process.env.CASEPILOT_E2E_API_URL ?? "http://localhost:8000";

test.use({ viewport: { width: 1600, height: 1000 } });

test("四段式脑图展示完整文字，并在画布内新增用例", async ({ page }) => {
  const token = Date.now();
  const collectionName = `脑图原位验收-${token}`;
  const title = `支付成功场景 ${token}`;
  const longExpected = "系统返回支付成功，并显示订单编号、支付时间、实际金额和可追溯的交易流水，不截断任何结果信息";
  let collectionId = "";
  let caseId = "";
  let addedCaseId = "";

  await page.goto("/");
  if (await page.getByRole("button", { name: "Display language: English" }).isVisible()) {
    await page.getByRole("button", { name: "Display language: English" }).click();
  }
  if (await page.getByLabel("邮箱").isVisible()) {
    await page.getByLabel("邮箱").fill("demo@casepilot.local");
    await page.getByLabel("密码").fill("CasePilot123!");
    await page.getByRole("button", { name: "登录并进入工作台" }).click();
  } else if (await page.getByLabel("Email").isVisible()) {
    await page.getByLabel("Email").fill("demo@casepilot.local");
    await page.getByLabel("Password").fill("CasePilot123!");
    await page.getByRole("button", { name: "Sign in to workspace" }).click();
  }
  await expect(page.getByRole("heading", { name: /今天想测试什么|What would you like to test/i })).toBeVisible();

  try {
    const me = await page.request.get(`${apiUrl}/api/v1/auth/me`);
    expect(me.ok()).toBeTruthy();
    const account = (await me.json()) as { spaces: { id: string }[] };
    const collectionResponse = await page.request.post(
      `${apiUrl}/api/v1/spaces/${account.spaces[0].id}/collections`,
      { data: { name: collectionName } },
    );
    expect(collectionResponse.status()).toBe(201);
    collectionId = ((await collectionResponse.json()) as { id: string }).id;
    const caseResponse = await page.request.post(
      `${apiUrl}/api/v1/collections/${collectionId}/test-cases`,
      { data: {
        case_key: `MAP-${token}`,
        title,
        module: "支付",
        priority: "P0",
        case_type: "功能",
        tags: [],
        preconditions: ["用户已登录"],
        steps: [{ action: "提交支付", expected: longExpected }],
        source: "脑图验收",
        source_refs: [],
      } },
    );
    expect(caseResponse.status()).toBe(201);
    caseId = ((await caseResponse.json()) as { id: string }).id;

    await page.goto(`/workbench/collections/${collectionId}`);
    if (await page.getByRole("button", { name: "Display language: English" }).isVisible()) {
      await page.getByRole("button", { name: "Display language: English" }).click();
    }
    await expect(page.getByText("1 条用例 · 1 个模块")).toBeVisible();
    await page.getByRole("button", { name: "用例脑图" }).click();
    const map = page.getByLabel(`${collectionName} 用例脑图`);
    await expect(map).toBeVisible();
    await expect(map.getByText("test_setup")).toBeVisible();
    await expect(map.getByText("test_procedure")).toBeVisible();
    await expect(map.getByText("test_validation")).toBeVisible();
    await expect(map.getByText(longExpected)).toBeVisible();

    const revisedExpected = `${longExpected}，并写入审计记录`;
    await map.getByLabel("直接编辑test_validation").fill(revisedExpected);
    await map.getByLabel("直接编辑test_validation").press("Enter");
    await expect(map.getByLabel("直接编辑test_validation")).toHaveValue(`1. ${revisedExpected}`);
    const revised = await page.request.get(`${apiUrl}/api/v1/collections/${collectionId}/test-cases`);
    expect(revised.ok()).toBeTruthy();
    expect(((await revised.json()) as { id: string; revision_number: number }[])
      .find((item) => item.id === caseId)?.revision_number).toBe(2);

    await page.getByRole("button", { name: /在支付下新增用例/ }).click();
    await expect(map.getByLabel("新用例标题")).toBeVisible();
    await expect(map.getByLabel("所属模块")).toHaveValue("支付");
    await expect(page.getByRole("heading", { name: "创建结构化测试用例" })).toHaveCount(0);
    await map.getByLabel("新用例标题").fill(`支付失败场景 ${token}`);
    await map.getByLabel("test_setup", { exact: true }).fill("用户已登录");
    await map.getByLabel("test_procedure", { exact: true }).fill("提交失败支付");
    await map.getByLabel("test_validation", { exact: true }).fill("显示失败原因");
    await map.getByRole("button", { name: "保存用例" }).click();
    await expect(map.getByLabel("新用例标题")).toHaveCount(0);
    const afterAdd = await page.request.get(`${apiUrl}/api/v1/collections/${collectionId}/test-cases`);
    const added = ((await afterAdd.json()) as { id: string; title: string }[])
      .find((item) => item.title === `支付失败场景 ${token}`);
    expect(added).toBeTruthy();
    addedCaseId = added!.id;
  } finally {
    if (addedCaseId) await page.request.delete(`${apiUrl}/api/v1/test-cases/${addedCaseId}`);
    if (caseId) await page.request.delete(`${apiUrl}/api/v1/test-cases/${caseId}`);
    if (collectionId) await page.request.delete(`${apiUrl}/api/v1/collections/${collectionId}`);
  }
});

test("大量用例默认收起详情，单条用例仍可展开编辑", async ({ page }) => {
  test.setTimeout(120_000);
  const token = Date.now();
  await page.goto("/");
  if (await page.getByRole("button", { name: "Display language: English" }).isVisible()) {
    await page.getByRole("button", { name: "Display language: English" }).click();
  }
  if (await page.getByLabel("邮箱").isVisible()) {
    await page.getByLabel("邮箱").fill("demo@casepilot.local");
    await page.getByLabel("密码").fill("CasePilot123!");
    await page.getByRole("button", { name: "登录并进入工作台" }).click();
  } else if (await page.getByLabel("Email").isVisible()) {
    await page.getByLabel("Email").fill("demo@casepilot.local");
    await page.getByLabel("Password").fill("CasePilot123!");
    await page.getByRole("button", { name: "Sign in to workspace" }).click();
  }
  await expect(page.getByRole("heading", { name: /今天想测试什么|What would you like to test/i })).toBeVisible();
  const account = await page.request.get(`${apiUrl}/api/v1/auth/me`);
  const spaceId = ((await account.json()) as { spaces: { id: string }[] }).spaces[0].id;
  const name = `脑图大量节点验收-${token}`;
  const collection = await page.request.post(`${apiUrl}/api/v1/spaces/${spaceId}/collections`, {
    data: { name },
  });
  expect(collection.status()).toBe(201);
  const collectionId = ((await collection.json()) as { id: string }).id;
  let caseIds: string[] = [];
  try {
    const created = await page.request.post(`${apiUrl}/api/v1/collections/${collectionId}/test-cases/batch`, {
      data: { cases: Array.from({ length: 31 }, (_, index) => ({
        case_key: `MAP-LARGE-${token}-${index}`,
        title: `批量用例 ${index}`,
        module: "批量模块",
        priority: "P1",
        case_type: "功能",
        tags: [],
        preconditions: ["已登录"],
        steps: [{ action: "操作", expected: "成功" }],
        source: "脑图性能验收",
      })) },
    });
    expect(created.status()).toBe(201);
    caseIds = ((await created.json()) as { id: string }[]).map((item) => item.id);
    await page.goto(`/workbench/collections/${collectionId}`);
    if (await page.getByRole("button", { name: "Display language: English" }).isVisible()) {
      await page.getByRole("button", { name: "Display language: English" }).click();
    }
    await expect(page.getByText("31 条用例 · 1 个模块")).toBeVisible();
    await page.getByRole("button", { name: "用例脑图" }).click();
    const map = page.getByLabel(`${name} 用例脑图`);
    await expect(map).toBeVisible();
    await expect(map.locator(".case-map-node--case")).toHaveCount(31);
    await expect(map.locator(".case-map-node--detail")).toHaveCount(0);
    await map.getByRole("button", { name: /展开批量用例 0的结构节点/ }).dispatchEvent("click");
    await expect(map.locator(".case-map-node--detail")).toHaveCount(3);
  } finally {
    for (const id of caseIds) await page.request.delete(`${apiUrl}/api/v1/test-cases/${id}`);
    await page.request.delete(`${apiUrl}/api/v1/collections/${collectionId}`);
  }
});
