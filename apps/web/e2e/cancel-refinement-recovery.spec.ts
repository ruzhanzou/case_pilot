import { test, expect } from '@playwright/test';
import { writeFileSync } from 'node:fs';

test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1', 'Requires real-model acceptance services');
test.setTimeout(480000);
test('cancel a refinement, reload, and continue without losing the earlier proposal', async ({ page }, info) => {
  const api = `${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
  const post = async (path: string, data: unknown) => {
    const r = await page.request.post(api + path, { data });
    expect(r.ok(), await r.text()).toBeTruthy(); return r.json();
  };
  const get = async (path: string) => {
    const r = await page.request.get(api + path); expect(r.ok()).toBeTruthy(); return r.json();
  };
  const user = await post('/auth/register', { email: `cancel-refine-${Date.now()}@casepilot.test`, password: 'CasePilot123!', display_name: '中断续改验收' });
  const collection = await post(`/spaces/${user.spaces[0].id}/collections`, { name: '取消后一轮仍保留前轮成果' });
  const item = await post(`/collections/${collection.id}/test-cases`, { title: '原始登录', module: '账号', priority: 'P1', preconditions: ['账号有效'], steps: [{ action: '提交登录', expected: '进入首页' }] });
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  await page.goto(`/workbench/collections/${collection.id}`);
  const input = page.locator('.principle-composer textarea');
  const send = async (content: string) => {
    await expect(page.locator('.principle-composer button[type=submit]')).toBeVisible({ timeout: 60000 });
    await input.fill(content);
    const response = page.waitForResponse(r => /\/(messages|resume)$/.test(new URL(r.url()).pathname) && r.request().method() === 'POST', { timeout: 180000 });
    await page.locator('.principle-composer button[type=submit]').click();
    const r = await response; expect(r.ok(), await r.text()).toBeTruthy(); let turn = await r.json();
    if (turn.assistant_message?.metadata.modification_confirmation) {
      const resumed = page.waitForResponse(r => r.url().endsWith('/resume') && r.request().method() === 'POST', { timeout: 180000 });
      await page.getByRole('button', { name: '确认修改并生成建议', exact: true }).last().click();
      const r = await resumed; expect(r.ok(), await r.text()).toBeTruthy(); turn = await r.json();
    }
    return turn;
  };
  const ready = async (id: string) => {
    await expect.poll(async () => (await get(`/case-change-sets/${id}`)).status, { timeout: 180000 }).toBe('ready');
    await expect(page.locator('.collection-changes__review').getByRole('button', { name: /一键采纳全部待审阅用例/ })).toBeEnabled({ timeout: 30000 });
    return get(`/case-change-sets/${id}`);
  };
  const first = await send(`仅将用例 ${item.case_key} 的标题改为「有效账号登录成功」，其他字段保持不变。`);
  const originalProposal = await ready(first.action.change_set_id);
  expect(originalProposal.items[0].proposed_snapshot.title).toBe('有效账号登录成功');
  await page.getByRole('button', { name: '继续调整这版结果', exact: true }).click();
  const second = await send('在上一版修改建议基础上，只把优先级改为P0，其他修改保持不变。');
  expect(second.action.job_id).toBeTruthy();
  await expect.poll(async () => (await get(`/generation-jobs/${second.action.job_id}`)).status, { timeout: 30000, intervals: [100, 200] }).toBe('running');
  await page.locator('.principle-composer').getByRole('button', { name: '结束任务', exact: true }).click();
  await expect.poll(async () => (await get(`/generation-jobs/${second.action.job_id}`)).status).toBe('cancelled');
  await page.reload();
  expect((await get(`/case-change-sets/${first.action.change_set_id}`)).items).toEqual(originalProposal.items);
  expect(await get(`/collections/${collection.id}/test-cases`)).toEqual([item]);
  const third = await send('继续上一版未采纳的修改建议，只将优先级改为P2，其他字段和之前的修改保持不变。');
  const finalProposal = await ready(third.action.change_set_id);
  expect(finalProposal.items[0].previous_change_set_id).toBe(first.action.change_set_id);
  expect(finalProposal.items[0].proposed_snapshot.title).toBe('有效账号登录成功');
  expect(finalProposal.items[0].proposed_snapshot.priority).toBe('P2');
  await page.locator('.collection-changes__review').getByRole('button', { name: /一键采纳全部待审阅用例/ }).click();
  await expect.poll(async () => (await get(`/collections/${collection.id}/test-cases`))[0].revision_number).toBe(item.revision_number + 1);
  await page.reload();
  const cases = await get(`/collections/${collection.id}/test-cases`);
  expect(cases[0].title).toBe('有效账号登录成功'); expect(cases[0].priority).toBe('P2');
  expect(cases[0].preconditions).toEqual(item.preconditions);
  expect(cases[0].steps.map((s: { action: string; expected: string }) => ({ action: s.action, expected: s.expected }))).toEqual(item.steps.map((s: { action: string; expected: string }) => ({ action: s.action, expected: s.expected })));
  expect((await get(`/generation-jobs/${second.action.job_id}`)).status).toBe('cancelled');
  await expect(page.locator('.principle-workbench')).toBeVisible();
  await expect(page.locator('.collection-changes__review')).toContainText('有效账号登录成功');
  writeFileSync(info.outputPath('evidence.json'), JSON.stringify({ first, originalProposal, second, third, finalProposal, cases }, null, 2));
  await page.screenshot({ path: info.outputPath('continued-after-cancel.png'), fullPage: true });
});
