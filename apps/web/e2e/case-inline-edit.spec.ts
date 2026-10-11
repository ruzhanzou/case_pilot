import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 1600, height: 1000 } });

for (const view of ["list", "map"]) {
  test(`manual editing preserves the ${view} view and saves in details`, async ({ page }, testInfo) => {
    const collection = { id: "alpha", space_id: "space", name: "Login cases", lifecycle_status: "maintenance", case_count: 1, mind_map_notes: [] };
    let testCase = { id: "one", case_key: "LOGIN-1", collection_ids: ["alpha"], title: "Registered user login", module: "Login", priority: "P1", case_type: "功能", tags: [], preconditions: ["User exists"], steps: [{ id: "step", action: "Submit login", expected: "Login succeeds" }], source: "Manual", source_refs: [], revision_number: 1, current_revision_id: "rev-1" };
    const workspace = { id: "workspace", space_id: "space", collection_id: "alpha", status: "active", title: "Login", context: { phase: "maintenance", active_view: view }, test_briefs: [], candidates: [], operation_plan: null, operation_history: [], messages: [], workflow_runs: [] };
    let saves = 0;
    const viewWrites: string[] = [];
    await page.route("**/api/v1/**", async route => {
      const path = new URL(route.request().url()).pathname;
      const body = route.request().postDataJSON();
      if (body?.active_view) viewWrites.push(body.active_view);
      let data: unknown = [];
      if (path.endsWith("/auth/me")) data = { id: "user", email: "test@example.com", display_name: "Tester", spaces: [{ id: "space", name: "Space", role: "owner" }] };
      else if (path.endsWith("/generation-models")) data = { models: [{ id: "auto", label: "Auto" }], default_model_id: "auto" };
      else if (path.endsWith("/spaces/space/collections")) data = [collection];
      else if (path.endsWith("/collections/alpha")) data = collection;
      else if (path.endsWith("/collections/alpha/test-cases")) data = [testCase];
      else if (path.endsWith("/test-cases/one") && route.request().method() === "PATCH") {
        saves++;
        testCase = { ...testCase, ...body, revision_number: 2 };
        data = testCase;
      } else if (path.includes("/workspaces/") || path.includes("/conversations/") || path.endsWith("/workspace")) data = workspace;
      await route.fulfill({ json: data });
    });
    await page.goto("/workbench/collections/alpha");
    const inspector = page.locator(".principle-inspector");
    const tab = page.getByRole("button", { name: view === "list" ? "Test case list" : "Mind map", exact: true });
    await expect(tab).toHaveClass(/is-active/);
    await inspector.getByRole("button", { name: "Edit", exact: true }).click();
    const editor = inspector.getByRole("region", { name: "Edit structured test case" });
    await expect(editor).toBeVisible();
    for (const width of [1600, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      await expect(editor).toBeVisible();
      const bounds = await inspector.evaluate(el => {
        const panel = el.getBoundingClientRect();
        const form = el.querySelector("form")!;
        return {
          overflow: el.scrollWidth > el.clientWidth,
          formOverflow: form.scrollWidth > form.clientWidth,
          outside: [...el.querySelectorAll("input, select, textarea, button")].some(node => {
            const rect = node.getBoundingClientRect();
            return rect.left < panel.left || rect.right > panel.right;
          }),
        };
      });
      expect(bounds).toEqual({ overflow: false, formOverflow: false, outside: false });
      await expect(editor.getByRole("button", { name: "Save as new revision", exact: true })).toBeInViewport();
      await page.screenshot({ path: testInfo.outputPath(`inline-editor-${width}.png`) });
    }

    await expect(tab).toHaveClass(/is-active/);
    await editor.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(editor).toHaveCount(0);
    expect(saves).toBe(0);
    await inspector.getByRole("button", { name: "Edit", exact: true }).click();
    await editor.getByLabel("Test case name", { exact: true }).fill("Updated login");
    await editor.getByRole("button", { name: "Save as new revision", exact: true }).click();
    await expect(editor).toHaveCount(0);
    await expect(inspector).toContainText("Updated login");
    await expect(tab).toHaveClass(/is-active/);
    expect(saves).toBe(1);
    expect(viewWrites).not.toContain("plan");
  });
}
