import { expect, test } from "@playwright/test";
import * as XLSX from "xlsx";
import type { TestCaseDto, TestCaseInput } from "../lib/casepilot-api";

test.use({ viewport: { width: 1600, height: 1000 } });

test("optional Excel descriptions survive editing and appear on case nodes", async ({ page }, testInfo) => {
  const cases: TestCaseDto[] = [];
  const description = "Verify location-based selective logging.\nIncludes the stationary scenario.";
  const collection = { id: "alpha", space_id: "space", name: "Descriptions", description: "",
    case_count: 0, lifecycle_status: "maintenance", created_at: "2026-09-22T00:00:00Z" };
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = [];
    if (path.endsWith("/auth/me")) data = { id: "user", email: "test@example.com", display_name: "Tester",
      spaces: [{ id: "space", name: "Space", description: "", role: "owner" }] };
    else if (path === "/api/v1/spaces/space/collections") data = [{ ...collection, case_count: cases.length }];
    else if (path === "/api/v1/collections/alpha") data = collection;
    else if (path.endsWith("/test-cases/batch")) {
      const inputs = route.request().postDataJSON().cases as TestCaseInput[];
      cases.push(...inputs.map((input, index) => ({ ...input,
        id: `case${index}`, case_key: `CASE-${index}`, collection_ids: ["alpha"], current_revision_id: `rev-${index}`,
        revision_number: 1, steps: input.steps.map((step, i) => ({ ...step, id: `step-${i}` })),
        source_refs: [], created_at: collection.created_at,
      })));
      data = cases;
    } else if (path === "/api/v1/collections/alpha/test-cases") data = cases;
    else if (path === "/api/v1/test-cases/case0" && route.request().method() === "PATCH") {
      cases[0] = { ...cases[0], ...route.request().postDataJSON(), revision_number: cases[0].revision_number + 1 };
      data = cases[0];
    }
    await route.fulfill({ json: data });
  });
  await page.goto("/cases/alpha");
  await page.getByRole("button", { name: /Import cases from Excel|从 Excel 导入用例/ }).click();
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet([
    ["Test_Case_Name", "Case Description", "Test Procedure", "Test Validation"],
    ["Location logging", description, "Enable logging", "Record appears"],
    ["Without description", "", "Disable logging", "Record absent"],
  ]), "Cases");
  await page.locator('input[type="file"]').setInputFiles({ name: "descriptions.xlsx",
    mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: XLSX.write(workbook, { type: "buffer", bookType: "xlsx" }),
  });
  await expect(page.locator(".case-import__table")).toContainText("Verify location-based");
  await page.getByRole("button", { name: /Import 2 test cases|导入 2 条用例/ }).click();
  await expect(page.locator(".case-import")).toHaveCount(0);
  expect(cases[0].description).toBe(description);
  expect(cases[1].description).toBe("");
  await page.getByRole("button", { name: /Edit current case|编辑当前用例/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel(/Case description|用例描述/)).toHaveValue(description);
  await dialog.getByLabel(/Case description|用例描述/).fill(`${description}\nUpdated scope.`);
  await dialog.getByRole("button", { name: /Save as new revision|保存为新版本/ }).click();
  await expect(dialog).toHaveCount(0);
  await page.getByRole("button", { name: /Case mind map|用例脑图/ }).click();
  const card = page.locator('.react-flow__node[data-id="case-case0"]');
  await expect(card.locator(".case-map-node__description")).toHaveText(`${description}\nUpdated scope.`);
  await expect(page.locator('.react-flow__node[data-id="case-case1"] .case-map-node__description')).toHaveCount(0);
  await card.locator("textarea").fill("Renamed location logging");
  await card.locator("textarea").press("Enter");
  await expect.poll(() => cases[0].title).toBe("Renamed location logging");
  expect(cases[0].description).toBe(`${description}\nUpdated scope.`);
  await page.screenshot({ path: testInfo.outputPath("case-description.png") });
});
