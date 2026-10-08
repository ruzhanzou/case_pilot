import { expect, test, type Page } from "@playwright/test";

test.use({ viewport: { width: 1440, height: 900 } });

async function setup(page: Page, kind: "coverage" | "review" | "modify" | "delete" | "candidate") {
  const snapshot = { title: "Login succeeds", module: "Login", priority: "P1", case_type: "功能", tags: [],
    preconditions: ["Account ready"], steps: [{ id: "step", action: "Submit", expected: "Success" }], source_refs: [] };
  let cases = [0, 1].map((i) => ({ ...snapshot, id: `case${i}`, case_key: `TC-${i}`,
    collection_ids: ["alpha"], current_revision_id: `rev${i}`, revision_number: 1, source: "test" }));
  let settled = "";
  const originalCases = cases.map((item) => ({ ...item }));
  let submitted: Record<string, string[]> | undefined;
  const collection = { id: "alpha", space_id: "space", name: "User flow", lifecycle_status: "maintenance", case_count: 2, mind_map_notes: [] };
  const change = () => ({ id: "change", conversation_id: "workspace", status: settled || "ready", items: originalCases.map((item) => ({
    ref: item.id, target_type: "formal", operation: kind, base_snapshot: item,
    status: settled === "applied" && submitted?.[item.id]?.length ? "applied" : settled ? "rejected" : "pending",
    accepted_fields: submitted?.[item.id] ?? [],
    proposed_snapshot: { ...item, title: "Updated title" },
    field_diff: [{ field: kind === "delete" ? "delete" : "title", before: item.title, after: "Updated title" }],
  })) });
  const workspace = () => ({ id: "workspace", space_id: "space", collection_id: "alpha", status: "active", title: "User flow",
    context: { active_job_id: (kind === "review" || kind === "coverage") ? "job" : "", phase: kind === "candidate" && !settled ? "candidate_review" : "maintenance", active_view: "list", selected_case_id: "case0" },
    test_briefs: [], candidates: kind === "candidate" && !settled ? [{ id: "candidate", ref: "C-1", snapshot, status: "candidate", included: true, version: 1, position: 0, updated_at: "2026-10-06" }] : [],
    messages: [{ id: "answer", role: "assistant", intent: (kind === "review" || kind === "coverage") ? (kind === "coverage" ? "COVERAGE_ANALYZE" : "CASE_REVIEW") : kind === "candidate" ? "CASE_GENERATE" : kind === "delete" ? "CASE_DELETE" : "CASE_MODIFY",
      status: settled ? "completed" : (kind === "review" || kind === "coverage") || kind === "candidate" ? "completed" : "awaiting_confirmation", content: settled ? "Changes saved" : "LONG DETAIL SHOULD STAY IN WORKSPACE",
      citations: [], target_case_ids: ["case0", "case1"], related_job_id: (kind === "review" || kind === "coverage") || kind === "candidate" ? "job" : null,
      metadata: (kind === "review" || kind === "coverage") ? { checked_case_count: 2, analysis_report: { summary: "Review", findings: [{ title: "Duplicate login coverage", severity: "high", case_refs: ["case0", "case1"], evidence: "Same steps", recommendation: "Keep one" }], limitations: [] } }
        : kind === "candidate" ? {} : { change_set_id: "change", ...(settled ? { action: settled } : {}) } }],
    workflow_runs: (kind === "review" || kind === "coverage") || kind === "candidate" ? [{ job_id: "job", message_id: "answer", status: "completed", stages: [{ stage: "context.prepared", progress: 10, status: "completed" }] }] : [],
    operation_plan: (kind === "review" || kind === "coverage") || kind === "candidate" ? null : { operations: [{ id: "operation", intent: kind === "delete" ? "CASE_DELETE" : "CASE_MODIFY", status: settled ? "completed" : "awaiting_confirmation", related_change_set_id: "change", target: {}, payload: {}, result: {} }] },
  });
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = [];
    if (path.endsWith("/auth/me")) data = { id: "user", email: "test@example.com", display_name: "Tester", spaces: [{ id: "space", name: "Space", role: "owner" }] };
    else if (path.endsWith("/generation-models")) data = { models: [{ id: "auto", label: "Auto" }], default_model_id: "auto" };
    else if (path.endsWith("/spaces/space/collections")) data = [collection];
    else if (path.endsWith("/collections/alpha")) data = collection;
    else if (path.endsWith("/collections/alpha/test-cases")) data = cases;
    else if (path.endsWith("/test-cases/case0") && route.request().method() === "PATCH") {
      const input = route.request().postDataJSON();
      cases = cases.map((item) => item.id === "case0" ? {
        ...item, ...input, current_revision_id: "rev0-next", revision_number: 2,
      } : item);
      data = cases[0];
    }
    else if (path.endsWith("/case-change-sets/change/apply")) {
      submitted = route.request().postDataJSON().accepted_fields;
      settled = "applied";
      cases = kind === "delete" ? cases.filter((item) => !submitted?.[item.id]?.includes("delete"))
        : cases.map((item) => submitted?.[item.id]?.includes("title") ? { ...item, title: "Updated title", revision_number: 2 } : item);
      data = { change_set: change(), test_cases: cases, candidate_snapshots: [] };
    } else if (path.endsWith("/case-change-sets/change/reject")) { settled = "rejected"; data = change(); }
    else if (path.endsWith("/case-change-sets/change")) data = change();
    else if (path.endsWith("/candidates/commit")) { settled = "applied"; data = cases; }
    else if (path.includes("/workspaces/") || path.includes("/conversations/") || path.endsWith("/workspace")) data = workspace();
    await route.fulfill({ json: data });
  });
  await page.goto("/workbench/collections/alpha");
  return { submitted: () => submitted, cases: () => cases };
}

