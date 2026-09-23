import { expect, test } from "@playwright/test";
import type { MindMapNote } from "../lib/casepilot-api";

test.use({ viewport: { width: 1600, height: 1000 } });

test("module hierarchy, text persistence, and module-aware case creation", async ({ page }, testInfo) => {
  const notes: MindMapNote[] = [];
  const collection = { id: "alpha", space_id: "space", name: "Module tree", description: "", case_count: 3,
    lifecycle_status: "maintenance", created_at: "2026-09-22T00:00:00Z" };
  const modules = ["Selective Logging/ODP/ODP Condition Matching/Location", "Selective Logging/ODP/Activity", "Other/Location"];
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
  await page.goto("/cases/alpha/case0");
  await page.getByRole("button", { name: /Case mind map|用例脑图/ }).click();
  const map = page.locator(".case-mind-map");
  const node = (path: string) => map.locator(`.react-flow__node[data-id="module-${encodeURIComponent(path)}"]`);
  const caseNode = map.locator('.react-flow__node[data-id="case-case0"]');
  await expect(map.locator(".case-map-node--detail")).toHaveCount(9);
  await map.getByRole("button", { name: /Collapse all test cases|折叠所有用例/ }).click();
  await expect(map.locator(".case-map-node--detail")).toHaveCount(0);
  await caseNode.getByRole("button", { name: /Expand the structure|展开.*结构节点/ }).dispatchEvent("click");
  await expect(map.locator(".case-map-node--detail")).toHaveCount(3);
  for (const kind of ["setup", "procedure", "validation"]) {
    await expect(map.locator(`.react-flow__node[data-id="case-case0-${kind}"]`)).toHaveCount(1);
  }
  await map.getByRole("button", { name: /Expand all case details|展开全部用例详情/ }).click();
  await expect(map.locator(".case-map-node--detail")).toHaveCount(9);
  await caseNode.getByRole("button", { name: /Collapse the structure|收起.*结构节点/ }).dispatchEvent("click");
  await expect(map.locator(".case-map-node--detail")).toHaveCount(6);
  await map.getByRole("button", { name: /Expand all case details|展开全部用例详情/ }).click();
  await expect(map.locator(".case-map-node--detail")).toHaveCount(9);
  await node("Selective Logging").getByRole("button", { name: /Hide leaf cases|隐藏.*叶子用例/ }).dispatchEvent("click");
  await expect(map.locator(".case-map-node--detail")).toHaveCount(3);
  await caseNode.getByRole("button", { name: /Expand the structure|展开.*结构节点/ }).dispatchEvent("click");
  await expect(map.locator(".case-map-node--detail")).toHaveCount(6);
  await map.getByRole("button", { name: /Expand all case details|展开全部用例详情/ }).click();
  await expect(map.locator(".case-map-node--detail")).toHaveCount(9);
  for (const path of ["Selective Logging", "Selective Logging/ODP", "Selective Logging/ODP/ODP Condition Matching", modules[0]]) {
    await expect(node(path)).toHaveCount(1);
  }
  await expect(map.locator(".case-map-node--module")).toHaveCount(7);
  const parent = await node("Selective Logging/ODP/ODP Condition Matching").boundingBox();
  const leaf = await node(modules[0]).boundingBox();
  expect(leaf!.x).toBeGreaterThan(parent!.x);
  // The deep branch can be outside the initial viewport; dispatch targets its actual control.
  await node(modules[0]).locator(".case-map-node__quick-add").dispatchEvent("click");
  await node(modules[0]).getByRole("button", { name: /New text node|新建文本节点/ }).dispatchEvent("click");
  await node(modules[0]).getByRole("textbox", { name: /Text node content|文本节点内容/ }).fill("Location note");
  await node(modules[0]).getByRole("button", { name: /Save text node|保存文本节点/ }).dispatchEvent("click");
  await expect(map.locator(".case-map-node--text")).toHaveCount(1);
  expect(notes[0].parent_id).toBe(`module-${encodeURIComponent(modules[0])}`);
  expect(notes[0].module).toBe(modules[0]);
  const editor = map.locator(".case-map-node--text textarea");
  await editor.fill("Updated location note");
  await editor.press("Enter");
  await expect.poll(() => notes[0].text).toBe("Updated location note");
  await page.reload();
  await page.getByRole("button", { name: /Case mind map|用例脑图/ }).click();
  await expect(map.locator(".case-map-node--text textarea")).toHaveValue("Updated location note");
  await map.locator(".case-map-node--text").getByRole("button", { name: /Delete text node|删除文本节点/ }).dispatchEvent("click");
  await expect(map.locator(".case-map-node--text")).toHaveCount(0);
  expect(notes).toHaveLength(0);
  await node(modules[0]).locator(".case-map-node__quick-add").dispatchEvent("click");
  await node(modules[0]).getByRole("button", { name: /New test case|新建用例/, exact: true }).dispatchEvent("click");
  await expect(map.getByRole("textbox", { name: /Case module|所属模块/, exact: true })).toHaveValue(modules[0]);
  await map.getByRole("textbox", { name: /New case title|新用例标题/ }).fill("New location scenario");
  await map.getByLabel("test_setup", { exact: true }).fill("Ready");
  await map.getByLabel("test_procedure", { exact: true }).fill("Perform");
  await map.getByLabel("test_validation", { exact: true }).fill("Pass");
  await map.getByRole("button", { name: /Save case|保存用例/, exact: true }).click();
  await expect(map.locator('.react-flow__node[data-id="case-new-case"]')).toHaveCount(1);
  expect(cases.at(-1)?.module).toBe(modules[0]);
  await map.getByRole("button", { name: /Fit to canvas|适应画布/ }).click();
  await page.screenshot({ path: testInfo.outputPath("module-tree.png") });
});
