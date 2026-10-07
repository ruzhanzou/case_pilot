import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 1600, height: 1000 } });

test("coverage finding starts a linked generation, streams completion, and retains candidates after incorporation", async ({ page }) => {
  const snapshot = { title: "Login succeeds", module: "Account", priority: "P1", case_type: "功能", tags: [], preconditions: ["Account ready"], steps: [{ id: "step", action: "Sign in", expected: "Home is visible" }], source_refs: [] };
  const cases = [{ ...snapshot, id: "case-1", case_key: "TC-1", current_revision_id: "rev-1", revision_number: 1, collection_ids: ["alpha"] }];
  const report = { summary: "Missing lockout coverage", findings: [{ title: "Locked account cannot sign in", severity: "high", case_refs: ["case-1"], evidence: "Account policy requires lockout", recommendation: "Add locked account rejection", basis: "requirement", relationship: "coverage", requirement_refs: ["Account policy §3"] }], limitations: [] };
  const message = (id: string, intent: string, content: string, metadata = {}, role = "assistant") => ({ id, role, intent, content, metadata, status: "completed", citations: [], target_case_ids: [], related_job_id: null, created_at: "2026-10-07T08:00:00Z" });
  const baseOperation = { confidence: 1, target: { case_ids: ["case-1"], resolved: true }, payload: {}, requires_confirmation: false, related_job_id: null, related_change_set_id: null, error_code: null, created_at: "2026-10-07T08:00:00Z" };
  const review = { ...baseOperation, id: "review", source_message_id: "request", sequence: 0, intent: "COVERAGE_ANALYZE", status: "completed", result: { analysis_report: report, scope_versions: { "case-1": "rev-1" }, scope_count: 1 } };
  let phase = "review";
  let included = true;
  let submitted: Record<string, unknown> | undefined;
  let finishJob: (() => void) | undefined;
  const candidate = () => ({ id: "candidate", generation_job_id: "job", ref: "C-1", version: 1, position: 0, snapshot: { ...snapshot, title: "Locked account is rejected" }, status: phase === "applied" ? "incorporated" : "candidate", included, updated_at: "2026-10-07T08:30:00Z" });
  const generation = () => ({ ...baseOperation, id: "generate", source_message_id: "followup", sequence: 0, intent: "CASE_GENERATE", status: phase === "running" ? "running" : phase === "applied" ? "completed" : "awaiting_confirmation", related_job_id: "job", payload: { source_operation_id: "review", instruction: "Add missing lockout coverage" }, result: { candidate_ids: phase === "running" ? [] : ["candidate"] }, created_at: "2026-10-07T08:30:00Z" });
  const workspace = () => ({ id: "workspace", space_id: "space", collection_id: "alpha", title: "Account quality", status: "active", context: { active_view: "plan", phase: phase === "ready" ? "candidate_review" : "maintenance", active_job_id: phase === "running" ? "job" : null, active_operation_id: phase === "ready" ? "generate" : null },
    test_briefs: [], candidates: phase === "ready" ? [candidate()] : [], candidate_history: ["ready", "applied"].includes(phase) ? [candidate()] : [],
    messages: [message("request", "COVERAGE_ANALYZE", "Check account coverage", {}, "user"), message("answer", "COVERAGE_ANALYZE", "Missing lockout coverage", { operation_id: "review", analysis_report: report, checked_case_count: 1 }), ...(phase === "review" ? [] : [message("followup", "CASE_GENERATE", "Add missing lockout coverage", {}, "user"), { ...message("generated", "CASE_GENERATE", phase === "running" ? "" : "One candidate is ready", { operation_id: "generate" }), status: phase === "running" ? "running" : "completed", related_job_id: "job" }])],
    workflow_runs: phase === "review" ? [] : [{ job_id: "job", message_id: "generated", status: phase === "running" ? "running" : "completed", current_stage: phase === "running" ? "context.prepared" : "completed", progress: phase === "running" ? 10 : 100, stages: [] }],
    operation_history: phase === "review" ? [review] : [review, generation()], operation_plan: { operations: phase === "review" ? [review] : [generation()] },
  });
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = [];
    if (path.endsWith("/auth/me")) data = { id: "user", display_name: "Tester", spaces: [{ id: "space", name: "Space", role: "owner" }] };
    else if (path.endsWith("/generation-models")) data = { models: [{ id: "auto", label: "Auto" }], default_model_id: "auto" };
    else if (path.endsWith("/spaces/space/collections")) data = [{ id: "alpha", space_id: "space", name: "Account quality", lifecycle_status: "maintenance", case_count: 1 }];
    else if (path.endsWith("/collections/alpha")) data = { id: "alpha", space_id: "space", name: "Account quality", lifecycle_status: "maintenance", case_count: 1 };
    else if (path.endsWith("/collections/alpha/test-cases")) data = cases;
    else if (path.endsWith("/workspace-candidates/candidate")) { included = route.request().postDataJSON().included ?? included; data = candidate(); }
    else if (path.endsWith("/candidates/commit")) { phase = "applied"; data = cases; }
    else if (path.endsWith("/messages")) { submitted = route.request().postDataJSON(); phase = "running"; data = { intent: "CASE_GENERATE", operation_plan: { operations: [generation()] }, action: { job_id: "job" } }; }
    else if (path.endsWith("/generation-jobs/job/events")) {
      await new Promise<void>((resolve) => { finishJob = resolve; });
      phase = "ready";
      await route.fulfill({ contentType: "text/event-stream", body: 'event: generation.completed\ndata: {"job_id":"job","status":"completed"}\n\n' });
      return;
    } else if (path.endsWith("/generation-jobs/job")) data = { id: "job", status: phase === "running" ? "running" : "completed" };
    else if (path.includes("/conversations/") || path.includes("/workspaces/") || path.endsWith("/workspace")) data = workspace();
    await route.fulfill({ json: data });
  });
  await page.goto("/workbench/collections/alpha");
  await expect(page.getByText("Requirement-backed gap", { exact: true })).toBeVisible();
  await page.getByRole("checkbox", { name: "Select finding 1" }).check();
  await page.getByRole("button", { name: "Generate missing cases", exact: true }).click();
  const composer = page.getByRole("textbox", { name: "Conversation message", exact: true });
  await expect(composer).toBeDisabled();
  expect(submitted?.source_operation_id).toBe("review");
  expect(submitted?.intent_override).toBe("CASE_GENERATE");
  await expect.poll(() => Boolean(finishJob)).toBe(true);
  finishJob?.();
  await expect(composer).toBeEnabled();
  await expect(page.getByRole("region", { name: "Candidate results" })).toContainText("Locked account is rejected");
  await expect(page.locator(".case-task-detail > header")).toContainText("Awaiting confirmation");
  await page.getByRole("button", { name: "Add selected candidates", exact: true }).click();
  await page.getByRole("button", { name: "Case workspace", exact: true }).click();
  await expect(page.getByRole("region", { name: "Candidate results" })).toContainText("Added");
  await page.reload();
  await page.getByRole("button", { name: "Case workspace", exact: true }).click();
  await expect(page.locator(".case-task-history > button")).toHaveCount(2);
  await expect(page.getByRole("region", { name: "Candidate results" })).toContainText("Locked account is rejected");
  await page.getByRole("button", { name: "Source task · Analyze coverage" }).click();
  await expect(page.locator(".case-review-plan")).toContainText("Locked account cannot sign in");
  await page.screenshot({ path: "../../artifacts/case-intent-workflows.png", fullPage: true });
});

