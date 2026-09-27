import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 1600, height: 1000 } });
for (const entry of ["/cases/alpha/case0", "/workbench/collections/alpha"]) {
  test(`search and keyboard reveal virtualized cases: ${entry}`, async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const collection = { id: "alpha", space_id: "space", name: "Login regression", case_count: 142,
    lifecycle_status: "maintenance", mind_map_notes: [] };
  const cases = Array.from({ length: 142 }, (_, index) => ({
    id: `case${index}`, case_key: `CASE-${index}`, collection_ids: ["alpha"],
    title: `Scenario ${index}: Invalid format email input handling verification`,
    description: "A long description that should not reserve space in the collapsed overview. ".repeat(5),
    current_revision_id: `revision-${index}`, revision_number: 1, module: "Web Account Password Login",
    priority: "P1", case_type: "功能", tags: [], preconditions: ["Ready"],
    steps: [{ id: "step", action: "Perform", expected: "Pass" }],
    source: "Excel", source_refs: [], created_at: "2026-09-22T00:00:00Z",
  }));
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = [];
    if (path.endsWith("/auth/me")) data = { id: "user", email: "test@example.com", display_name: "Tester",
      spaces: [{ id: "space", name: "Space", description: "", role: "owner" }] };
    else if (path.endsWith("/workspace") || path.includes("/conversations/") || path.includes("/workspaces/")) data = {
      id: "workspace", space_id: "space", collection_id: "alpha", title: "Login regression", status: "active",
      context: { phase: "maintenance" }, messages: [], test_briefs: [], candidates: [], workflow_runs: [], operation_plan: null,
    };
    else if (path === "/api/v1/generation-models") data = { models: [], default_model_id: "auto" };
    else if (path === "/api/v1/spaces/space/collections") data = [collection];
    else if (path === "/api/v1/collections/alpha") data = collection;
    else if (path === "/api/v1/collections/alpha/test-cases") data = cases;
    await route.fulfill({ json: data });
  });

    await page.goto(entry);
    await page.getByRole("button", { name: /^(Case mind map|Mind map|用例脑图)$/ }).click();
    const map = page.locator(".case-mind-map");
    const search = map.getByRole("textbox", { name: /Search test cases|搜索用例资产/ });
    const selected = (index: number) => map.locator(`[data-id="case-case${index}"]`);
    const expectRevealed = async (index: number) => {
      await expect(selected(index).locator(".case-map-node")).toHaveClass(/is-selected/);
      await expect.poll(async () => {
        const canvas = await map.boundingBox();
        const card = await selected(index).boundingBox();
        return !!canvas && !!card && card.x >= canvas.x && card.y >= canvas.y + 50 &&
          card.x + card.width <= canvas.x + canvas.width && card.y + card.height <= canvas.y + canvas.height - 50;
      }).toBe(true);
    };
    await search.fill("CASE-140");
    await expectRevealed(140);
    await expect(search).toBeFocused();
    await search.fill("CASE-14");
    await expectRevealed(14);
    await search.press("ArrowDown");
    await expectRevealed(140);
    await expect(search).toBeFocused();
    await search.press("ArrowDown");
    await expectRevealed(141);
    await search.press("ArrowDown");
    await expectRevealed(141);
    await search.press("ArrowUp");
    await expectRevealed(140);
    await search.fill("no-such-case");
    await expect(map.getByRole("status")).toContainText(/No matching cases|无匹配用例/);
    await search.press("ArrowDown");
    await search.fill("");
    await map.focus();
    await page.keyboard.press("ArrowDown");
    await expectRevealed(141);
    await expect(selected(141)).toBeFocused();
    await page.keyboard.press("ArrowUp");
    await expectRevealed(140);
    const editor = selected(140).locator("textarea");
    await editor.focus();
    await editor.press("ArrowUp");
    await expectRevealed(140);
    await expect(editor).toBeFocused();
    await search.fill("CASE-140");
    await map.getByRole("button", { name: /Collapse all test cases|折叠所有用例/ }).click();
    await search.fill("CASE-141");
    await expectRevealed(141);
    await page.screenshot({ path: testInfo.outputPath("search-focused-node.png") });
    if (entry.startsWith("/cases/")) {
      for (const viewport of [{ width: 1440, height: 700 }, { width: 1024, height: 650 }]) {
        await page.setViewportSize(viewport);
        const controls = map.locator(".case-map-controls");
        await expect.poll(async () => {
          const canvas = await map.boundingBox();
          const bar = await controls.boundingBox();
          return !!canvas && !!bar && canvas.y + canvas.height <= viewport.height + 1 &&
            bar.y >= canvas.y && bar.y + bar.height <= viewport.height - 10;
        }).toBe(true);
        await controls.getByRole("button", { name: /Collapse all test cases|折叠所有用例/ }).click();
      }
      await page.screenshot({ path: testInfo.outputPath("short-viewport-controls.png") });
    }
    expect(errors).toEqual([]);
  });
}
