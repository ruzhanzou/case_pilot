import { expect, test, type Page } from "@playwright/test";

const collectionName = "UI回归-登录接口-20260908";
const caseKey = `REC-${Date.now()}`;
const initialTitle = `录屏验收：登录会话创建 ${caseKey}`;
const updatedTitle = `${initialTitle}（已修改）`;

test.use({ viewport: { width: 1440, height: 900 } });

async function showStage(page: Page, label: string) {
  await page.locator("[data-recording-stage]").evaluateAll((items) =>
    items.forEach((item) => item.remove()),
  );
  await page.locator("body").evaluate((body, text) => {
    const banner = document.createElement("div");
    banner.dataset.recordingStage = "true";
    banner.textContent = text;
    Object.assign(banner.style, {
      position: "fixed",
      zIndex: "99999",
      top: "20px",
      left: "50%",
      transform: "translateX(-50%)",
      padding: "10px 18px",
      borderRadius: "999px",
      color: "white",
      background: "rgba(29, 78, 216, .94)",
      boxShadow: "0 10px 30px rgba(29, 78, 216, .28)",
      font: "600 14px system-ui",
    });
    body.appendChild(banner);
  }, label);
  await page.waitForTimeout(900);
}

test("录屏验收：新增、修改并删除临时用例", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("邮箱").fill("demo@casepilot.local");
  await page.getByLabel("密码").fill("CasePilot123!");
  await page.getByRole("button", { name: "登录并进入工作台" }).click();
  await expect(page.getByRole("heading", { name: "今天想测试什么？" })).toBeVisible();

  await page.getByLabel("用例管理").click();
  await page.getByLabel("搜索用例集合").fill(collectionName);
  await page
    .getByRole("button", { name: new RegExp(`${collectionName} \\d+ 条用例`) })
    .click();
  await expect(page.getByRole("heading", { name: collectionName })).toBeVisible();
  const caseCount = page.locator(".case-library__view-controls > span");
  await expect(caseCount).toHaveText(/^\d+ 条用例$/);
  const baselineCount = await caseCount.innerText();

  await showStage(page, "步骤 1 / 3 · 新增临时验收用例");
  await page.getByRole("button", { name: "新建用例" }).first().click();
  await expect(
    page.getByRole("heading", { name: "创建结构化测试用例" }),
  ).toBeVisible();
  await page.getByLabel("用例编号").fill(caseKey);
  await page.getByLabel("用例名称").fill(initialTitle);
  await page.getByLabel("所属模块").fill("登录接口");
  await page.getByLabel("优先级").selectOption("P1");
  await page.getByLabel("用例类型").fill("功能验收");
  await page.getByLabel("标签").fill("录屏验收, CRUD");
  await page.getByLabel("来源").fill("Codex 录屏验收");
  await page
    .getByPlaceholder("执行前必须满足的环境、数据或账号条件")
    .fill("存在有效的测试账号");
  await page.getByLabel("执行操作").fill("输入正确账号密码并提交登录");
  await page
    .getByLabel("预期结果／校验点")
    .fill("登录成功并创建唯一有效会话");
  await page.waitForTimeout(700);
  await page.getByRole("button", { name: "创建用例", exact: true }).click();
  await expect(page.getByRole("heading", { name: initialTitle })).toBeVisible();
  await page.waitForTimeout(1100);

  await showStage(page, "步骤 2 / 3 · 修改名称并保存新版本");
  await page.getByRole("button", { name: "编辑当前用例" }).click();
  await expect(
    page.getByRole("heading", { name: "编辑结构化测试用例" }),
  ).toBeVisible();
  await page.getByLabel("用例名称").fill(updatedTitle);
  await page
    .getByLabel("预期结果／校验点")
    .fill("登录成功、只创建一个会话，并返回有效认证令牌");
  await page.waitForTimeout(700);
  await page.getByRole("button", { name: "保存为新版本" }).click();
  await expect(page.getByRole("heading", { name: updatedTitle })).toBeVisible();
  await page.waitForTimeout(1100);

  await showStage(page, "步骤 3 / 3 · 删除临时验收用例");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "删除当前用例" }).click();
  await expect(page.getByText(updatedTitle, { exact: true })).toHaveCount(0);
  await expect(caseCount).toHaveText(baselineCount);
  await showStage(page, "验收完成 · 新增、修改、删除均通过");
  await page.waitForTimeout(1200);
});
