import { expect, test, type Page } from '@playwright/test';
import * as XLSX from 'xlsx';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const api = `${process.env.CASEPILOT_E2E_API_URL ?? 'http://localhost:8015'}/api/v1`;
const output = path.resolve('../../output/workspace-files-e2e');
test.use({ viewport: { width: 1440, height: 1000 } });
test.skip(process.env.CASEPILOT_FILES_ACCEPTANCE !== '1', 'Requires isolated API and parser worker');

async function setup(page: Page) {
  await mkdir(output, { recursive: true });
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  const response = await page.request.post(`${api}/auth/register`, { data: {
    email: `files-${Date.now()}-${Math.random().toString(36).slice(2)}@casepilot.test`, password: 'CasePilot123!', display_name: '文件页验收',
  } });
  expect(response.status()).toBe(201);
  const account = await response.json();
  const created = await page.request.post(`${api}/spaces/${account.spaces[0].id}/collections`, { data: { name: `文件工作台验收-${Date.now()}` } });
  expect(created.status()).toBe(201);
  const collection = await created.json();
  await page.goto(`/workbench/collections/${collection.id}`);
  await expect(page.locator('.principle-composer textarea')).toBeEnabled();
  const workspace = await (await page.request.get(`${api}/collections/${collection.id}/workspace`)).json();
  return { account, collection, workspace };
}
const filesTab = (page: Page) => page.getByRole('button', { name: '上传文件', exact: true });
const fileList = (page: Page) => page.getByRole('navigation', { name: '上传文件', exact: true });
const preview = (page: Page) => page.getByRole('region', { name: '文件预览' });
async function upload(page: Page, files: { name: string; mimeType: string; buffer: Buffer }[]) {
  const response = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/attachments'));
  await page.locator('.principle-composer input[type=file]').setInputFiles(files);
  const result = await response;
  expect(result.status()).toBe(202);
  return result.json();
}