test("chat shows process and summary; review evidence lives in workspace", async ({ page }) => {
  await setup(page, "review");
  await expect(page.locator(".principle-analysis-summary")).toContainText("Checked 2 cases");
  await expect(page.locator(".principle-message")).not.toContainText("LONG DETAIL");
  await expect(page.locator(".principle-review-answer")).toHaveText("Review");
  await expect(page.locator(".principle-review-highlights")).toHaveCount(0);
  await page.getByRole("button", { name: "Discuss priorities", exact: true }).click();
  const composer = page.getByRole("textbox", { name: "Conversation message", exact: true });
  await expect(composer).toHaveValue(/Duplicate login coverage/);
  await expect(composer).toBeFocused();
  await expect(page.getByRole("button", { name: "Discuss priorities", exact: true })).toBeDisabled();
  await composer.fill("");
  await page.getByText("Processing steps · Completed", { exact: true }).click();
  await expect(page.locator(".principle-workflow-stage")).toBeVisible();
  await page.getByRole("button", { name: "View plan in workspace" }).click();
  await expect(page.getByRole("region", { name: "Case workspace" })).toContainText("Duplicate login coverage");
  await expect(page.locator(".principle-case-area .collection-changes__toolbar")).toHaveCount(0);
  const plan = page.locator(".case-review-plan");
  await plan.getByRole("radio", { name: "TC-0", exact: true }).check();
  await plan.getByRole("button", { name: "TC-0", exact: true }).click();
  await expect(page.locator('[data-id="case-case0"]')).toHaveClass(/selected/);
  await page.getByRole("button", { name: "Case workspace", exact: true }).click();
  await expect(plan.getByRole("radio", { name: "TC-0", exact: true })).toBeChecked();
});

