import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 1600, height: 1000 } });
for (const count of [160, 1000]) {
  for (const entry of ["/cases/alpha/case0", "/workbench/collections/alpha"]) {
    test(`bounded editing and layout tracking: ${count} cases ${entry}`, async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const collection = { id: "alpha", space_id: "space", name: "Login regression", case_count: count,
    lifecycle_status: "maintenance", mind_map_notes: [] };
  const cases = Array.from({ length: count }, (_, index) => ({
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
      await search.fill("CASE-10");
      await expect(map.locator('[data-id="case-case10"] .is-selected')).toBeVisible();
      await search.fill("");
      await map.focus();
      const navigation = await map.evaluate(async (element) => {
        const samples: number[] = [];
        let running = true;
        let previous = performance.now();
        const sample = (now: number) => {
          samples.push(now - previous);
          previous = now;
          if (running) requestAnimationFrame(sample);
        };
        requestAnimationFrame(sample);
        const start = performance.now();
        for (let index = 0; index < 30; index++) {
          element.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
          await new Promise((resolve) => setTimeout(resolve, 33));
        }
        await new Promise((resolve) => setTimeout(resolve, 300));
        running = false;
        samples.sort((a, b) => a - b);
        return { elapsed: performance.now() - start, p95FrameMs: samples[Math.floor(samples.length * 0.95)], maxFrameMs: samples.at(-1) };
      });
      await expect(map.locator('[data-id="case-case40"] .is-selected')).toBeVisible();
      const editor = map.locator('[data-id="case-case40"] textarea');
      const start = Date.now();
      await editor.fill("Unsaved title survives viewport culling");
      await expect(editor).toBeFocused();
      const editMs = Date.now() - start;
      await expect.poll(() => map.locator(".react-flow__node").count()).toBeLessThan(100);
      await expect.poll(() => map.locator(".react-flow__edge").count()).toBeLessThan(100);
      const box = (await map.boundingBox())!;
      const viewport = map.locator(".react-flow__viewport");
      const beforePan = await viewport.getAttribute("style");
      await page.mouse.move(box.x + 10, box.y + box.height / 2);
      await page.mouse.wheel(0, 5000);
      await expect.poll(() => viewport.getAttribute("style")).not.toBe(beforePan);
      await expect(editor).toHaveValue("Unsaved title survives viewport culling");
      await expect(editor).toBeFocused();
      expect(await map.locator(".react-flow__node").count()).toBeLessThan(100);
      // Dispatch to the offscreen retained editor without scrolling it back into view.
      await editor.dispatchEvent("keydown", { key: "Escape", bubbles: true });
      await expect.poll(() => map.locator('[data-id="case-case40"]').count()).toBe(0);

      await search.fill(`CASE-${count - 1}`);
      const last = map.locator(`[data-id="case-case${count - 1}"]`);
      await expect(last.locator(".is-selected")).toBeVisible();
      for (let index = 0; index < 4; index++) await map.getByRole("button", { name: /Zoom in|放大脑图/ }).click();
      await expect(map.locator(".case-map-controls")).toContainText("162%");
      await search.fill("");
      await map.focus();
      await page.keyboard.press("ArrowUp");
      await expect(map.locator(".case-map-controls")).toContainText("162%");
      await map.getByRole("button", { name: /Collapse all test cases|折叠所有用例/ }).click();
      await expect(map.locator(".case-map-node--detail")).toHaveCount(0);
      await search.fill(`CASE-${count - 1}`);
      await expect(last.locator(".is-selected")).toBeVisible();
      await map.getByRole("button", { name: /Expand all case details|展开全部用例详情/ }).click();
      await expect.poll(async () => {
        const canvas = await map.boundingBox();
        const card = await last.boundingBox();
        return !!canvas && !!card && card.x >= canvas.x && card.y >= canvas.y + 45 &&
          card.x + card.width <= canvas.x + canvas.width && card.y + card.height <= canvas.y + canvas.height - 45;
      }).toBe(true);
      const metrics = { count, entry, navigation, editMs, mountedNodes: await map.locator(".react-flow__node").count() };
      console.log("Mind map interaction metrics", JSON.stringify(metrics));
      await testInfo.attach("interaction-metrics", { body: JSON.stringify(metrics), contentType: "application/json" });
      expect(errors).toEqual([]);
    });
  }
}
