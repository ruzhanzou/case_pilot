import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 1600, height: 1000 } });

for (const candidateMode of [false, true]) {
  test(`AI polish scopes suggestions to the current ${candidateMode ? "candidate" : "case"}`, async ({ page }, testInfo) => {
    const collection = { id: "alpha", space_id: "space", name: "Login cases", lifecycle_status: candidateMode ? "candidate_review" : "maintenance", case_count: 2, mind_map_notes: [] };
    const snapshot = { title: "Registered user login", module: "Login", priority: "P1", case_type: "功能", tags: [], preconditions: ["User exists"], steps: [{ id: "step", action: "Submit login", expected: "Login succeeds" }], source: "Manual", source_refs: [] };
    const cases = ["one", "two"].map(id => ({ ...snapshot, id, case_key: id, collection_ids: ["alpha"], revision_number: 1, current_revision_id: `rev-${id}` }));
    let candidate = { id: "candidate-one", ref: "candidate-ref", version: 1, included: true, status: "ready", snapshot };
    let request: Record<string, unknown> | undefined;
    let saves = 0;
    let fail = true;
    const workspace = () => ({ id: "workspace", space_id: "space", collection_id: "alpha", status: "active", title: "Login", context: { phase: candidateMode ? "candidate_review" : "maintenance", active_view: "list" }, test_briefs: [], candidates: candidateMode ? [candidate] : [], operation_plan: null, operation_history: [], messages: [], workflow_runs: [] });
    await page.route("**/api/v1/**", async route => {
      const path = new URL(route.request().url()).pathname;
      let data: unknown = [];
      if (path.endsWith("/auth/me")) data = { id: "user", email: "test@example.com", display_name: "Tester", spaces: [{ id: "space", name: "Space", role: "owner" }] };
      else if (path.endsWith("/generation-models")) data = { models: [{ id: "auto", label: "Auto" }], default_model_id: "auto" };
      else if (path.endsWith("/spaces/space/collections")) data = [collection];
      else if (path.endsWith("/collections/alpha")) data = collection;
      else if (path.endsWith("/collections/alpha/test-cases")) data = cases;
      else if (path.endsWith("/workspace-candidates/candidate-one") && route.request().method() === "PATCH") {
        saves++;
        candidate = { ...candidate, snapshot: route.request().postDataJSON().snapshot, version: candidate.version + 1 };
        data = candidate;
      } else if (path.endsWith("/messages") && route.request().method() === "POST") {
        request = route.request().postDataJSON();
        if (fail) { await route.fulfill({ status: 503, json: { detail: "Please retry" } }); return; }
        data = { conversation_id: "workspace", intent: "CASE_MODIFY", action: { type: "awaiting_confirmation" }, operation_plan: null };
      } else if (path.includes("/workspaces/") || path.includes("/conversations/") || path.endsWith("/workspace")) data = workspace();
      await route.fulfill({ json: data });
    });
    await page.goto("/workbench/collections/alpha");
    const inspector = page.locator(".principle-inspector");
    await inspector.getByRole("button", { name: "Close case details", exact: true }).click();
    await expect(inspector).toHaveCount(0);
    const rows = page.locator(".principle-case-row");
    await rows.first().getByRole("button").first().click();
    await expect(inspector).toBeVisible();
    if (!candidateMode) {
      await inspector.getByRole("button", { name: "Close case details", exact: true }).click();
      await rows.nth(1).getByRole("button").first().click();
      await expect(inspector).toBeVisible();
      await rows.first().getByRole("button").first().click();
    }
    if (candidateMode) {
      await expect(inspector.getByLabel("Title", { exact: true })).toHaveValue("Registered user login");
      await inspector.getByLabel("Title", { exact: true }).fill("Updated login title");
    } else await expect(inspector).toContainText("Registered user login");
    await inspector.getByRole("button", { name: "AI polish", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("checkbox")).toHaveCount(4);
    for (const checkbox of await dialog.getByRole("checkbox").all()) await checkbox.uncheck();
    const submit = dialog.getByRole("button", { name: /generate suggestions/i });
    await expect(submit).toBeDisabled();
    await dialog.getByLabel("Additional requirements (optional)").fill("Keep wording concise");
    await dialog.getByRole("checkbox", { name: /Split procedure/ }).check();
    await page.screenshot({ path: testInfo.outputPath("ai-polish.png") });
    await submit.click();
    await expect(dialog.getByRole("alert")).toContainText("Please retry");
    expect(request?.intent_override).toBe("CASE_MODIFY");
    expect(request?.targets).toEqual([candidateMode ? { kind: "case", candidate_refs: ["candidate-ref"] } : { kind: "case", case_ids: ["one"] }]);
    expect(request?.content).toContain("Keep wording concise");
    expect(request?.content).toContain("Split procedure steps");
    expect(request?.content).not.toContain("Clarify title");
    if (candidateMode) { expect(saves).toBe(1); expect(candidate.snapshot.title).toBe("Updated login title"); }
    else expect(saves).toBe(0);
    fail = false;
    await submit.click();
    await expect(dialog).toHaveCount(0);
    expect(saves).toBe(candidateMode ? 1 : 0);
  });
}
