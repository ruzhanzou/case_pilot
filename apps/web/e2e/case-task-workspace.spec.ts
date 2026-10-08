import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 1600, height: 1000 } });

test("conversation owns progress and summaries while workstation owns results", async ({ page }, testInfo) => {
  let running = true;
  let sends = 0;
  const collection = { id: "alpha", space_id: "space", name: "Account quality workspace", lifecycle_status: "maintenance", case_count: 0, mind_map_notes: [] };
  const message = (id: string, role: string, content: string, intent: string, status = "completed") => ({
    id, role, content, intent, status, citations: [], target_case_ids: [], related_job_id: null,
    metadata: {}, created_at: "2026-10-07T09:30:00Z",
  });
  const workspace = () => ({
    id: "workspace", space_id: "space", collection_id: "alpha", status: "active", title: "Account tasks",
    context: { phase: "maintenance", active_job_id: running ? "job" : "" }, test_briefs: [], candidates: [], operation_plan: null,
    messages: [
      message("request-1", "user", "Find account login cases", "CASE_QUERY"),
      message("result-1", "assistant", "Found 4 account login cases.", "CASE_QUERY"),
      message("request-2", "user", "Explain password validation", "KNOWLEDGE_QA"),
      message("result-2", "assistant", "Passwords require at least 8 characters.", "KNOWLEDGE_QA"),
      message("request-3", "user", "Review missing account coverage", "COVERAGE_ANALYZE"),
      message("result-3", "assistant", running ? "" : "Coverage review complete: add a locked account scenario.", "COVERAGE_ANALYZE", running ? "running" : "completed"),
    ],
    workflow_runs: [{ job_id: "job", message_id: "result-3", status: running ? "running" : "completed", current_stage: "context.prepared", progress: running ? 20 : 100, stages: [] }],
  });
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = [];
    if (path.endsWith("/generation-jobs/job/events")) {
      await route.fulfill({ contentType: "text/event-stream", body: 'event: context.prepared\ndata: {"progress":10}\n\n' });
      return;
    }
    if (path.endsWith("/generation-jobs/job")) data = { id: "job", status: running ? "running" : "completed", stage: "test_case.generated", progress: 75, stages: [1, 2].map(attempt => ({ stage: "test_case.generated", status: "completed", attempt })) };
    else if (path.endsWith("/auth/me")) data = { id: "user", email: "test@example.com", display_name: "Tester", spaces: [{ id: "space", name: "Space", role: "owner" }] };
    else if (path.endsWith("/generation-models")) data = { models: [{ id: "auto", label: "Auto" }], default_model_id: "auto" };
    else if (path.endsWith("/spaces/space/collections")) data = [collection];
    else if (path.endsWith("/collections/alpha")) data = collection;
    else if (path.endsWith("/messages") && route.request().method() === "POST") sends++;
    else if (path.includes("/workspaces/") || path.includes("/conversations/") || path.endsWith("/workspace")) data = workspace();
    await route.fulfill({ json: data });
  });
  await page.goto("/workbench/collections/alpha");
  const composer = page.getByRole("textbox", { name: "Conversation message", exact: true });
  await expect(composer).toBeDisabled();
  await expect(page.locator(".case-conversation-running")).toBeVisible();
  await expect(page.locator(".conversation-task-flow")).toBeVisible();
  await expect(page.locator(".conversation-task-flow li")).toHaveCount(3);
  await expect(page.locator(".case-task-workspace .task-workflow")).toHaveCount(0);
  await expect(page.locator(".case-task-running")).toContainText("Follow progress or provide details in the conversation");
  await page.getByRole("button", { name: "Result history" }).click();
  await page.locator(".case-task-history > button").filter({ hasText: "Query test cases" }).click();
  await expect(page.locator(".case-task-result")).toHaveCount(0);
  await expect(page.locator("#case-message-result-1")).toContainText("Found 4 account login cases.");
  await expect(composer).toBeDisabled();
  expect(sends).toBe(0);
  running = false;
  await page.reload();
  await expect(composer).toBeEnabled();
  await expect(page.locator(".case-conversation-running")).toHaveCount(0);
  await expect(page.locator(".case-task-result")).toHaveCount(0);
  await expect(page.locator("#case-message-result-3")).toContainText("Coverage review complete");
  await page.getByRole("button", { name: "Result history" }).click();
  await expect(page.locator(".case-task-history > button").filter({ hasText: "Knowledge Q&A" })).toHaveCount(0);
  await page.locator(".case-task-history > button").filter({ hasText: "Query test cases" }).click();
  await expect(page.locator(".case-task-workspace")).not.toContainText("Passwords require at least 8 characters.");
  await page.getByRole("button", { name: "View request in conversation" }).click();
  await expect(page.locator("#case-message-request-1")).toBeInViewport();
  await page.getByRole("button", { name: "Generate cases", exact: true }).click();
  await expect(composer).toHaveValue("Generate cases for the current collection: ");
  await expect(composer).toBeFocused();
  expect(sends).toBe(0);
  await page.screenshot({ path: testInfo.outputPath("conversation-workstation.png"), fullPage: true });
});