test('real uploads → previews → exact downloads → persistence → sent files → isolation and responsive layout', async ({ page, playwright }) => {
  test.setTimeout(240_000);
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  const { workspace, collection } = await setup(page);
  await filesTab(page).click();
  await expect(page.getByText('暂无上传文件')).toBeVisible();
  await page.screenshot({ path: `${output}/01-empty.png`, fullPage: true });
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet([['需求', '规则'], ['FILE-XLSX-42', '验证码7分钟有效']]), '登录规则');
  const fixtures = [
    { name: '中文需求.txt', mimeType: 'text/plain', buffer: Buffer.from('FILE-TXT-42：连续输错4次后锁定19分钟。\n<script>alert("unsafe")</script>') },
    { name: '需求说明.pdf', mimeType: 'application/pdf', buffer: Buffer.from('JVBERi0xLjcKJcK1wrYKJSBXcml0dGVuIGJ5IE11UERGIDEuMjkuMAoKMSAwIG9iago8PC9UeXBlL0NhdGFsb2cvUGFnZXMgMiAwIFIvSW5mbzw8L1Byb2R1Y2VyKE11UERGIDEuMjkuMCk+Pj4+CmVuZG9iagoKMiAwIG9iago8PC9UeXBlL1BhZ2VzL0NvdW50IDEvS2lkc1s0IDAgUl0+PgplbmRvYmoKCjMgMCBvYmoKPDwvRm9udDw8L2hlbHYgNSAwIFI+Pj4+CmVuZG9iagoKNCAwIG9iago8PC9UeXBlL1BhZ2UvTWVkaWFCb3hbMCAwIDU5NSA4NDJdL1JvdGF0ZSAwL1Jlc291cmNlcyAzIDAgUi9QYXJlbnQgMiAwIFIvQ29udGVudHNbNiAwIFJdPj4KZW5kb2JqCgo1IDAgb2JqCjw8L1R5cGUvRm9udC9TdWJ0eXBlL1R5cGUxL0Jhc2VGb250L0hlbHZldGljYS9FbmNvZGluZy9XaW5BbnNpRW5jb2Rpbmc+PgplbmRvYmoKCjYgMCBvYmoKPDwvTGVuZ3RoIDEyMC9GaWx0ZXIvRmxhdGVEZWNvZGU+PgpzdHJlYW0KeNo1i7EKgjEMhPc8Rd7AJE0vFMRBcHETsomD2BYHHVx8fvsPchx88N3Rh45JyrKiHMYRwvmm3XO8vqzKOfm6d3jzh1frVdwd1osXK3eTEGg0dFSMcBMMzHA0YLUst/HEWEtDDY2KttH/EcXG4ZZnOiVd6Afu/yB5CmVuZHN0cmVhbQplbmRvYmoKCnhyZWYKMCA3CjAwMDAwMDAwMDAgNjU1MzUgZiAKMDAwMDAwMDA0MiAwMDAwMCBuIAowMDAwMDAwMTIwIDAwMDAwIG4gCjAwMDAwMDAxNzIgMDAwMDAgbiAKMDAwMDAwMDIxMyAwMDAwMCBuIAowMDAwMDAwMzIwIDAwMDAwIG4gCjAwMDAwMDA0MDkgMDAwMDAgbiAKCnRyYWlsZXIKPDwvU2l6ZSA3L1Jvb3QgMSAwIFIvSURbPDFENDNDMzkxNEM2RkMyQTVDMkEwMTk0OUMyOTdDM0FGPjxGMkM0NEY5MEIxMkMyMEE4ODkyMEMxQUZBMkZDNjJBOT5dPj4Kc3RhcnR4cmVmCjU5OAolJUVPRgo=', 'base64') },
    { name: '规则.xls', mimeType: 'application/vnd.ms-excel', buffer: XLSX.write(workbook, { type: 'buffer', bookType: 'biff8' }) },
    { name: '登录规则.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: XLSX.write(workbook, { type: 'buffer', bookType: 'xlsx' }) },
  ];
  const uploaded = await upload(page, fixtures);
  await expect(fileList(page).getByRole('button')).toHaveCount(4);
  await expect.poll(async () => (await (await page.request.get(`${api}/knowledge-sources/${uploaded.source.id}`)).json()).status, { timeout: 90_000 }).toBe('ready');
  await expect(fileList(page).getByText(/已就绪/)).toHaveCount(4);
  const source = await (await page.request.get(`${api}/knowledge-sources/${uploaded.source.id}`)).json();
  for (let i = 0; i < fixtures.length; i++) {
    await fileList(page).getByRole('button', { name: new RegExp('^' + fixtures[i].name.replace('.', '\\.') + ' ') }).click();
    await expect(preview(page).locator('pre')).toContainText(['FILE-TXT-42', 'FILE-PDF-42', 'FILE-XLSX-42', 'FILE-XLSX-42'][i]);
    const downloading = page.waitForEvent('download');
    await preview(page).getByRole('button', { name: '下载原文件' }).click();
    const downloaded = await downloading;
    expect(downloaded.suggestedFilename()).toBe(fixtures[i].name);
    expect(Array.from(await readFile((await downloaded.path())!))).toEqual(Array.from(fixtures[i].buffer));
  }
  await page.screenshot({ path: `${output}/02-preview-download.png`, fullPage: true });
  for (const label of ['用例脑图', '用例列表', '用例工作区']) {
    await page.getByRole('button', { name: label, exact: true }).click();
    await expect(preview(page)).toHaveCount(0);
    await filesTab(page).click();
    await expect(fileList(page).getByRole('button')).toHaveCount(4);
  }
  await expect.poll(async () => (await (await page.request.get(`${api}/conversations/${workspace.id}`)).json()).context.active_view).toBe('files');
  await page.reload();
  await expect(filesTab(page)).toHaveAttribute('aria-pressed', 'true');
  await expect(fileList(page).getByRole('button')).toHaveCount(4);
  // Pending attachments move to a sent message without disappearing or duplicating.
  await page.locator('.principle-composer textarea').fill('你好');
  await page.locator('.principle-composer button[type=submit]').click();
  await expect.poll(async () => (await (await page.request.get(`${api}/conversations/${workspace.id}`)).json()).context.pending_attachments.length, { timeout: 60_000 }).toBe(0);
  await filesTab(page).click();
  await expect(fileList(page).getByRole('button')).toHaveCount(4);
  await page.reload();
  await expect(fileList(page).getByRole('button')).toHaveCount(4);
  // Cross-space and anonymous requests must not access either route.
  const stranger = await playwright.request.newContext();
  const docId = source.documents[0].id;
  for (const action of ['preview', 'download']) expect((await stranger.get(`${api}/knowledge-documents/${docId}/${action}`)).status()).toBe(401);
  expect((await stranger.post(`${api}/auth/register`, { data: { email: `stranger-${Date.now()}@casepilot.test`, password: 'CasePilot123!', display_name: '独立空间' } })).status()).toBe(201);
  for (const action of ['preview', 'download']) expect((await stranger.get(`${api}/knowledge-documents/${docId}/${action}`)).status()).toBe(403);
  await stranger.dispose();
  for (const width of [1280, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(filesTab(page)).toBeVisible();
    await fileList(page).getByRole('button', { name: /^登录规则.xlsx / }).click();
    await expect(preview(page).locator('pre')).toContainText('FILE-XLSX-42');
    await expect(preview(page).getByRole('button', { name: '下载原文件' })).toBeVisible();
    await page.screenshot({ path: `${output}/responsive-${width}.png`, fullPage: true });
  }
  expect(errors).toEqual([]);
  await writeFile(`${output}/main-evidence.json`, JSON.stringify({ collection, workspaceId: workspace.id, source, errors, checks: ['empty','4-formats','literal-script-text','download-byte-equality','tabs','refresh','sent-files','anonymous','cross-space','1280/768/390'] }, null, 2));
});

test('duplicate filenames, removal, preview retry, failed parsing and deleted files', async ({ page }) => {
  test.setTimeout(180_000);
  const { workspace } = await setup(page);
  await filesTab(page).click();
  await upload(page, [{ name: '同名.txt', mimeType: 'text/plain', buffer: Buffer.from('FIRST-FILE') }, { name: '同名.txt', mimeType: 'text/plain', buffer: Buffer.from('SECOND-FILE') }]);
  await expect(fileList(page).getByRole('button')).toHaveCount(2);
  await expect(fileList(page).getByText(/已就绪/)).toHaveCount(2, { timeout: 90_000 });
  await fileList(page).getByRole('button').first().click();
  const first = await preview(page).locator('pre').textContent();
  await fileList(page).getByRole('button').last().click();
  await expect(preview(page).locator('pre')).not.toHaveText(first!);
  // One transient transport failure, followed by a real API retry.
  let failed = false;
  await page.route('**/knowledge-documents/*/preview', async route => {
    if (!failed) { failed = true; await route.fulfill({ status: 503, json: { detail: '暂时不可用，请重试。' } }); }
    else await route.continue();
  });
  await page.getByRole('button', { name: '用例列表', exact: true }).click();
  await filesTab(page).click();
  await expect(preview(page).getByRole('alert')).toContainText('暂时不可用');
  await preview(page).getByRole('button', { name: '重试' }).click();
  await expect(preview(page).locator('pre')).toContainText(/FIRST-FILE|SECOND-FILE/);
  await page.unroute('**/knowledge-documents/*/preview');
  // Removing pending files must immediately update the file tab.
  await page.locator('.principle-composer').getByRole('button', { name: '移除 同名.txt', exact: true }).first().click();
  await expect(fileList(page).getByRole('button')).toHaveCount(1);
  const broken = await upload(page, [{ name: '损坏.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\ninvalid document') }]);
  await expect(fileList(page).getByRole('button', { name: /损坏.pdf/ })).toContainText('解析失败', { timeout: 90_000 });
  await fileList(page).getByRole('button', { name: /损坏.pdf/ }).click();
  await expect(preview(page)).toContainText('文件解析失败');
  const downloaded = page.waitForEvent('download');
  await preview(page).getByRole('button', { name: '下载原文件' }).click();
  expect((await downloaded).suggestedFilename()).toBe('损坏.pdf');
  expect((await page.request.delete(`${api}/knowledge-sources/${broken.source.id}`)).status()).toBe(204);
  await page.getByRole('button', { name: '用例列表', exact: true }).click();
  await filesTab(page).click();
  await fileList(page).getByRole('button', { name: /损坏.pdf/ }).click();
  await expect(preview(page).getByRole('alert')).toContainText('文件不存在或已被删除');
  const currentUrl = page.url();
  await preview(page).getByRole('button', { name: '下载原文件' }).click();
  await expect(preview(page).getByRole('alert')).toHaveCount(2);
  expect(page.url()).toBe(currentUrl);
  for (const action of ['preview', 'download']) expect((await page.request.get(`${api}/knowledge-documents/${broken.document_ids[0]}/${action}`)).status()).toBe(404);
  await page.screenshot({ path: `${output}/03-deleted-file.png`, fullPage: true });
  await writeFile(`${output}/edge-evidence.json`, JSON.stringify({ workspaceId: workspace.id, checks: ['same-name-distinct','retry','remove','real-parse-failure','deleted-file'] }, null, 2));
});

