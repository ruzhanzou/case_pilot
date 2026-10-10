import { expect, test } from "@playwright/test";

const api = process.env.CASEPILOT_E2E_API_URL ?? "http://localhost:8000";

for (const entry of ["new conversation", "existing workspace"] as const) {
  test(`${entry} uploads multiple attachments without crypto.randomUUID`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.addInitScript(() => {
      localStorage.setItem("casepilot.locale.v1", "zh-CN");
      Object.defineProperty(crypto, "randomUUID", { configurable: true, value: undefined });
    });
    const registered = await page.request.post(`${api}/api/v1/auth/register`, { data: {
      email: `attachment-compat-${Date.now()}@casepilot.test`,
      password: "CasePilot123!", display_name: "附件兼容性验收",
    } });
    expect(registered.ok()).toBeTruthy();
    let path = "/workbench";
    if (entry === "existing workspace") {
      const account = await registered.json();
      const collection = await page.request.post(`${api}/api/v1/spaces/${account.spaces[0].id}/collections`, {
        data: { name: "附件兼容性验收" },
      });
      expect(collection.ok()).toBeTruthy();
      path = `/workbench/collections/${(await collection.json()).id}`;
    }
    await page.goto(path);
    expect(await page.evaluate(() => typeof crypto.randomUUID)).toBe("undefined");
    const composer = page.locator(entry === "new conversation" ? ".new-conversation__composer" : ".principle-composer");
    await expect(composer).toBeVisible();
    await expect(composer.locator("textarea")).toBeEnabled();
    const names = ["login.txt", "logout.txt"];
    const uploaded = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith("/attachments"));
    await composer.locator('input[type="file"]').setInputFiles(names.map(name => ({
      name, mimeType: "text/plain", buffer: Buffer.from(`${name}: 用户可以登录和退出系统。`),
    })));
    const response = await uploaded;
    expect(response.status()).toBe(202);
    for (const name of names) {
      await expect(composer.getByLabel("待发送附件")).toContainText(name, { timeout: 90_000 });
    }
    await expect(composer.locator("textarea")).toBeEnabled();
    const saved = await (await page.request.get(response.url().replace(/\/attachments$/, ""))).json();
    expect(saved.context.pending_attachments.map((file: { name: string }) => file.name).sort()).toEqual(names.sort());
    expect(saved.messages).toHaveLength(0);
    expect(errors).toEqual([]);
  });
}
