import { expect, test } from "@playwright/test";

test("collection and case navigation preserves the authenticated workspace", async ({ page }) => {
  const requests: string[] = [];
  const collections = ["alpha", "beta"].map((id) => ({
    id, space_id: "space", name: id, description: "", case_count: 2,
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
      data = [1, 2].map((n) => ({
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
  await page.getByRole("button", { name: /Case beta 2/ }).click();
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
});
