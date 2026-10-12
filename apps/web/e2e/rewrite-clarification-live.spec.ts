import { expect, test, type Page, type TestInfo } from '@playwright/test';
import { writeFileSync } from 'node:fs';
import type { ConversationTurnDto, TestCaseDto, CaseChangeSetDto } from '../lib/casepilot-api';

test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1', 'Requires isolated real API, worker and model');
test.use({ viewport: { width: 1600, height: 1000 }, trace: 'on' });
test.setTimeout(480_000);
const api = `${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
test.beforeEach(async ({ page }, info) => {
  const timings: { path: string; milliseconds: number }[] = [];
  page.on('requestfinished', request => {
    const path = new URL(request.url()).pathname;
    if (request.method() !== 'POST' || !/\/(messages|resume|confirm-intent|apply)$/.test(path)) return;
    timings.push({ path, milliseconds: request.timing().responseEnd });
    writeFileSync(info.outputPath('request-timings.json'), JSON.stringify(timings, null, 2));
  });
});
async function setup(page: Page) {
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  const registration = await page.request.post(`${api}/auth/register`, { data: { email: `rewrite-e2e-${Date.now()}@casepilot.test`, display_name: '重写续办验收', password: 'CasePilot123!' } });
  expect(registration.status()).toBe(201);
  const account = await registration.json();
  const response = await page.request.post(`${api}/spaces/${account.spaces[0].id}/collections`, { data: { name: `重写续办验收-${Date.now()}` } });
  expect(response.ok()).toBeTruthy();
  const collection = await response.json();
  const originals: TestCaseDto[] = [];
  for (const [module, title, action, expected] of [['登录', '手机号密码登录成功', '输入手机号和密码并登录', '进入首页'], ['订单', '查看订单详情', '打开订单', '显示订单详情']]) {
    const result = await page.request.post(`${api}/collections/${collection.id}/test-cases`, { data: { module, title, priority: 'P1', preconditions: ['测试账号已注册，使用有效凭据'], steps: [{ action, expected }] } });
    expect(result.status()).toBe(201); originals.push(await result.json());
  }
  await page.goto(`/workbench/collections/${collection.id}`);
  await expect(page.locator('.principle-composer textarea')).toBeEnabled();
  const read = async (): Promise<TestCaseDto[]> => (await page.request.get(`${api}/collections/${collection.id}/test-cases`)).json();
  return { originals, read, collection };
}
async function send(page: Page, content: string): Promise<ConversationTurnDto> {
  const input = page.locator('.principle-composer textarea');
  await expect(input).toBeEnabled({ timeout: 240_000 });
  await input.fill(content);
  const waiting = page.waitForResponse(r => r.request().method() === 'POST' && /\/(messages|resume)$/.test(new URL(r.url()).pathname), { timeout: 180_000 });
  await page.locator('.principle-composer button[type=submit]').click();
  const result = await waiting;
  expect(result.ok(), await result.text()).toBeTruthy();
  return result.json();
}
async function capture(page: Page, info: TestInfo, data: unknown, name: string) {
  writeFileSync(info.outputPath(`${name}.json`), JSON.stringify(data, null, 2));
  await expect(page.locator('.principle-composer textarea')).toBeVisible({ timeout: 60_000 });
  await expect(page.locator('.principle-message.is-user').first()).toBeAttached({ timeout: 60_000 });
  await page.screenshot({ path: info.outputPath(`${name}.png`), fullPage: true });
}

test('resolved rewrite scope survives clarification and reload through real model adoption', async ({ page }, info) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  const s = await setup(page);
  const first = await send(page, '重写登录模块用例');
  await capture(page, info, first, '01-initial-clarification');
  expect(first.action.job_id).toBeFalsy();
  expect(first.assistant_message?.metadata.modification_confirmation).not.toBe(true);
  expect(first.operation_plan?.operations[0].target.case_ids).toEqual([s.originals[0].id]);
  await page.reload();
  const reply = await send(page, '操作细节');
  await capture(page, info, reply, '02-short-reply');
  expect(reply.operation_plan?.operations[0].id).toBe(first.operation_plan?.operations[0].id);
  expect(reply.assistant_message?.metadata.modification_confirmation).toBe(true);
  expect(reply.assistant_message?.target_case_ids).toEqual([s.originals[0].id]);
  expect(await s.read()).toEqual(s.originals);
  await page.reload();
  const waiting = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/resume'), { timeout: 180_000 });
  await page.getByRole('button', { name: '确认修改并生成建议', exact: true }).last().click();
  const response = await waiting; expect(response.ok()).toBeTruthy();
  const confirmed = await response.json() as ConversationTurnDto;
  expect(confirmed.action.job_id).toBeTruthy();
  let change: CaseChangeSetDto;
  await expect.poll(async () => {
    change = await (await page.request.get(`${api}/case-change-sets/${confirmed.action.change_set_id}`)).json();
    if (change.status === 'failed') throw new Error(JSON.stringify(change));
    return change.status;
  }, { timeout: 240_000, intervals: [2000] }).toBe('ready');
  expect(change!.items.map(i => i.ref)).toEqual([s.originals[0].id]);
  expect(await s.read()).toEqual(s.originals);
  await expect(page.locator('.collection-changes__review')).toBeVisible({ timeout: 60_000 });
  await capture(page, info, { confirmed, change: change! }, '03-review-before-save');
  const applying = page.waitForResponse(r => r.request().method() === 'POST' && /\/apply$/.test(new URL(r.url()).pathname));
  await page.locator('.collection-changes__review').getByRole('button', { name: /一键采纳全部待审阅用例/ }).click();
  expect((await applying).ok()).toBeTruthy();
  await page.reload();
  const after = await s.read();
  const target = after.find(c => c.id === s.originals[0].id)!;
  expect(target.revision_number).toBe(s.originals[0].revision_number + 1);
  expect(target.steps).not.toEqual(s.originals[0].steps);
  expect(after.find(c => c.id === s.originals[1].id)).toEqual(s.originals[1]);
  expect(errors).toEqual([]);
  await capture(page, info, { first, reply, confirmed, before: s.originals, after, errors }, '04-persisted-result');
});

test('unresolved scope keeps direction and resumes after choosing a case', async ({ page }, info) => {
  const s = await setup(page);
  let first = await send(page, '重写「火星支付XYZ」模块用例');
  if (first.requires_intent_confirmation) {
    const confirming = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/confirm-intent'), { timeout: 180_000 });
    await page.locator('.conversation-intent-confirmation').getByRole('button', { name: /修改/ }).click();
    const response = await confirming; expect(response.ok()).toBeTruthy();
    first = await response.json();
  }
  expect(first.action.job_id).toBeFalsy();
  const reply = await send(page, '操作细节');
  await capture(page, info, { first, reply }, '01-scope-still-missing');
  expect(reply.action.job_id).toBeFalsy();
  expect(reply.assistant_message?.metadata.modification_confirmation).not.toBe(true);
  expect(await s.read()).toEqual(s.originals);
  await page.reload();
  await page.getByRole('button', { name: '用例列表', exact: true }).click();
  const row = page.locator('.principle-case-row').filter({ hasText: s.originals[0].title });
  await row.getByRole('checkbox').check();
  const result = await send(page, '');
  await capture(page, info, result, '02-selected-target-preview');
  expect(result.operation_plan?.operations[0].id).toBe(first.operation_plan?.operations[0].id);
  expect(result.assistant_message?.metadata.modification_confirmation).toBe(true);
  expect(result.assistant_message?.target_case_ids).toEqual([s.originals[0].id]);
  expect(result.assistant_message?.content).toContain('操作细节');
  expect(result.action.job_id).toBeFalsy();
  expect(await s.read()).toEqual(s.originals);
});

test('changed selection requires a fresh preview and saves only the reconfirmed case', async ({ page }, info) => {
  const s = await setup(page);
  const first = await send(page, '将当前集合所有用例的步骤写得更清晰，标题保持不变');
  expect(first.assistant_message?.metadata.modification_confirmation).toBe(true);
  expect(new Set(first.assistant_message?.target_case_ids)).toEqual(new Set(s.originals.map(c => c.id)));
  await page.reload();
  await page.getByRole('button', { name: '用例列表', exact: true }).click();
  const row = page.locator('.principle-case-row').filter({ hasText: s.originals[1].title });
  await row.getByRole('checkbox').uncheck();
  await expect(row.getByRole('checkbox')).not.toBeChecked();
  await page.locator('.principle-composer textarea').fill('前置条件和预期结果也保持不变，只丰富操作细节');
  const waiting = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/resume'), { timeout: 180_000 });
  await page.getByRole('button', { name: '确认修改并生成建议', exact: true }).last().click();
  const response = await waiting;
  expect(response.ok(), await response.text()).toBeTruthy();
  const revised = await response.json() as ConversationTurnDto;
  expect(response.request().postDataJSON().confirm_modification).toBe(false);
  expect(revised.action.job_id).toBeFalsy();
  expect(revised.assistant_message?.target_case_ids).toEqual([s.originals[0].id]);
  expect(revised.assistant_message?.metadata.modification_confirmation).toBe(true);
  expect(revised.assistant_message?.content).toContain('前置条件');
  expect(await s.read()).toEqual(s.originals);
  await capture(page, info, { first, revised, cases: await s.read() }, 'changed-selection-confirmation');
  await page.reload();
  const executing = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/resume'), { timeout: 180_000 });
  await page.getByRole('button', { name: '确认修改并生成建议', exact: true }).last().click();
  const execution = await executing; expect(execution.ok()).toBeTruthy();
  const confirmed = await execution.json() as ConversationTurnDto;
  expect(confirmed.action.job_id).toBeTruthy();
  const duplicate = await page.request.post(`${api}/conversation-operations/${revised.operation_plan!.operations[0].id}/resume`, { data: { confirm_modification: true } });
  expect(duplicate.status()).toBe(409);
  let change: CaseChangeSetDto;
  await expect.poll(async () => {
    change = await (await page.request.get(`${api}/case-change-sets/${confirmed.action.change_set_id}`)).json();
    if (change.status === 'failed') throw new Error(JSON.stringify(change));
    return change.status;
  }, { timeout: 240_000, intervals: [2000] }).toBe('ready');
  expect(change!.items.map(item => item.ref)).toEqual([s.originals[0].id]);
  expect(await s.read()).toEqual(s.originals);
  await expect(page.locator('.collection-changes__review')).toBeVisible({ timeout: 60_000 });
  const applying = page.waitForResponse(r => r.request().method() === 'POST' && /\/apply$/.test(new URL(r.url()).pathname));
  await page.locator('.collection-changes__review').getByRole('button', { name: /一键采纳全部待审阅用例/ }).click();
  expect((await applying).ok()).toBeTruthy();
  await page.reload();
  const after = await s.read(); const saved = after.find(c => c.id === s.originals[0].id)!;
  expect(saved.revision_number).toBe(s.originals[0].revision_number + 1);
  expect(saved.title).toBe(s.originals[0].title);
  expect(saved.preconditions).toEqual(s.originals[0].preconditions);
  expect(saved.steps.map(step => step.expected)).toEqual(s.originals[0].steps.map(step => step.expected));
  expect(saved.steps).not.toEqual(s.originals[0].steps);
  expect(after.find(c => c.id === s.originals[1].id)).toEqual(s.originals[1]);
  const repeatedApply = await page.request.post(`${api}/case-change-sets/${confirmed.action.change_set_id}/apply`, { data: {} });
  expect(repeatedApply.ok()).toBeTruthy();
  expect(await s.read()).toEqual(after);
  await capture(page, info, { first, revised, confirmed, change: change!, before: s.originals, after, duplicateConfirmationStatus: duplicate.status() }, 'changed-selection-saved');
});


test('clearing selected cases blocks confirmation and cancellation leaves cases unchanged', async ({ page }, info) => {
  const s = await setup(page);
  let first = await send(page, '将登录模块用例的步骤写得更清晰');
  if (first.requires_intent_confirmation) {
    // Live models may fail the exact-evidence guard. Follow the explicit user
    // confirmation UI; never bypass the guard or assume that parsing succeeded.
    expect(first.action.job_id).toBeFalsy();
    expect(await s.read()).toEqual(s.originals);
    const confirming = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/confirm-intent'), { timeout: 180_000 });
    await page.locator('.conversation-intent-confirmation').getByRole('button', { name: /修改/ }).click();
    const response = await confirming; expect(response.ok()).toBeTruthy();
    first = await response.json();
  }
  expect(first.assistant_message?.metadata.modification_confirmation).toBe(true);
  await page.getByRole('button', { name: '用例列表', exact: true }).click();
  await page.locator('.principle-case-row').filter({ hasText: s.originals[0].title }).getByRole('checkbox').uncheck();
  const requests: string[] = [];
  page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/resume')) requests.push(request.url()); });
  await page.getByRole('button', { name: '确认修改并生成建议', exact: true }).last().click();
  await expect(page.getByText('请先选择要修改的用例，再确认修改。', { exact: true })).toBeVisible();
  expect(requests).toEqual([]);
  expect(await s.read()).toEqual(s.originals);
  await capture(page, info, { first, requests, cases: await s.read() }, 'empty-selection-blocked');
  const cancelling = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/cancel'));
  await page.getByRole('button', { name: '结束任务', exact: true }).last().click();
  expect((await cancelling).ok()).toBeTruthy();
  await page.reload();
  expect(await s.read()).toEqual(s.originals);
  const staleConfirm = await page.request.post(`${api}/conversation-operations/${first.operation_plan!.operations[0].id}/resume`, { data: { confirm_modification: true } });
  expect(staleConfirm.status()).toBe(409);
  await capture(page, info, { unchanged: await s.read(), staleConfirmationStatus: staleConfirm.status() }, 'cancelled-unchanged');
});
