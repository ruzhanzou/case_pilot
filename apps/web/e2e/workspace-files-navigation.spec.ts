import { expect, test, type Page } from '@playwright/test';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const api = `${process.env.CASEPILOT_E2E_API_URL ?? 'http://localhost:8015'}/api/v1`;
const output = path.resolve('../../output/workspace-files-repeat');
const filesTab = (page: Page) => page.getByRole('button', { name: '上传文件', exact: true });
const fileList = (page: Page) => page.getByRole('navigation', { name: '上传文件', exact: true });
const preview = (page: Page) => page.getByRole('region', { name: '文件预览' });
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
test.skip(process.env.CASEPILOT_FILES_ACCEPTANCE !== '1', 'Requires isolated services');
test.use({ viewport: { width: 1440, height: 1000 } });

async function setup(page: Page) {
  await mkdir(output, { recursive: true });
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  const response = await page.request.post(`${api}/auth/register`, { data: { email: `nav-${Date.now()}-${Math.random().toString(36).slice(2)}@casepilot.test`, password: 'CasePilot123!', display_name: '反复切换验收' } });
  expect(response.status()).toBe(201);
  const account = await response.json();
  const collections = [];
  for (const name of ['有文件工作台', '空工作台']) {
    const created = await page.request.post(`${api}/spaces/${account.spaces[0].id}/collections`, { data: { name: `${name}-${Date.now()}` } });
    expect(created.status()).toBe(201);
    collections.push(await created.json());
  }
  await page.goto(`/workbench/collections/${collections[0].id}`);
  await expect(page.locator('.principle-composer textarea')).toBeEnabled();
  const workspace = await (await page.request.get(`${api}/collections/${collections[0].id}/workspace`)).json();
  return { collections, workspace };
}

test('rapid tab changes persist the final selection even when an earlier save is slow', async ({ page }) => {
  const { workspace } = await setup(page);
  await filesTab(page).click();
  await expect.poll(async () => (await (await page.request.get(`${api}/conversations/${workspace.id}`)).json()).context.active_view).toBe('files');
  await page.route(`**/workspaces/${workspace.id}`, async route => {
    if (route.request().method() === 'PATCH' && route.request().postDataJSON()?.active_view === 'map') await delay(800);
    await route.continue();
  });
  const mapSaved = page.waitForResponse(r => r.request().method() === 'PATCH' && r.url().endsWith(`/workspaces/${workspace.id}`) && r.request().postDataJSON()?.active_view === 'map');
  const filesSaved = page.waitForResponse(r => r.request().method() === 'PATCH' && r.url().endsWith(`/workspaces/${workspace.id}`) && r.request().postDataJSON()?.active_view === 'files');
  await page.getByRole('button', { name: '用例脑图', exact: true }).click();
  await filesTab(page).click();
  expect((await mapSaved).ok()).toBe(true);
  expect((await filesSaved).ok()).toBe(true);
  await page.unroute(`**/workspaces/${workspace.id}`);
  await page.reload();
  await expect(filesTab(page)).toHaveAttribute('aria-pressed', 'true');
});