test("restored task group advances in order and pauses for confirmation", async ({ page }) => {
  const calls: string[] = [];
  const operations = ["CASE_QUERY", "CASE_REVIEW", "CASE_MODIFY", "CASE_GENERATE"].map((intent, sequence) => ({
    id: `operation-${sequence}`, source_message_id: "request", sequence, intent, status: "queued",
    confidence: 1, target: {}, payload: { instruction: intent }, result: {}, requires_confirmation: true,
    related_job_id: null, related_change_set_id: null, error_code: null, created_at: "2026-10-07T09:00:00Z",
  }));
  const messages: unknown[] = [{ id: "request", role: "user", content: "Query, review, rewrite, then generate", intent: "CASE_QUERY", status: "completed", metadata: {}, citations: [], target_case_ids: [], related_job_id: null }];
  const collection = { id: "alpha", space_id: "space", name: "Workflow queue", lifecycle_status: "maintenance", case_count: 0 };
  const workspace = () => ({ id: "workspace", space_id: "space", collection_id: "alpha", context: { phase: "maintenance", active_view: "plan" }, messages, test_briefs: [], candidates: [], workflow_runs: [], operation_history: operations, operation_plan: { source_message_id: "request", operations } });
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = [];
    if (path.endsWith("/auth/me")) data = { id: "user", display_name: "Tester", spaces: [{ id: "space", name: "Space", role: "owner" }] };
    else if (path.endsWith("/generation-models")) data = { models: [{ id: "auto", label: "Auto" }], default_model_id: "auto" };
    else if (path.endsWith("/spaces/space/collections")) data = [collection];
    else if (path.endsWith("/collections/alpha")) data = collection;
    else if (path.includes("/conversation-operations/") && path.endsWith("/resume")) {
      const id = path.split("/").at(-2)!;
      calls.push(id);
      const operation = operations.find((item) => item.id === id)!;
      operation.status = operation.intent === "CASE_MODIFY" ? "awaiting_confirmation" : "completed";
      messages.push({ id: `message-${id}`, role: "assistant", content: operation.status, intent: operation.intent, status: operation.status, metadata: { operation_id: id }, citations: [], target_case_ids: [], related_job_id: null });
      data = { action: {}, intent: operation.intent, operation_plan: { operations } };
    } else if (path.includes("/workspaces/") || path.includes("/conversations/") || path.endsWith("/workspace")) data = workspace();
    await route.fulfill({ json: data });
  });
  await page.goto("/workbench/collections/alpha");
  await expect.poll(() => calls).toEqual(["operation-0", "operation-1", "operation-2"]);
  await expect(page.getByRole("textbox", { name: "Conversation message", exact: true })).toBeEnabled();
  await expect(page.locator(".case-task-history > button")).toHaveCount(4);
  await expect(page.locator(".case-task-history")).toContainText("Waiting for previous task");
  await page.locator(".case-task-history > button").filter({ hasText: "Modify test cases" }).click();
  await expect(page.locator(".case-task-detail > header")).toContainText("Awaiting confirmation");
  expect(calls).toHaveLength(3);
});
