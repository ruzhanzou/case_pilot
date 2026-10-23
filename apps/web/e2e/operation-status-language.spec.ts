import { expect, test } from "@playwright/test";

test("new conversation shows product labels instead of internal operation states", async ({ page }) => {
  const operation = (id: string, sequence: number, status: string) => ({
    id,
    source_message_id: "request",
    sequence,
    intent: sequence === 0 ? "CASE_QUERY" : sequence === 1 ? "CASE_MODIFY" : "CASE_GENERATE",
    confidence: 1,
    status,
    target: {},
    payload: {},
    result: {},
    requires_confirmation: true,
    related_job_id: null,
    related_change_set_id: null,
    error_code: null,
    created_at: `2026-10-24T00:00:0${sequence}Z`,
  });
  const operations = [
    operation("choose-collection", 0, "awaiting_collection"),
    operation("choose-action", 1, "awaiting_intent"),
    operation("queued", 2, "queued"),
  ];
  const conversation = {
    id: "status-conversation",
    space_id: "space",
    collection_id: null,
    title: "多动作状态说明",
    status: "active",
    context: {},
    messages: [{
      id: "request",
      role: "user",
      content: "查询后修改并生成用例",
      intent: "CASE_QUERY",
      intent_confidence: 1,
      status: "completed",
      target_case_ids: [],
      related_job_id: null,
      citations: [],
      metadata: {},
      created_at: "2026-10-24T00:00:00Z",
    }],
    test_briefs: [],
    candidates: [],
    workflow_runs: [],
    operation_history: operations,
    operation_plan: {
      status: "awaiting_collection",
      source_message_id: "request",
      current_operation_id: "choose-collection",
      operations,
    },
  };
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let json: unknown = [];
    if (path.endsWith("/auth/me")) json = {
      id: "user",
      email: "qa@example.com",
      display_name: "QA",
      spaces: [{ id: "space", name: "质量空间", role: "owner" }],
    };
    else if (path.endsWith("/generation-models")) json = { models: [], default_model_id: "auto" };
    else if (path.endsWith("/conversations/status-conversation")) json = conversation;
    else if (path.endsWith("/spaces/space/collections")) json = [];
    await route.fulfill({ json });
  });
  await page.addInitScript(() => localStorage.setItem("casepilot.locale.v1", "zh-CN"));
  await page.goto("/workbench/conversations/status-conversation");

  const plan = page.getByRole("list", { name: "多意图执行进度" });
  await expect(plan).toContainText("等待选择集合");
  await expect(plan).toContainText("等待选择操作");
  await expect(plan).toContainText("等待执行");
  await expect(plan).not.toContainText(/awaiting_|queued/);
});