test('20 navigation cycles preserve files, previews, downloads and workspace isolation', async ({ page }, testInfo) => {
  test.setTimeout(300_000);
  const roundNumber = testInfo.repeatEachIndex + Number(process.env.CASEPILOT_REPEAT_OFFSET ?? 0) + 1;
  const errors: string[] = [];
  const serverErrors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => { if (response.url().startsWith(api) && response.status() >= 500) serverErrors.push(`${response.status()} ${response.url()}`); });
  const { collections, workspace } = await setup(page);
  const home = `/workbench/collections/${collections[0].id}`;
  const empty = `/workbench/collections/${collections[1].id}`;
  const files = [0, 1, 2].map(i => ({ name: `切换文件-${i}.txt`, mimeType: 'text/plain', buffer: Buffer.from(`NAV-FILE-${i}：独立内容，不可串文件。`) }));
  const uploading = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/attachments'));
  await page.locator('.principle-composer input[type=file]').setInputFiles(files);
  const upload = await uploading;
  expect(upload.status()).toBe(202);
  await filesTab(page).click();
  await expect(fileList(page).getByText(/已就绪/)).toHaveCount(3, { timeout: 90_000 });
  const counters = { cycles: 0, tabClicks: 1, fileSelections: 0, reloads: 0, pageNavigations: 0, downloads: 0, delayedPreviewSwitches: 0 };
  async function assertFiles() {
    await expect(filesTab(page)).toHaveAttribute('aria-pressed', 'true');
    await expect(fileList(page).getByRole('button')).toHaveCount(3);
    for (let i = 0; i < 3; i++) {
      await fileList(page).getByRole('button', { name: new RegExp(`^切换文件-${i}\\.txt `) }).click();
      counters.fileSelections++;
      await expect(preview(page).locator('pre')).toContainText(`NAV-FILE-${i}`);
      for (let other = 0; other < 3; other++) if (other !== i) await expect(preview(page).locator('pre')).not.toContainText(`NAV-FILE-${other}`);
    }
  }
  for (let cycle = 0; cycle < 20; cycle++) {
    for (const label of ['用例脑图', '用例列表', '用例工作区']) {
      await page.getByRole('button', { name: label, exact: true }).click();
      counters.tabClicks++;
      await expect(preview(page)).toHaveCount(0);
      await filesTab(page).click();
      counters.tabClicks++;
      await assertFiles();
    }
    if (cycle % 4 === 0) {
      await expect.poll(async () => (await (await page.request.get(`${api}/conversations/${workspace.id}`)).json()).context.active_view).toBe('files');
      await page.reload(); counters.reloads++;
      await assertFiles();
      await page.goto(empty); counters.pageNavigations++;
      await filesTab(page).click(); counters.tabClicks++;
      await expect(page.getByText('暂无上传文件')).toBeVisible();
      await page.goBack(); counters.pageNavigations++;
      await assertFiles();
      await page.goForward(); counters.pageNavigations++;
      await expect(page.getByText('暂无上传文件')).toBeVisible();
      await page.goBack(); counters.pageNavigations++;
      await assertFiles();
      const section = ['用例资产管理', 'QA 用例执行', '空间知识库'][Math.floor(cycle / 4) % 3];
      await page.getByRole('button', { name: section, exact: true }).click(); counters.pageNavigations++;
      await expect(page.locator('.principle-workbench')).toHaveCount(0);
      await expect(page).toHaveURL(new RegExp(section === '用例资产管理' ? '/cases' : section === 'QA 用例执行' ? '/executions' : '/knowledge'));
      await page.goBack(); counters.pageNavigations++;
      await assertFiles();
      const downloadEvent = page.waitForEvent('download');
      await preview(page).getByRole('button', { name: '下载原文件' }).click();
      const download = await downloadEvent;
      expect(await readFile((await download.path())!, 'utf8')).toBe(files[2].buffer.toString());
      counters.downloads++;
    }
    if (cycle % 5 === 0) {
      await page.route('**/knowledge-documents/*/preview', async route => { await delay(500); await route.continue().catch(() => undefined); });
      await fileList(page).getByRole('button', { name: /^切换文件-0/ }).click();
      await fileList(page).getByRole('button', { name: /^切换文件-1/ }).click();
      await page.getByRole('button', { name: '用例列表', exact: true }).click();
      await filesTab(page).click();
      counters.tabClicks += 2;
      counters.delayedPreviewSwitches++;
      await assertFiles();
      await page.unrouteAll({ behavior: 'wait' });
    }
    counters.cycles++;
    if (cycle % 5 === 4) console.log(`navigation round ${roundNumber}: ${cycle + 1}/20 cycles passed`);
  }
  expect(errors).toEqual([]);
  expect(serverErrors).toEqual([]);
  await page.screenshot({ path: `${output}/round-${roundNumber}.png`, fullPage: true });
  await writeFile(`${output}/round-${roundNumber}.json`, JSON.stringify({ counters, errors, serverErrors, home }, null, 2));
});