test('large preview is bounded, keyboard works, and another workspace has no leaked files', async ({ page }) => {
  test.setTimeout(180_000);
  const { account, collection } = await setup(page);
  const content = Array.from({ length: 6000 }, (_, i) => `Requirement ${i}: validate login and show a clear error when the account is locked.`).join('\n');
  await filesTab(page).focus();
  await page.keyboard.press('Enter');
  const uploaded = await upload(page, [{ name: '长文档.txt', mimeType: 'text/plain', buffer: Buffer.from(content) }]);
  await expect(fileList(page).getByText(/已就绪/)).toHaveCount(1, { timeout: 120_000 });
  await expect(preview(page)).toContainText('仅展示部分内容');
  const result = await (await page.request.get(`${api}/knowledge-documents/${uploaded.document_ids[0]}/preview`)).json();
  expect(result.truncated).toBe(true);
  expect(result.content.length).toBeLessThanOrEqual(100_000);
  const downloading = page.waitForEvent('download');
  await preview(page).getByRole('button', { name: '下载原文件' }).click();
  expect(await readFile((await (await downloading).path())!, 'utf8')).toBe(content);
  await page.screenshot({ path: `${output}/04-long-document.png`, fullPage: true });
  const other = await page.request.post(`${api}/spaces/${account.spaces[0].id}/collections`, { data: { name: '附件隔离验收' } });
  expect(other.status()).toBe(201);
  await page.goto(`/workbench/collections/${(await other.json()).id}`);
  await filesTab(page).click();
  await expect(page.getByText('暂无上传文件')).toBeVisible();
  await expect(fileList(page)).toHaveCount(0);
  await page.goto(`/workbench/collections/${collection.id}`);
  await expect(filesTab(page)).toHaveAttribute('aria-pressed', 'true');
  await expect(fileList(page).getByRole('button')).toHaveCount(1);
  await writeFile(`${output}/large-evidence.json`, JSON.stringify({ documentId: uploaded.document_ids[0], bytes: Buffer.byteLength(content), previewLength: result.content.length, truncated: result.truncated, workspaceIsolation: true }, null, 2));
});

