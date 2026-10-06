import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 1600, height: 1000 } });

test("maintenance task restores scope across reload, map/list and report navigation", async ({ page }, testInfo) => {
  const collection = { id: "alpha", space_id: "space", name: "Payments", case_count: 3,
    lifecycle_status: "maintenance", mind_map_notes: [] };
  const cases = Array.from({ length: 3 }, (_, i) => ({
    id: `case${i}`, case_key: `TC-${i}`, title: `Scenario ${i}`, collection_ids: ["alpha"],
    module: i < 2 ? "支付/退款" : "账号/登录", priority: "P1", case_type: "功能", tags: [],
    current_revision_id: `rev${i}`, revision_number: 1, preconditions: ["Ready"],
    steps: [{ id: "step", action: "Submit", expected: "Pass" }], source: "manual", source_refs: [],
  }));
  let completed = false;
  let eventConnections = 0;
  let activeView = "list";
  const workspace = () => ({
    id: "workspace", space_id: "space", collection_id: "alpha", title: "Payments", status: "active",
    context: { phase: "maintenance", active_job_id: completed ? "" : "job", active_view: activeView,
      selected_targets: [{ label: "Old selection", target: { kind: "case", case_ids: ["case0"] } }] },
    test_briefs: [], candidates: [],
    messages: [{ id: "answer", role: "assistant", intent: "CASE_REVIEW", status: completed ? "completed" : "running",
      content: completed ? "Review complete" : "Checking 2 cases", related_job_id: "job", citations: [],
      metadata: completed ? { analysis_report: { findings: [{ title: "Missing expected result", case_refs: ["case1"] }] } } : {} }],
    workflow_runs: [{ job_id: "job", message_id: "answer", operation: "knowledge_qa",
      status: completed ? "completed" : "running", stages: [], progress: completed ? 100 : 20 }],
    operation_plan: { status: completed ? "completed" : "running", operations: [{
      id: "operation", sequence: 0, intent: "CASE_REVIEW", status: completed ? "completed" : "running",
      target: { resolved: true, case_ids: ["case0", "case1"], candidate_refs: [] }, payload: {}, result: {},
    }] },
  });
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/events")) {
      eventConnections++;
      return route.fulfill({ contentType: "text/event-stream", body: 'event: context.prepared\ndata: {"progress":20}\n\n' });
    }
    let data: unknown = [];
    if (path.endsWith("/auth/me")) data = { id: "user", email: "test@example.com", display_name: "Tester",
      spaces: [{ id: "space", name: "Space", role: "owner" }] };
    else if (path === "/api/v1/generation-models") data = { models: [], default_model_id: "auto" };
    else if (path === "/api/v1/spaces/space/collections") data = [collection];
    else if (path === "/api/v1/collections/alpha") data = collection;
    else if (path === "/api/v1/collections/alpha/test-cases") data = cases;
    else if (path.includes("generation-jobs")) data = { id: "job", status: completed ? "completed" : "running" };
    else if (path.endsWith("/workspace") || path.includes("/workspaces/") || path.includes("/conversations/")) {
      if (route.request().method() === "PATCH") {
        activeView = route.request().postDataJSON().active_view ?? activeView;
      }
      data = workspace();
    }
    await route.fulfill({ json: data });
  });
  await page.goto("/workbench/collections/alpha");
  await expect.poll(() => eventConnections).toBeGreaterThan(0);
  await expect(page.locator(".principle-case-row.is-ai-running")).toHaveCount(2);
  await expect(page.locator(".principle-composer textarea")).toBeDisabled();
  await page.reload();
  await expect.poll(() => eventConnections).toBeGreaterThan(1);
  await expect(page.locator(".principle-case-row.is-ai-running")).toHaveCount(2);
  await page.getByRole("button", { name: /^(Mind map|用例脑图)$/ }).click();
  await expect(page.locator(".case-map-node--case.is-ai-running")).toHaveCount(2);
  completed = true;
  await page.reload();
  await expect(page.locator(".principle-composer textarea")).toBeEnabled();
  await page.getByRole("button", { name: /Locate TC-1|定位 TC-1/ }).click();
  await expect(page.locator('[data-id="case-case1"] .case-map-node')).toHaveClass(/is-selected/);
  await page.screenshot({ path: testInfo.outputPath("analysis-report-location.png") });
  let submittedTargets: unknown;
  await page.route("**/conversations/workspace/messages", async (route) => {
    submittedTargets = route.request().postDataJSON().targets;
    await route.fulfill({ json: { conversation_id: "workspace", action: {}, operation_plan: null } });
  });
  await page.locator(".principle-composer textarea").fill("修改 TC-1 的预期结果");
  await page.locator('.principle-composer button[type="submit"]').click();
  await expect.poll(() => submittedTargets).toEqual([{ kind: "case", case_ids: ["case1"] }]);
});
