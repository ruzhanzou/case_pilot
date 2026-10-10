import { expect, test } from "@playwright/test";

const api = process.env.CASEPILOT_E2E_API_URL ?? "http://localhost:8000";

test("planning batches stream, survive stale polling and reload, then become confirmable", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("casepilot.locale.v1", "zh-CN"));
  const account = await (await page.request.post(`${api}/api/v1/auth/register`, { data: {
    email: `planning-progress-${Date.now()}@casepilot.test`, display_name: "规划进度验收", password: "CasePilot123!",
  } })).json();
  const collection = await (await page.request.post(`${api}/api/v1/spaces/${account.spaces[0].id}/collections`, {
    data: { name: "并发规划进度验收" },
  })).json();
  const workspace = await (await page.request.put(`${api}/api/v1/collections/${collection.id}/workspace`)).json();
  const jobId = "10000000-0000-4000-8000-000000000001";
  const content = {
    test_object: "账号登录", test_objective: "验证三种登录方式", scope: [], roles: [], core_flows: [],
    business_rules: [], constraints: [], risks: [], coverage_dimensions: [], assumptions: [], open_questions: [],
    planning: {
      feature_points: [1, 2, 3].map(i => ({ id: `F${i}`, name: `登录方式${i}`, module: "登录", description: `规则${i}`, requirement_refs: [] })),
      test_points: [1, 2, 3].map(i => ({ id: `P${i}`, title: `方式${i}登录成功`, objective: `验证方式${i}登录成功`, feature_point_ids: [`F${i}`] })),
    },
  };
  let complete = false;
  let ready = 1;
  let stale = true;
  const snapshot = (count: number) => ({
    id: jobId, status: complete ? "completed" : "running", stage: complete ? "completed" : "test_point.generated",
    progress: 35 + count * 20, error_code: null, stages: [],
    planning_progress: { progress: 35 + count * 20, completed_batches: count, total_batches: 3,
      test_point_count: count, active_batches: [{ batch: 3, features: ["登录方式3"] }] },
    planning_preview: { ...content, planning: { ...content.planning, test_points: content.planning.test_points.slice(0, count) } },
  });
  await page.route(`**/api/v1/conversations/${workspace.id}`, async route => {
    await route.fulfill({ json: { ...workspace,
      context: { ...workspace.context, active_view: "map", active_job_id: complete ? null : jobId, phase: complete ? "brief_review" : "brief_drafting" },
      messages: [{ id: "planning-message", role: "assistant", content: "正在处理请求", intent: "CASE_GENERATE",
        status: complete ? "completed" : "running", metadata: {}, target_case_ids: [], citations: [],
        related_job_id: jobId, created_at: new Date().toISOString() }],
      workflow_runs: [{ job_id: jobId, message_id: "planning-message", operation: "draft_brief",
        status: complete ? "completed" : "running", stage: "test_point.generated", stages: [],
        created_at: new Date().toISOString() }],
      test_briefs: complete ? [{ id: "brief-preview", version: 1, status: "draft", content,
        markdown_content: "# 账号登录", created_at: new Date().toISOString() }] : [],
    } });
  });
  await page.route(`**/api/v1/generation-jobs/${jobId}`, route => route.fulfill({ json: snapshot(stale ? 0 : ready) }));
  await page.route(`**/api/v1/generation-jobs/${jobId}/events`, route => route.fulfill({
    contentType: "text/event-stream", body: `event: test_point.generated\ndata: ${JSON.stringify(snapshot(ready))}\n\n`,
  }));
  await page.goto(`/workbench/conversations/${workspace.id}`);
  const preview = page.getByRole("region", { name: "实时测试规划" });
  await expect(preview).toBeVisible();
  await expect(page.locator(".principle-analysis-summary")).toHaveCount(0);
  await expect(page.locator(".principle-workflow")).not.toHaveAttribute("open");
  await expect(preview.getByRole("progressbar", { name: "规划进度" })).toHaveCSS("height", "5px");
  await expect(preview.getByText("方式1登录成功", { exact: true })).toBeVisible();
  await expect(preview.getByRole("progressbar", { name: "规划进度" })).toHaveAttribute("value", "55");
  await page.waitForTimeout(3500); // A stale poll must not erase the streamed batch.
  await expect(preview.getByText("方式1登录成功", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "确认规划并生成用例", exact: true })).toHaveCount(0);
  stale = false;
  ready = 2;
  await expect(preview.getByText("方式2登录成功", { exact: true })).toBeVisible();
  await page.reload();
  await expect(preview.getByText("方式2登录成功", { exact: true })).toBeVisible();
  await expect(preview.getByRole("progressbar", { name: "规划进度" })).toHaveAttribute("value", "75");
  await page.screenshot({ path: "../../output/parallel-planning/live-preview.png", fullPage: true });
  complete = true;
  ready = 3;
  await expect(preview).toHaveCount(0);
  await expect(page.getByRole("button", { name: "确认规划并生成用例", exact: true })).toBeVisible();
});
