import { expect, test } from "@playwright/test";

const api = process.env.CASEPILOT_E2E_API_URL ?? "http://localhost:8000";

test("preview planning before cases, edit a point, generate only the selected branch", async ({ page }) => {
  const login = await page.request.post(`${api}/api/v1/auth/login`, {
    data: { email: "demo@casepilot.local", password: "CasePilot123!" },
  });
  expect(login.ok()).toBeTruthy();
  const account = await login.json();
  const created = await page.request.post(`${api}/api/v1/spaces/${account.spaces[0].id}/collections`, {
    data: { name: `规划验收-${Date.now()}` },
  });
  expect(created.status()).toBe(201);
  const collection = await created.json();
  const workspace = await (await page.request.put(`${api}/api/v1/collections/${collection.id}/workspace`)).json();
  const conversationUrl = `${api}/api/v1/conversations/${workspace.id}`;
  const requested = await page.request.post(`${conversationUrl}/messages`, {
    data: { content: "为账号密码登录功能生成测试用例", intent_override: "CASE_GENERATE", model_id: "auto" },
  });
  expect(requested.status()).toBe(202);
  await expect.poll(async () => {
    const current = await (await page.request.get(conversationUrl)).json();
    return current.test_briefs.at(-1)?.content.planning?.test_points.length ?? 0;
  }, { timeout: 90000 }).toBeGreaterThan(0);
  const before = await (await page.request.get(conversationUrl)).json();
  expect(before.candidates).toHaveLength(0);
  const brief = before.test_briefs.at(-1);
  const point = brief.content.planning.test_points[0];
  await page.goto(`/workbench/collections/${collection.id}`);
  const map = page.getByRole("region", { name: "测试规划脑图" });
  await expect(map).toBeVisible();
  await expect(map.getByText(/尚未生成用例/)).toBeVisible();
  await map.getByLabel("规划展开层级").selectOption("20");
  await map.getByRole("button", { name: "切换全屏" }).click();
  await map.getByRole("button", { name: point.title, exact: true }).click();
  await page.getByLabel("测试点名称", { exact: true }).fill("登录凭据校验规则");
  await page.getByLabel("业务场景名称", { exact: true }).fill("用户提交凭据");
  await page.getByRole("button", { name: "保存规划新版本" }).click();
  await expect(page.getByLabel(/Test brief version|测试说明版本/)).toHaveValue(String(brief.version + 1));
  await map.getByLabel("规划展开层级").selectOption("20");
  await expect(map.getByRole("button", { name: "登录凭据校验规则", exact: true })).toBeVisible();
  const changed = await (await page.request.get(conversationUrl)).json();
  expect(changed.test_briefs.at(-1).version).toBe(brief.version + 1);
  expect(changed.candidates).toHaveLength(0);
  const stale = await page.request.post(`${api}/api/v1/workspaces/${workspace.id}/test-briefs/confirm`, {
    data: { version: brief.version, model_id: "auto" },
  });
  expect(stale.status()).toBe(409);
  await page.reload();
  await expect(map).toBeVisible();
  await map.getByLabel("规划展开层级").selectOption("20");
  await map.getByRole("button", { name: "切换全屏" }).click();
  await map.getByRole("button", { name: "登录凭据校验规则", exact: true }).click();
  await page.screenshot({ path: "test-results/planning-preview.png", fullPage: true });
  await map.getByRole("button", { name: "生成选中范围（1）", exact: true }).click();
  await expect.poll(async () => {
    const current = await (await page.request.get(conversationUrl)).json();
    return current.candidates.length;
  }, { timeout: 90000 }).toBe(1);
  const after = await (await page.request.get(conversationUrl)).json();
  expect(after.candidates[0].snapshot.test_point_ids).toEqual([point.id]);
  expect(after.candidates[0].snapshot.module).toContain("用户提交凭据/登录凭据校验规则");
  await page.screenshot({ path: "test-results/planning-generated.png", fullPage: true });
  const firstCandidateId = after.candidates[0].id;
  const nextPoint = changed.test_briefs.at(-1).content.planning.test_points[1];
  const second = await page.request.post(`${api}/api/v1/workspaces/${workspace.id}/test-briefs/confirm`, {
    data: { version: changed.test_briefs.at(-1).version, model_id: "auto", selected_test_point_ids: [nextPoint.id] },
  });
  expect(second.status()).toBe(202);
  await expect.poll(async () => (await (await page.request.get(conversationUrl)).json()).candidates.length,
    { timeout: 90000 }).toBe(2);
  const combined = await (await page.request.get(conversationUrl)).json();
  expect(combined.candidates.some((item: { id: string }) => item.id === firstCandidateId)).toBeTruthy();
  const committed = await page.request.post(`${api}/api/v1/workspaces/${workspace.id}/candidates/commit`, {
    data: { candidate_ids: combined.candidates.map((item: { id: string }) => item.id) },
  });
  expect(committed.status()).toBe(200);
  expect((await committed.json()).length).toBe(2);
});

test("attached requirements are read past twelve blocks and 800 characters", async ({ request }) => {
  const login = await request.post(`${api}/api/v1/auth/login`, {
    data: { email: "demo@casepilot.local", password: "CasePilot123!" },
  });
  const account = await login.json();
  const collection = await (await request.post(`${api}/api/v1/spaces/${account.spaces[0].id}/collections`, {
    data: { name: `附件完整性-${Date.now()}` },
  })).json();
  const workspace = await (await request.put(`${api}/api/v1/collections/${collection.id}/workspace`)).json();
  const url = `${api}/api/v1/conversations/${workspace.id}`;
  const text = Array.from({ length: 16 }, (_, index) =>
    `# 功能${index}\n${"登录规则及具体条件。".repeat(120)}文末规则${index}：锁定期为30分钟。`,
  ).join("\n\n");
  const upload = await request.post(`${url}/attachments`, {
    multipart: { files: { name: "requirements.txt", mimeType: "text/plain", buffer: Buffer.from(text) } },
  });
  expect(upload.status()).toBe(202);
  const source = (await upload.json()).source;
  await expect.poll(async () => {
    const sources = await (await request.get(`${api}/api/v1/spaces/${account.spaces[0].id}/knowledge-sources`)).json();
    return sources.find((item: { id: string }) => item.id === source.id)?.status;
  }, { timeout: 90000 }).toBe("ready");
  const started = await request.post(`${url}/messages`, {
    data: { content: "根据附件为登录功能规划测试用例", intent_override: "CASE_GENERATE", model_id: "auto" },
  });
  expect(started.status()).toBe(202);
  await expect.poll(async () => (await (await request.get(url)).json()).test_briefs.length,
    { timeout: 90000 }).toBe(1);
  const current = await (await request.get(url)).json();
  const evidence = current.test_briefs[0].content.planning.evidence as { excerpt: string }[];
  expect(evidence.length).toBeGreaterThan(12);
  expect(evidence.some((item) => item.excerpt.length > 800)).toBeTruthy();
  expect(evidence.map((item) => item.excerpt).join("\n")).toContain("文末规则15：锁定期为30分钟");
  expect(current.candidates).toHaveLength(0);
});
