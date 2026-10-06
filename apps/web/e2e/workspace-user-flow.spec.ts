import { expect, test, type Page } from "@playwright/test";

test.use({ viewport: { width: 1440, height: 900 } });

async function setup(page: Page, kind: "review" | "modify" | "delete" | "candidate") {
  const snapshot = { title: "Login succeeds", module: "Login", priority: "P1", case_type: "功能", tags: [],
    preconditions: ["Account ready"], steps: [{ id: "step", action: "Submit", expected: "Success" }], source_refs: [] };
  let cases = [0, 1].map((i) => ({ ...snapshot, id: `case${i}`, case_key: `TC-${i}`,
    collection_ids: ["alpha"], current_revision_id: `rev${i}`, revision_number: 1, source: "test" }));
  let settled = "";
  let submitted: Record<string, string[]> | undefined;
  const collection = { id: "alpha", space_id: "space", name: "User flow", lifecycle_status: "maintenance", case_count: 2, mind_map_notes: [] };
  const change = () => ({ id: "change", conversation_id: "workspace", status: settled || "ready", items: cases.map((item) => ({
    ref: item.id, target_type: "formal", operation: kind, base_snapshot: item,
    proposed_snapshot: { ...item, title: "Updated title" },
    field_diff: [{ field: kind === "delete" ? "delete" : "title", before: item.title, after: "Updated title" }],
  })) });
  const workspace = () => ({ id: "workspace", space_id: "space", collection_id: "alpha", status: "active", title: "User flow",
    context: { active_job_id: kind === "review" ? "job" : "", phase: kind === "candidate" && !settled ? "candidate_review" : "maintenance", active_view: "list", selected_case_id: "case0" },
    test_briefs: [], candidates: kind === "candidate" && !settled ? [{ id: "candidate", ref: "C-1", snapshot, status: "candidate", included: true, version: 1, position: 0, updated_at: "2026-10-06" }] : [],
    messages: [{ id: "answer", role: "assistant", intent: kind === "review" ? "CASE_REVIEW" : kind === "candidate" ? "CASE_GENERATE" : kind === "delete" ? "CASE_DELETE" : "CASE_MODIFY",
      status: settled ? "completed" : kind === "review" || kind === "candidate" ? "completed" : "awaiting_confirmation", content: settled ? "Changes saved" : "LONG DETAIL SHOULD STAY IN WORKSPACE",
      citations: [], target_case_ids: ["case0", "case1"], related_job_id: kind === "review" || kind === "candidate" ? "job" : null,
      metadata: kind === "review" ? { checked_case_count: 2, analysis_report: { summary: "Review", findings: [{ title: "Duplicate login coverage", severity: "high", case_refs: ["case0", "case1"], evidence: "Same steps", recommendation: "Keep one" }], limitations: [] } }
        : kind === "candidate" ? {} : { change_set_id: "change", ...(settled ? { action: settled } : {}) } }],
    workflow_runs: kind === "review" || kind === "candidate" ? [{ job_id: "job", message_id: "answer", status: "completed", stages: [{ stage: "context.prepared", progress: 10, status: "completed" }] }] : [],
    operation_plan: kind === "review" || kind === "candidate" ? null : { operations: [{ id: "operation", intent: kind === "delete" ? "CASE_DELETE" : "CASE_MODIFY", status: settled ? "completed" : "awaiting_confirmation", related_change_set_id: "change", target: {}, payload: {}, result: {} }] },
  });
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = [];
    if (path.endsWith("/auth/me")) data = { id: "user", email: "test@example.com", display_name: "Tester", spaces: [{ id: "space", name: "Space", role: "owner" }] };
    else if (path.endsWith("/generation-models")) data = { models: [{ id: "auto", label: "Auto" }], default_model_id: "auto" };
    else if (path.endsWith("/spaces/space/collections")) data = [collection];
    else if (path.endsWith("/collections/alpha")) data = collection;
    else if (path.endsWith("/collections/alpha/test-cases")) data = cases;
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
  await page.getByText("Processing steps · Completed", { exact: true }).click();
  await expect(page.locator(".principle-workflow-stage")).toBeVisible();
  await page.getByRole("button", { name: "View plan in workspace" }).click();
  await expect(page.getByRole("region", { name: "Review and change plan" })).toContainText("Duplicate login coverage");
  await expect(page.locator("details.collection-changes")).not.toHaveAttribute("open", "");
  const plan = page.locator(".case-review-plan");
  await plan.getByRole("radio", { name: "TC-0", exact: true }).check();
  await plan.getByRole("button", { name: "TC-0", exact: true }).click();
  await expect(page.locator('[data-id="case-case0"]')).toHaveClass(/selected/);
  await page.getByRole("button", { name: "Review plan", exact: true }).click();
  await expect(plan.getByRole("radio", { name: "TC-0", exact: true })).toBeChecked();
});

for (const kind of ["modify", "delete"] as const) {
  test(`${kind}: preview, selective confirmation, persisted list, reload`, async ({ page }) => {
    const state = await setup(page, kind);
    const review = page.locator(".collection-changes__review");
    await expect(review).toBeVisible();
    expect(state.submitted()).toBeUndefined();
    await review.locator("details").nth(1).evaluate((el: HTMLDetailsElement) => { el.open = true; });
    await review.locator('input[type="checkbox"]').nth(1).uncheck();
    await review.getByRole("button", { name: kind === "delete" ? "Apply selected deletions" : "Apply selected changes" }).click();
    await expect(review).toHaveCount(0);
    expect(state.submitted()).toEqual({ case0: [kind === "delete" ? "delete" : "title"], case1: [] });
    expect(state.cases().find((item) => item.id === "case1")?.revision_number).toBe(1);
    await expect(page).toHaveURL(/workbench\/collections\/alpha/);
    await page.reload();
    await expect(page.locator(".collection-changes__review")).toHaveCount(0);
    await expect(page.locator(".principle-case-row")).toHaveCount(kind === "delete" ? 1 : 2);
  });
}

test("cancel leaves cases unchanged and removes pending review", async ({ page }) => {
  const state = await setup(page, "delete");
  await page.getByRole("button", { name: "Cancel changes", exact: true }).click();
  await expect(page.locator(".collection-changes__review")).toHaveCount(0);
  expect(state.submitted()).toBeUndefined();
  expect(state.cases()).toHaveLength(2);
});

test("candidate confirmation keeps the user in the collection workspace", async ({ page }) => {
  await setup(page, "candidate");
  await page.getByRole("button", { name: "Add selected", exact: true }).click();
  await expect(page).toHaveURL(/workbench\/collections\/alpha/);
  await expect(page.locator(".principle-case-row")).toHaveCount(2);
  await expect(page.getByRole("button", { name: "Add selected", exact: true })).toHaveCount(0);
});
