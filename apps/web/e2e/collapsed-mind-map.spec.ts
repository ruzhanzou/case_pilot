import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 1600, height: 1000 } });

for (const { longTitles, entry } of [
  { longTitles: false, entry: "/cases/alpha/case0" },
  { longTitles: true, entry: "/cases/alpha/case0" },
  { longTitles: true, entry: "/workbench/collections/alpha" },
]) {
test(`collapse reflows titles and restores details: ${longTitles ? "142 long titles" : "ten titles"} ${entry}`, async ({ page }, testInfo) => {
  const caseCount = longTitles ? 142 : 10;
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const collection = { id: "alpha", space_id: "space", name: "Login regression", case_count: caseCount,
    lifecycle_status: "maintenance", mind_map_notes: [] };
  const cases = Array.from({ length: caseCount }, (_, index) => ({
    id: `case${index}`, case_key: `CASE-${index}`, collection_ids: ["alpha"],
    title: longTitles ? `Life Logger:\nPhase_E2E_Usecase_ACD_Tags_Selective_Logging_multi_Drop_${index}_EN_life_logger_ON ${"WWWW_多语言_".repeat(index % 5)}` : `Scenario ${index}: Invalid format email input handling verification`,
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
  const collapse = map.getByRole("button", { name: /Collapse all test cases|折叠所有用例/ });
  const overviewFits = () => map.evaluate((element) => {
    const canvas = element.getBoundingClientRect();
    const cards = [...element.querySelectorAll(".react-flow__node")].map((node) => node.getBoundingClientRect());
    const cases = [...element.querySelectorAll(".case-map-node--case")].map((node) => node.getBoundingClientRect()).sort((a, b) => a.y - b.y);
    return cards.length === 12 && cards.every((card) => card.left >= canvas.left && card.right <= canvas.right &&
      card.top >= canvas.top && card.bottom <= canvas.bottom - 60) &&
      cases.every((card, index) => index === 0 || card.top >= cases[index - 1].bottom + 4);
  });
  await collapse.click();
  await expect(map.locator(".case-map-node--detail")).toHaveCount(0);
  await expect(map.locator(".case-map-controls")).toContainText("100%");
  if (longTitles) {
    const globalView = map.getByRole("button", { name: "Show entire mind map" });
    await expect(globalView).toBeVisible();
    await expect(globalView).toHaveText("Global view");
    // Exercise real wrapping and font differences, rather than short synthetic titles.
    await page.addStyleTag({ content: ".case-map-node--case.is-collapsed textarea { font-family: Arial; font-size: 16px; line-height: 24px; }" });
    await collapse.click();
    await expect(map.locator(".case-map-controls")).toContainText("100%");
    await globalView.click();
    await expect(map.locator(".case-map-node--case")).toHaveCount(142);
    await expect.poll(() => map.evaluate((element) => {
      const canvas = element.getBoundingClientRect();
      const cards = [...element.querySelectorAll(".react-flow__node")].map((node) => node.getBoundingClientRect());
      const cases = [...element.querySelectorAll(".case-map-node--case")].map((node) => node.getBoundingClientRect()).sort((a, b) => a.y - b.y);
      return cards.every((card) => card.left >= canvas.left && card.right <= canvas.right && card.top >= canvas.top && card.bottom <= canvas.bottom - 60) &&
        cases.every((card, index) => index === 0 || card.top > cases[index - 1].bottom);
    })).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("long-titles-global-view.png") });
    await map.getByRole("button", { name: "Reset to 100 percent" }).click();
    await expect(map.locator(".case-map-controls")).toContainText("100%");
    await page.screenshot({ path: testInfo.outputPath("long-titles-100-percent.png") });
    expect(errors).toEqual([]);
    return;
  }
  await expect.poll(overviewFits).toBe(true);
  // Dragging a title and changing zoom must not leave stale positions on the next collapse.
  const first = map.locator('.react-flow__node[data-id="case-case0"]');
  const box = (await first.boundingBox())!;
  await page.mouse.move(box.x + 3, box.y + 10);
  await page.mouse.down();
  await page.mouse.move(box.x + 100, box.y + 200, { steps: 10 });
  await page.mouse.up();
  await map.getByRole("button", { name: /Zoom out|缩小脑图/ }).click();
  await collapse.click();
  await expect(map.locator(".case-map-controls")).toContainText("100%");
  await expect.poll(overviewFits).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("collapsed-at-100.png") });
  await first.getByRole("button", { name: /Expand the structure|展开.*结构节点/ }).click();
  await expect(map.locator(".case-map-node--detail")).toHaveCount(3);
  await map.getByRole("button", { name: /Expand all case details|展开全部用例详情/ }).click();
  await expect(map.locator(".case-map-node--detail")).toHaveCount(30);
  expect(errors).toEqual([]);
});
}
