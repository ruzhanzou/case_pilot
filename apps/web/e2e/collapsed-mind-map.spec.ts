import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 1600, height: 1000 } });

test("collapse reflows all ten titles at 100% and restores details", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const collection = { id: "alpha", space_id: "space", name: "Login regression", case_count: 10,
    lifecycle_status: "maintenance", mind_map_notes: [] };
  const cases = Array.from({ length: 10 }, (_, index) => ({
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
    else if (path === "/api/v1/spaces/space/collections") data = [collection];
    else if (path === "/api/v1/collections/alpha") data = collection;
    else if (path === "/api/v1/collections/alpha/test-cases") data = cases;
    await route.fulfill({ json: data });
  });
  await page.goto("/cases/alpha/case0");
  await page.getByRole("button", { name: /Case mind map|用例脑图/ }).click();
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