test('a restored processing snapshot updates when parsing completes', async ({ page }) => {
  const { workspace } = await setup(page);
  await filesTab(page).click();
  await upload(page, [{ name: '恢复解析.txt', mimeType: 'text/plain', buffer: Buffer.from('RESTORED-PREVIEW-42') }]);
  await expect(fileList(page).getByText(/已就绪/)).toHaveCount(1, { timeout: 90_000 });
  // Reproduce a reload that receives the last processing snapshot, then let all reads use the real API.
  let injected = false;
  await page.route('**/api/v1/**', async route => {
    const url = route.request().url();
    if (!injected && (url.endsWith(`/conversations/${workspace.id}`) || url.endsWith('/workspace'))) {
      const response = await route.fetch();
      const body = await response.json();
      if (body.id === workspace.id && body.context?.pending_attachments?.length) {
        injected = true;
        for (const attachment of body.context.pending_attachments) attachment.status = 'parsing';
        await route.fulfill({ response, json: body });
        return;
      }
      await route.fulfill({ response });
      return;
    }
    await route.continue();
  });
  await page.reload();
  await expect(fileList(page).getByText(/解析中/)).toHaveCount(1);
  expect(injected).toBe(true);
  await expect(fileList(page).getByText(/已就绪/)).toHaveCount(1);
  await expect(preview(page).locator('pre')).toContainText('RESTORED-PREVIEW-42');
  await page.unroute('**/api/v1/**');
});
