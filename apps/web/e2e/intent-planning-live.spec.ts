import { expect, test } from '@playwright/test';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1', 'Requires live API and model');
test.use({ viewport: { width: 1600, height: 1000 }, video: { mode: 'on', size: { width: 1600, height: 1000 } }, trace: 'on' });
const dir = resolve('../../output/intent-optimization');
const api = `${process.env.CASEPILOT_E2E_API_URL}/api/v1`;

test('semantic plan: missing target, clarification, independent scopes and preserved data', async ({ page }) => {
  test.setTimeout(600000);
  const manifest = JSON.parse(readFileSync(`${dir}/manifest.json`, 'utf8'));
  const collectionId = manifest.collection.id;
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  expect((await page.request.post(`${api}/auth/login`, { data: { email: 'demo@casepilot.local', password: 'CasePilot123!' } })).ok()).toBeTruthy();
  const readCases = async () => (await (await page.request.get(`${api}/collections/${collectionId}/test-cases`)).json());
  const state = await (await page.request.get(`${api}/collections/${collectionId}/workspace`)).json();
  const cid = state.id;
  const before = await readCases();
  expect(state.context.selected_targets.flatMap((s: {target:{case_ids?:string[]}}) => s.target.case_ids ?? []).every((id:string) => before.some((c:{id:string}) => c.id === id))).toBe(true);
  await page.goto(`/workbench/collections/${collectionId}`);
  const composer = page.locator('.principle-composer textarea');
  const records: unknown[] = [];
  async function send(content: string) {
    await expect(composer).toBeEnabled({ timeout: 300000 });
    await composer.fill(content);
    const response = page.waitForResponse(r => r.request().method() === 'POST' && /\/(messages|resume)$/.test(new URL(r.url()).pathname), { timeout: 120000 });
    await page.locator('.principle-composer button[type=submit]').click();
    const r = await response;
    expect(r.ok()).toBeTruthy();
    const body = await r.json(); records.push({ content, body });
    writeFileSync(`${dir}/clarification-results.json`, JSON.stringify(records, null, 2));
    return body;
  }
  // Establish a prior single-case result; it must not silently become a new mutation target.
  const order = before.find((c:{module:string}) => c.module === '订单库存');
  await send(`查询用例 ${order.case_key}`);
  await expect(page.locator('.task-query-table tbody tr')).toHaveCount(1);
  const unclear = await send('把优先级设为P0。');
  expect(unclear.intent).toBe('CASE_MODIFY');
  expect(unclear.assistant_message.status).toBe('awaiting_clarification');
  expect(unclear.operation_plan.operations[0].payload.plan.clarification_questions.length).toBeGreaterThan(0);
  expect(await readCases()).toEqual(before);
  await page.screenshot({ path: `${dir}/18-target-clarification.png`, fullPage: true });
  const clarified = await send('处理「账号登录」模块的全部用例，优先级改为P1，标题和步骤保持不变。');
  expect(clarified.operation_plan.operations[0].id).toBe(unclear.operation_plan.operations[0].id);
  const review = page.locator('.collection-changes__review');
  await expect(review).toContainText('P1', { timeout: 240000 });
  await expect(review.locator('.collection-changes__items > details')).toHaveCount(3);
  expect(await readCases()).toEqual(before);
  await page.screenshot({ path: `${dir}/19-clarified-module-diff.png`, fullPage: true });
  await review.getByRole('button', { name: '取消变更', exact: true }).click();
  await expect(page.locator('.collection-changes__badge')).toHaveText('未应用');
  const multi = await send('查询账号登录模块，然后查询订单库存模块。');
  expect(multi.operation_plan.operations).toHaveLength(2);
  await expect.poll(async () => {
    const current = await (await page.request.get(`${api}/conversations/${cid}`)).json();
    return current.operation_history.filter((op:{source_message_id:string}) => op.source_message_id === multi.user_message.id).filter((op:{status:string}) => op.status === 'completed').length;
  }, { timeout: 180000 }).toBe(2);
  const after = await (await page.request.get(`${api}/conversations/${cid}`)).json();
  const ops = after.operation_history.filter((op:{source_message_id:string}) => op.source_message_id === multi.user_message.id).sort((a:{sequence:number},b:{sequence:number}) => a.sequence-b.sequence);
  expect(ops[0].result.scope_count).toBe(3);
  expect(ops[1].result.scope_count).toBe(1);
  expect(ops.every((op:{payload:{plan:{routing_source:string}}}) => op.payload.plan.routing_source === 'semantic')).toBe(true);
  expect(await readCases()).toEqual(before);
  records.push({ passed: true, operations: ops });
  writeFileSync(`${dir}/clarification-results.json`, JSON.stringify(records, null, 2));
  await page.screenshot({ path: `${dir}/20-multi-task-independent-scopes.png`, fullPage: true });
});
