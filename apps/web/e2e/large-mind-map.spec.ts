import { expect, test } from "@playwright/test";
import type { MindMapNote } from "../lib/casepilot-api";

test.use({ viewport: { width: 1600, height: 1000 }, actionTimeout: 20_000 });

for (const entry of ["/cases/alpha/case0", "/workbench/collections/alpha"]) {
test(`large module mind map stays responsive and preserves editing: ${entry}`, async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const notes: MindMapNote[] = [];
  const collection = { id: "alpha", space_id: "space", name: "Module tree", description: "", case_count: 160,
    lifecycle_status: "maintenance", created_at: "2026-09-22T00:00:00Z" };
  const modules = Array.from({ length: 160 }, (_, index) => `A/B/C${Math.floor(index / 10)}/D${index % 10}`);
  const cases = modules.map((module, index) => ({
    id: `case${index}`, case_key: `CASE-${index}`, collection_ids: ["alpha"], title: `Scenario ${index}`,
    current_revision_id: `revision-${index}`, revision_number: 1, module, priority: "P1", case_type: "功能", tags: [],
    preconditions: ["Ready"], steps: [{ id: "step", action: "Perform", expected: "Pass" }],
    source: "Excel", source_refs: [], created_at: "2026-09-22T00:00:00Z",
  }));
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = [];
    if (path.endsWith("/auth/me")) data = { id: "user", email: "test@example.com", display_name: "Tester",
      spaces: [{ id: "space", name: "Space", description: "", role: "owner" }] };
    else if (path.endsWith("/workspace") || path.includes("/conversations/") || path.includes("/workspaces/")) data = {
      id: "workspace", space_id: "space", collection_id: "alpha", title: "Module tree",
      status: "active", context: { phase: "maintenance" }, messages: [], test_briefs: [], candidates: [],
      workflow_runs: [], operation_plan: null,
    };
    else if (path === "/api/v1/generation-models") data = { models: [], default_model_id: "auto" };
    else if (path === "/api/v1/spaces/space/collections") data = [{ ...collection, mind_map_notes: notes }];
    else if (path === "/api/v1/collections/alpha") {
      if (route.request().method() === "PATCH") notes.splice(0, notes.length, ...route.request().postDataJSON().mind_map_notes);
      data = { ...collection, mind_map_notes: notes };
    } else if (path === "/api/v1/collections/alpha/test-cases") {
      if (route.request().method() === "POST") {
        const created = { ...cases[0], ...route.request().postDataJSON(), id: "new-case", case_key: "NEW-CASE" };
        cases.push(created);
        await route.fulfill({ status: 201, json: created });
        return;
      }
      data = cases;
    }
    await route.fulfill({ json: data });
  });
  await page.goto(entry);
  await page.getByRole("button", { name: /^(Case mind map|Mind map|用例脑图)$/i }).click();
  const map = page.locator(".case-mind-map");
  await expect(map.locator(".case-map-controls")).toBeVisible();
  // Warm up node measurements before sampling animated zoom frame intervals.
  await map.getByRole("button", { name: /Fit to canvas|适应画布/ }).click();
  await page.bringToFront();
  const metrics = await map.evaluate(async (element) => {
    const samples: number[] = [];
    let previous: number | undefined;
    let running = true;
    const sample = (now: number) => {
      if (previous !== undefined) samples.push(now - previous);
      previous = now;
      if (running) requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
    for (let i = 0; i < 8; i++) {
      const label = i % 2 ? /Zoom out|缩小脑图/ : /Zoom in|放大脑图/;
      const button = [...element.querySelectorAll<HTMLButtonElement>("button")]
        .find((item) => label.test(item.getAttribute("aria-label") ?? ""))!;
      button.click();
      await new Promise((resolve) => setTimeout(resolve, 220));
    }
    running = false;
    samples.sort((a, b) => a - b);
    return { mountedNodes: element.querySelectorAll(".react-flow__node").length,
      frames: samples.length, p95FrameMs: samples[Math.floor(samples.length * 0.95)],
      maxFrameMs: samples.at(-1) };
  });
  console.log("Mind map performance", JSON.stringify(metrics));
  await testInfo.attach("zoom-metrics", { body: JSON.stringify(metrics), contentType: "application/json" });
  expect(metrics.mountedNodes).toBeLessThan(120);
  expect(metrics.frames).toBeGreaterThan(0);
  await page.screenshot({ path: testInfo.outputPath("large-map.png") });

  const root = map.locator('.react-flow__node[data-id="collection-root"]');
  await root.locator(".case-map-node__quick-add").dispatchEvent("click");
  await root.getByRole("button", { name: /New text node|新建文本节点/ }).dispatchEvent("click");
  const editor = root.getByRole("textbox", { name: /Text node content|文本节点内容/ });
  await editor.fill("Unsaved note survives panning");
  const viewport = map.locator(".react-flow__viewport");
  const before = await viewport.getAttribute("style");
  await page.mouse.move(1100, 600);
  await page.mouse.wheel(0, 6000);
  await expect.poll(() => viewport.getAttribute("style")).not.toBe(before);
  await expect(editor).toHaveValue("Unsaved note survives panning");
  await root.getByRole("button", { name: /Save text node|保存文本节点/ }).dispatchEvent("click");
  await expect.poll(() => notes.length).toBe(1);
  expect(notes[0].text).toBe("Unsaved note survives panning");
  await map.getByRole("button", { name: /Fit to canvas|适应画布/ }).click();
  await expect.poll(() => map.locator(".react-flow__node").count()).toBeLessThan(120);

  // Focused inline edits must also survive viewport culling, then cancel cleanly.
  await root.locator(".case-map-node__quick-add").dispatchEvent("click");
  const titleEditor = map.locator('.react-flow__node[data-id="case-case0"] textarea');
  await titleEditor.fill("Unsaved inline title");
  await root.locator(".case-map-node__quick-add").dispatchEvent("click");
  await page.mouse.move(1100, 600);
  await page.mouse.wheel(0, 6000);
  await expect(titleEditor).toHaveValue("Unsaved inline title");
  await titleEditor.press("Escape");
  await map.getByRole("button", { name: /Fit to canvas|适应画布/ }).click();
  await expect.poll(() => map.locator(".react-flow__node").count()).toBeLessThan(120);

  // Hold a menu open so all cards can be inspected, including offscreen cases.
  await root.locator(".case-map-node__quick-add").dispatchEvent("click");
  await map.getByRole("button", { name: /Collapse all test cases|折叠所有用例/ }).click();
  await expect(map.locator(".case-map-node--case")).toHaveCount(160);
  await expect(map.locator(".case-map-node--detail")).toHaveCount(0);
  await map.getByRole("button", { name: /Expand all case details|展开全部用例详情/ }).click();
  await expect(map.locator(".case-map-node--detail")).toHaveCount(480);
  await root.locator(".case-map-node__quick-add").dispatchEvent("click");
  await expect.poll(() => map.locator(".react-flow__node").count()).toBeLessThan(120);
  expect(errors).toEqual([]);
});
}
