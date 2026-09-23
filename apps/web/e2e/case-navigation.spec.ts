import { expect, test } from "@playwright/test";

test("collection and case navigation preserves the authenticated workspace", async ({ page }, testInfo) => {
  const requests: string[] = [];
  const collections = ["alpha", "beta"].map((id) => ({
    id, space_id: "space", name: id, description: "", case_count: 25,
    lifecycle_status: "maintenance", created_at: "2026-09-18T00:00:00Z",
  }));
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    requests.push(path);
    let data: unknown = [];
    if (path === "/api/v1/auth/me") {
      data = { id: "user", email: "test@example.com", display_name: "Tester",
        spaces: [{ id: "space", name: "Space", description: "", role: "owner" }] };
    } else if (path === "/api/v1/spaces/space/collections") {
      data = collections;
    } else if (/\/collections\/[^/]+\/test-cases$/.test(path)) {
      const collection = path.split("/")[4];
      data = Array.from({ length: 25 }, (_, i) => i + 1).map((n) => ({
        id: `${collection}-${n}`, case_key: `${collection}-${n}`,
        collection_ids: [collection], title: `Case ${collection} ${n}`,
        current_revision_id: `revision-${n}`, revision_number: 1,
        module: "Navigation", priority: "P1", case_type: "功能", tags: [],
        preconditions: [], steps: [], source: "test", source_refs: [],
        created_at: "2026-09-18T00:00:00Z",
      }));
    }
    await route.fulfill({ json: data });
  });

  await page.goto("/cases/alpha/alpha-1");
  await expect(page.locator(".case-table tr.is-selected")).toContainText("Case alpha 1");
  // DOM identity catches remounts even when mocked authentication returns instantly.
  const sidebar = await page.locator(".collection-sidebar__list").elementHandle();
  requests.length = 0;
  await page.locator(".collection-item").filter({ hasText: "beta" }).click();
  await expect(page).toHaveURL(/\/cases\/beta\/beta-1$/);
  await expect(page.locator(".case-table tr.is-selected")).toContainText("Case beta 1");
  await page.waitForLoadState("networkidle");
  expect(requests).toEqual(["/api/v1/collections/beta/test-cases"]);
  expect(await sidebar!.evaluate((node) => node.isConnected)).toBe(true);

  requests.length = 0;
  await page.getByRole("button", { name: /Case beta 2$/ }).click();
  await expect(page).toHaveURL(/\/cases\/beta\/beta-2$/);
  await page.waitForLoadState("networkidle");
  expect(requests).toEqual([]);
  expect(await sidebar!.evaluate((node) => node.isConnected)).toBe(true);

  await page.goBack();
  await expect(page.locator(".case-table tr.is-selected")).toContainText("Case beta 1");
  await page.goBack();
  await expect(page.locator(".case-table tr.is-selected")).toContainText("Case alpha 1");
  await page.goForward();
  await expect(page.locator(".case-table tr.is-selected")).toContainText("Case beta 1");
  expect(requests).not.toContain("/api/v1/auth/me");
  expect(await sidebar!.evaluate((node) => node.isConnected)).toBe(true);

  await page.reload();
  await expect(page.locator(".case-table tr.is-selected")).toContainText("Case beta 1");

  // Direct links start with focus outside the table.
  await page.keyboard.press("ArrowDown");
  await expect(page).toHaveURL(/\/cases\/beta\/beta-2$/);
  await page.locator(".case-detail h2").click();
  await page.keyboard.press("ArrowDown");
  await expect(page).toHaveURL(/\/cases\/beta\/beta-3$/);
  // A modal must keep its own keyboard behavior.
  await page.evaluate(() => {
    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.id = "keyboard-test-dialog";
    document.querySelector("body")!.appendChild(dialog);
  });
  await page.keyboard.press("ArrowDown");
  await expect(page).toHaveURL(/\/cases\/beta\/beta-3$/);
  await page.locator("#keyboard-test-dialog").evaluate((element) => element.remove());

  const list = page.locator(".case-table-wrap");
  await page.getByRole("button", { name: "beta-1 Case beta 1", exact: true }).click();
  await page.keyboard.press("ArrowUp");
  await expect(page).toHaveURL(/\/cases\/beta\/beta-1$/);
  for (let i = 0; i < 20; i++) {
    await page.keyboard.press("ArrowDown");
    await expect(page.locator(".case-table tr.is-selected")).toContainText(`Case beta ${i + 2}`);
  }
  await expect(page).toHaveURL(/\/cases\/beta\/beta-21$/);
  await expect(page.locator(".case-table tr.is-selected button")).toBeFocused();
  await page.keyboard.press("ArrowUp");
  await expect(page).toHaveURL(/\/cases\/beta\/beta-20$/);
  await expect(page.locator(".case-table tr.is-selected button")).toBeInViewport();
  expect(await list.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);
  await expect(page.getByRole("columnheader", { name: "Test target", exact: true })).toHaveCount(0);
  const before = await page.locator(".case-detail").boundingBox();
  await page.getByRole("button", { name: /Expand case details|扩大用例详情/ }).click();
  const after = await page.locator(".case-detail").boundingBox();
  expect(after!.width).toBeGreaterThan(before!.width);
  const header = await page.locator(".case-library__header").boundingBox();
  const toolbar = await page.locator(".case-library__toolbar").boundingBox();
  expect(header!.y + header!.height).toBeLessThanOrEqual(toolbar!.y + 1);
  const search = page.locator(".case-search input");
  await search.fill("Case beta 2");
  await search.press("ArrowDown");
  await expect(page).toHaveURL(/\/cases\/beta\/beta-20$/);
  await search.fill("");
  await page.screenshot({ path: testInfo.outputPath("case-list-layout.png") });
});