for (const kind of ["modify", "delete"] as const) {
  test(`${kind}: preview, selective confirmation, persisted list, reload`, async ({ page }) => {
    const state = await setup(page, kind);
    await page.getByRole("button", { name: "Case workspace", exact: true }).click();
    const review = page.locator(".collection-changes__review");
    await expect(review).toBeVisible();
    expect(state.submitted()).toBeUndefined();
    await review.locator("details").nth(1).evaluate((el: HTMLDetailsElement) => { el.open = true; });
    await review.locator('input[type="checkbox"]').nth(1).uncheck();
    await review.getByRole("button", { name: kind === "delete" ? "Apply selected deletions" : "Apply selected changes" }).click();
    await expect(page.locator('.collection-changes__badge')).toHaveText('Applied');
    await expect(review.getByRole('button', { name: /Apply selected/ })).toHaveCount(0);
    expect(state.submitted()).toEqual({ case0: [kind === "delete" ? "delete" : "title"], case1: [] });
    expect(state.cases().find((item) => item.id === "case1")?.revision_number).toBe(1);
    await expect(page).toHaveURL(/workbench\/collections\/alpha/);
    await page.getByRole('button', { name: 'Test case list', exact: true }).click();
    await page.reload();
    await expect(page.locator(".principle-case-row")).toHaveCount(kind === "delete" ? 1 : 2);
  });
}

test("cancel leaves cases unchanged and retains a read-only review", async ({ page }) => {
  const state = await setup(page, "delete");
  await page.getByRole("button", { name: "Case workspace", exact: true }).click();
  await page.getByRole("button", { name: "Cancel changes", exact: true }).click();
  await expect(page.locator('.collection-changes__badge')).toHaveText('Not applied');
  await expect(page.getByRole('button', { name: 'Apply selected deletions', exact: true })).toHaveCount(0);
  expect(state.submitted()).toBeUndefined();
  expect(state.cases()).toHaveLength(2);
});

test("candidate confirmation keeps the user in the collection workspace", async ({ page }) => {
  await setup(page, "candidate");
  await page.getByRole("button", { name: "Add to official collection", exact: true }).click();
  await expect(page).toHaveURL(/workbench\/collections\/alpha/);
  await expect(page.locator(".principle-case-row")).toHaveCount(2);
  await expect(page.getByRole("button", { name: "Add to official collection", exact: true })).toHaveCount(0);
});

test("manual edit stays in the case workspace and saves a new revision", async ({ page }) => {
  const state = await setup(page, "review");
  await page.getByRole("button", { name: "Mind map", exact: true }).click();
  await page.getByRole("button", { name: "Open the full editor for Login succeeds" }).first().click();
  await expect(page.getByRole("button", { name: "Case workspace", exact: true })).toHaveClass(/is-active/);
  const editor = page.getByRole("region", { name: "Edit structured test case" });
  await expect(editor).toBeVisible();
  await editor.getByRole("textbox", { name: "Test case name" }).fill("Login succeeds with MFA");
  await page.getByRole("button", { name: "Mind map", exact: true }).click();
  await page.getByRole("button", { name: "Case workspace", exact: true }).click();
  await expect(editor.getByRole("textbox", { name: "Test case name" })).toHaveValue("Login succeeds with MFA");
  await editor.getByRole("button", { name: "Save as new revision" }).click();
  await expect(editor).toHaveCount(0);
  expect(state.cases()[0].title).toBe("Login succeeds with MFA");
  expect(state.cases()[0].revision_number).toBe(2);
  await expect(page.getByRole("button", { name: "Case workspace", exact: true })).toHaveClass(/is-active/);
  await page.getByRole("button", { name: "Test case list", exact: true }).click();
  await page.getByRole("button", { name: "Show case details", exact: true }).click();
  await expect(page.locator(".principle-inspector").getByRole("heading")).toHaveText("Login succeeds with MFA");
});

 test("coverage findings offer an editable follow-up without submitting a mutation", async ({ page }) => {
  const state = await setup(page, "coverage");
  await page.getByRole("button", { name: "Draft missing cases", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Conversation message", exact: true })).toHaveValue(/Keep one/);
  expect(state.submitted()).toBeUndefined();
  expect(state.cases()).toHaveLength(2);
  await page.getByRole("textbox", { name: "Conversation message", exact: true }).fill("My unfinished request");
  await expect(page.getByRole("button", { name: "Draft missing cases", exact: true })).toBeDisabled();
});
