/* eslint-disable @typescript-eslint/no-explicit-any -- Real service acceptance evidence. */
import { test, expect } from '@playwright/test';
import { writeFileSync } from 'node:fs';
test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1', 'Requires deployed real model');
test.use({ viewport: { width: 1700, height: 1100 }, trace: 'on' });
test('batch rewrite remains running after preview and cancellation keeps all originals', async ({ page }, info) => {
  test.setTimeout(720000);
  const api = `${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
  const post = async (path: string, data: any) => { const r = await page.request.post(api + path, { data }); expect(r.ok(), await r.text()).toBeTruthy(); return r.json(); };
  const get = async (path: string) => { const r = await page.request.get(api + path); expect(r.ok()).toBeTruthy(); return r.json(); };
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  const account = await post('/auth/login', { email: 'demo@casepilot.local', password: 'CasePilot123!' });
  const collection = await post(`/spaces/${account.spaces[0].id}/collections`, { name: `批量状态及取消-${Date.now()}` });
  for (let i = 1; i <= 25; i++) await post(`/collections/${collection.id}/test-cases`, { case_key: `B-${i}`, title: `账号user_${i}登录`, module: '登录', priority: 'P1', case_type: '功能', preconditions: [`账号user_${i}可用`], steps: [{ action: `user_${i}以正确密码登录`, expected: '登录成功' }] });
  const original = await get(`/collections/${collection.id}/test-cases`);
  await page.goto(`/workbench/collections/${collection.id}`);
  const composer = page.locator('.principle-composer textarea'); await expect(composer).toBeEnabled({ timeout: 60000 });
  await composer.fill('改写当前集合全部25条用例：每条最后一步预期补充“审计日志包含该账号的成功登录记录”，保留原有预期和所有其他字段。');
  let pending = page.waitForResponse(r => r.request().method() === 'POST' && /\/(messages|resume)$/.test(new URL(r.url()).pathname), { timeout: 180000 });
  await page.locator('.principle-composer button[type=submit]').click(); let turn = await (await pending).json();
  if (turn.assistant_message?.metadata.modification_confirmation) {
    pending = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/resume'), { timeout: 180000 });
    await page.getByRole('button', { name: '确认修改并生成建议', exact: true }).click(); turn = await (await pending).json();
  }
  expect(turn.action.change_set_id).toBeTruthy();
  const change = () => get(`/case-change-sets/${turn.action.change_set_id}`);
  await expect.poll(async () => { const c = await change(); if (c.status === 'failed') throw new Error(JSON.stringify(c)); return [c.status, c.items.length]; }, { timeout: 540000, intervals: [1000] }).toEqual(['generating', 20]);
  await expect(page.getByTestId('rewrite-batch-preview')).toBeVisible();
  await expect(page.getByLabel('AI 改写状态')).toContainText('正在处理 25 条用例');
  await expect(page.getByText('改写完成，等待审阅', { exact: true })).toHaveCount(0);
  await expect(page.locator('.case-task-running')).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('running-preview.png'), fullPage: true });
  const preview = await change();
  await page.getByRole('button', { name: '结束任务', exact: true }).click();
  await expect(composer).toBeEnabled({ timeout: 60000 });
  await page.reload(); await expect(composer).toBeEnabled();
  expect(await get(`/collections/${collection.id}/test-cases`)).toEqual(original);
  const job = await get(`/generation-jobs/${turn.action.job_id}`); expect(job.status).toBe('cancelled');
  writeFileSync(info.outputPath('evidence.json'), JSON.stringify({ turn, preview, job, original, final: await get(`/collections/${collection.id}/test-cases`) }, null, 2));
});
