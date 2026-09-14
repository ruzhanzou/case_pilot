import { expect, test } from "@playwright/test";
import path from "node:path";

const ownerEmail =
  process.env.CASE_SEARCH_OWNER_EMAIL ??
  "search-owner-1789145010@casepilot.local";
const password = process.env.CASE_SEARCH_PASSWORD ?? "CasePilot123!";
const projectId = process.env.CASE_SEARCH_PROJECT_ID ?? "CP-00036";
const targetKey = process.env.CASE_SEARCH_TARGET_KEY ?? "FR-SEARCH-145010";
const artifactDir = path.resolve(
  process.env.CASE_SEARCH_ARTIFACT_DIR ??
    "../../artifacts/case-search-acceptance",
);

test.use({ viewport: { width: 1600, height: 1000 } });

test("用例资产可按 test_target、创建人及组合条件模糊搜索", async ({
  page,
}) => {
  const browserErrors: string[] = [];
  const failedApiResponses: string[] = [];
  page.on("console", (message) => {
    if (
      message.type() === "error" &&
      !message.text().startsWith("Failed to load resource")
    ) {
      browserErrors.push(message.text());
    }
  });
  page.on("response", (response) => {
    if (
      response.status() >= 400 &&
      response.url().startsWith("http://localhost:8000/")
    ) {
      failedApiResponses.push(`${response.status()} ${response.url()}`);
    }
  });

  await page.goto("/");
  await page.getByLabel("邮箱").fill(ownerEmail);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "登录并进入工作台" }).click();
  await expect(page.getByRole("heading", { name: "今天想测试什么？" })).toBeVisible();
  browserErrors.length = 0;
  failedApiResponses.length = 0;

  await page.goto(`/case-projects/${projectId}`);
  await expect(
    page.getByRole("heading", { name: "统一登录搜索验收" }),
  ).toBeVisible();

  const search = page.getByLabel("搜索用例资产");
  const rows = page.locator(".case-table tbody tr");
  await expect(rows).toHaveCount(2);
  await expect(page.locator(".case-table")).toContainText(targetKey);
  await expect(page.locator(".case-table")).toContainText("李四·搜索验收");
  await expect(page.locator(".case-table")).toContainText("张三·搜索验收");
  await page.screenshot({
    path: path.join(artifactDir, "01-case-assets-baseline.png"),
    fullPage: true,
  });

  const collectionSearch = page.getByLabel("搜索用例集合");
  const collectionItems = page.locator(".collection-sidebar__list .collection-item");
  await collectionSearch.fill("SEARCH-145");
  await expect(collectionItems).toHaveCount(1);
  await expect(collectionItems.first()).toContainText("统一登录搜索验收");
  await collectionSearch.fill("FR-SEARCH-145010 李四");
  await expect(collectionItems).toHaveCount(1);
  await page.screenshot({
    path: path.join(artifactDir, "06-collection-search.png"),
    fullPage: true,
  });
  await collectionSearch.fill("不存在的集合");
  await expect(collectionItems).toHaveCount(0);
  await expect(page.getByText("没有匹配的用例集合")).toBeVisible();
  await page.screenshot({
    path: path.join(artifactDir, "07-collection-search-empty.png"),
    fullPage: true,
  });
  await collectionSearch.fill("");

  await search.fill("SEARCH-145");
  await expect(rows).toHaveCount(2);
  await expect(page.locator(".case-library__view-controls > span")).toHaveText(
    "2 条用例",
  );
  await page.screenshot({
    path: path.join(artifactDir, "02-test-target-fuzzy-search.png"),
    fullPage: true,
  });

  await search.fill("张三");
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText("统一登录异常恢复");
  await expect(rows.first()).toContainText("张三·搜索验收");
  await page.screenshot({
    path: path.join(artifactDir, "03-creator-fuzzy-search.png"),
    fullPage: true,
  });

  await search.fill(`${targetKey} 张三`);
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText("统一登录异常恢复");
  await page.screenshot({
    path: path.join(artifactDir, "04-combined-search.png"),
    fullPage: true,
  });

  await search.fill("不存在的目标 李四");
  await expect(rows).toHaveCount(0);
  await expect(page.getByText("当前集合还没有匹配的用例")).toBeVisible();
  await page.screenshot({
    path: path.join(artifactDir, "05-empty-result.png"),
    fullPage: true,
  });

  expect(browserErrors).toEqual([]);
  expect(failedApiResponses).toEqual([]);
});
