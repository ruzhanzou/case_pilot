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
    await page.getByRole("button", { name: "用例脑图" }).click();
    const map = page.getByLabel(`${collectionName} 用例脑图`);
    await expect(map).toBeVisible();
    await expect(map.getByText("test_setup")).toBeVisible();
    await expect(map.getByText("test_procedure")).toBeVisible();
    await expect(map.getByText("test_validation")).toBeVisible();
    await expect(map.getByText(longExpected)).toBeVisible();

    await page.getByRole("button", { name: /在支付下新增用例/ }).click();
    await expect(map.getByLabel("新用例标题")).toBeVisible();
    await expect(map.getByLabel("所属模块")).toHaveValue("支付");
    await expect(page.getByRole("heading", { name: "创建结构化测试用例" })).toHaveCount(0);
  } finally {
    if (caseId) await page.request.delete(`${apiUrl}/api/v1/test-cases/${caseId}`);
    if (collectionId) await page.request.delete(`${apiUrl}/api/v1/collections/${collectionId}`);
  }
});
