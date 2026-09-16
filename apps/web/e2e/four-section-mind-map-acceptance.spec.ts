import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const collectionName =
  process.env.CASEPILOT_ACCEPTANCE_COLLECTION ??
  "四段式E2E验收-20260915-1510";
const artifactDir = path.resolve(
  process.env.CASEPILOT_ACCEPTANCE_ARTIFACT_DIR ??
    "../../docs/evidence/four-section-e2e-2026-09-15",
);

test.use({ viewport: { width: 1600, height: 1000 } });

test("四段式脑图支持结构展示、原位编辑和快捷新增节点", async ({
  page,
}) => {
  fs.mkdirSync(artifactDir, { recursive: true });

  await page.goto("/");
  await page.getByLabel("邮箱").fill("demo@casepilot.local");
  await page.getByLabel("密码").fill("CasePilot123!");
  await page.getByRole("button", { name: "登录并进入工作台" }).click();
  await expect(
    page.getByRole("heading", { name: "今天想测试什么？" }),
  ).toBeVisible();

  await page.getByLabel("用例管理").click();
  await page.getByLabel("搜索用例集合").fill(collectionName);
  await page
    .getByRole("button", { name: new RegExp(`${collectionName} 2 条用例`) })
    .click();
  await page.getByRole("button", { name: "用例脑图", exact: true }).click();

  const map = page.getByLabel(`${collectionName} 用例脑图`);
  await expect(map.getByText("test_setup").first()).toBeVisible();
  await expect(map.getByText("test_procedure").first()).toBeVisible();
  await expect(map.getByText("test_validation").first()).toBeVisible();
  await expect(map.getByText("已绑定自动化")).toBeVisible();

  await page.getByRole("button", { name: "进入脑图全屏" }).click();
  await page.getByRole("button", { name: "适应画布" }).click();
  await expect(page.getByText("title · CP-C3AFF443 · V3")).toBeVisible();
  await page.screenshot({
    path: path.join(artifactDir, "01-four-section-mind-map.png"),
  });

  const inlineEditor = page.getByRole("textbox", {
    name: "直接编辑test_validation",
  });
  await expect(inlineEditor).toHaveValue(
    "1. 登录成功且只创建一个有效会话（E2E验收已修改）",
  );
  await page.screenshot({
    path: path.join(artifactDir, "02-edit-validation-node.png"),
  });

  await inlineEditor.press("Escape");
  await page.getByRole("button", { name: /在身份认证下新增用例/ }).click();
  await page.getByRole("button", { name: "退出脑图全屏" }).click();
  await expect(
    page.getByRole("heading", { name: "创建结构化测试用例" }),
  ).toBeVisible();
  await expect(page.getByLabel("所属模块")).toHaveValue("身份认证");
  await page.screenshot({
    path: path.join(artifactDir, "03-create-case-from-mind-map.png"),
  });
});
