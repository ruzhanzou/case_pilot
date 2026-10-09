import { writeFileSync } from 'node:fs';
import { expect, test, type Page, type TestInfo } from '@playwright/test';
import type { CaseChangeSetDto, ConversationTurnDto, TestCaseDto } from '../lib/casepilot-api';

// Real browser, API, worker, model and database. No network mocking.
test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1', 'Requires isolated real services');
test.use({ viewport: { width: 1600, height: 1000 }, trace: 'on', video: 'retain-on-failure' });
test.setTimeout(600_000);
const api = `${process.env.CASEPILOT_E2E_API_URL}/api/v1`;

async function get<T>(page: Page, path: string): Promise<T> {
  const response = await page.request.get(`${api}${path}`);
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}
async function setup(page: Page, long = false, titles = ['短信验证码校验', '用户名密码校验', '库存不足禁止下单']) {
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  const login = await page.request.post(`${api}/auth/login`, { data: { email: 'demo@casepilot.local', password: 'CasePilot123!' } });
  expect(login.ok()).toBeTruthy();
  const account = await login.json();
  const stamp = Date.now();
  const response = await page.request.post(`${api}/spaces/${account.spaces[0].id}/collections`, { data: { name: `修改回归验收-${stamp}` } });
  expect(response.ok()).toBeTruthy();
  const collection = await response.json() as { id: string };
  const original: TestCaseDto[] = [];
  for (const [index, title] of titles.entries()) {
    const created = await page.request.post(`${api}/collections/${collection.id}/test-cases`, { data: {
      case_key: `QA-${stamp}-${index}`, title, module: index < 2 ? '登录' : '订单', priority: index === 0 ? 'P0' : 'P1', case_type: '功能',
      preconditions: long && index === 0 ? [] : [index === 2 ? '商品库存为零' : '测试账号已注册'],
      steps: Array.from({ length: long && index === 0 ? 5 : 1 }, (_, n) => ({ action: index === 2 ? '提交数量为1的订单' : `第${n + 1}步提交登录请求`, expected: index === 2 ? '提示库存不足，不创建订单' : `第${n + 1}步返回登录成功` })),
    } });
    expect(created.status()).toBe(201);
    original.push(await created.json());
  }
  await page.goto(`/workbench/collections/${collection.id}`);
  await expect(page.locator('.principle-composer textarea')).toBeEnabled({ timeout: 60_000 });
  writeFileSync(test.info().outputPath('fixture.json'), JSON.stringify({ collection, original }, null, 2));
  return { collection, original, read: () => get<TestCaseDto[]>(page, `/collections/${collection.id}/test-cases`) };
}
async function send(page: Page, content: string, confirm = true, expectedIds?: string[]): Promise<ConversationTurnDto> {
  const composer = page.locator('.principle-composer textarea');
  await expect(composer).toBeEnabled({ timeout: 240_000 });
  await composer.fill(content);
  const waiting = page.waitForResponse(r => r.request().method() === 'POST' && /\/(messages|resume)$/.test(new URL(r.url()).pathname), { timeout: 180_000 });
  await page.locator('.principle-composer button[type=submit]').click();
  await expect(page.getByTestId('scope-thinking')).toBeVisible();
  await expect(page.getByTestId('scope-thinking')).toContainText('正在思考');
  const response = await waiting;
  await expect(page.getByTestId('scope-thinking')).toHaveCount(0);
  expect(response.ok(), await response.text()).toBeTruthy();
  const turn = await response.json() as ConversationTurnDto;
  writeFileSync(test.info().outputPath(`turn-${Date.now()}.json`), JSON.stringify({ content, turn }, null, 2));
  if (expectedIds) expect(new Set(turn.assistant_message?.target_case_ids)).toEqual(new Set(expectedIds));
  if (confirm && turn.assistant_message?.metadata.modification_confirmation === true) {
    expect(turn.action.job_id).toBeFalsy();
    const confirming = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/resume'), { timeout: 180_000 });
    await page.getByRole('button', { name: '确认修改并生成建议', exact: true }).last().click();
    const confirmed = await confirming;
    expect(confirmed.ok(), await confirmed.text()).toBeTruthy();
    return confirmed.json();
  }
  return turn;
}
async function ready(page: Page, turn: ConversationTurnDto) {
  expect(turn.action.change_set_id, JSON.stringify(turn)).toBeTruthy();
  const path = `/case-change-sets/${turn.action.change_set_id}`;
  await expect.poll(async () => {
    const result = await get<CaseChangeSetDto>(page, path);
    if (!['generating', 'ready'].includes(result.status)) throw new Error(`Expected a reviewable proposal, got ${result.status}`);
    return result.status;
  }, { timeout: 240_000, intervals: [1000, 2000] }).toBe('ready');
  await expect(page.locator('.principle-composer textarea')).toBeEnabled({ timeout: 240_000 });
  const notice = page.getByTestId('active-mutation-task-notice');
  if (await notice.isVisible()) await notice.getByRole('button', { name: '前往工作区审阅', exact: true }).click();
  await expect(page.locator('.collection-changes__review')).toBeVisible();
  return get<CaseChangeSetDto>(page, path);
}
async function accept(page: Page) {
  const response = page.waitForResponse(r => r.request().method() === 'POST' && /\/case-change-sets\/[^/]+\/apply$/.test(new URL(r.url()).pathname));
  await page.locator('.collection-changes__review').getByRole('button', { name: /一键采纳全部待审阅用例/ }).click();
  expect((await response).ok()).toBeTruthy();
  await expect(page.locator('.principle-composer textarea')).toBeEnabled({ timeout: 240_000 });
}
async function evidence(page: Page, info: TestInfo, values: unknown) {
  const path = info.outputPath('evidence.json');
  writeFileSync(path, JSON.stringify(values, null, 2));
  await info.attach('persisted-evidence', { path, contentType: 'application/json' });
  await page.screenshot({ path: info.outputPath('result.png'), fullPage: true });
}
test.beforeEach(async ({ page }) => {
  page.on('pageerror', error => { throw error; });
});


test('B1 previous query target survives assignment matching another case title', async ({ page }, info) => {
  const s = await setup(page);
  const query = await send(page, `查询用例 ${s.original[0].case_key}`);
  expect(query.assistant_message?.target_case_ids).toEqual([s.original[0].id]);
  const turn = await send(page, '把刚才查到的用例标题改为「库存不足禁止下单」，其他字段和其他用例不变', true, [s.original[0].id]);
  const change = await ready(page, turn);
  expect(change.items.map(i => i.ref)).toEqual([s.original[0].id]);
  expect(change.items[0].proposed_snapshot.title).toBe(s.original[2].title);
  await accept(page);
  const after = await s.read();
  expect(after.find(c => c.id === s.original[0].id)?.title).toBe(s.original[2].title);
  expect(after.find(c => c.id === s.original[1].id)).toEqual(s.original[1]);
  expect(after.find(c => c.id === s.original[2].id)).toEqual(s.original[2]);
  await evidence(page, info, { query, change, after });
});

test('B2 unknown identifier mixed with valid identifier never silently drops a target', async ({ page }, info) => {
  const s = await setup(page);
  const turn = await send(page, `将用例 ${s.original[0].case_key} 和 QA-NOT-EXIST-999 的优先级改为P2，其他字段不变`, false);
  expect(turn.action.job_id).toBeFalsy();
  expect(turn.assistant_message?.metadata.modification_confirmation).not.toBe(true);
  expect(turn.action.change_set_id).toBeFalsy();
  expect(turn.action.type).toBe('clarification');
  expect(await s.read()).toEqual(s.original);
  await evidence(page, info, { turn, after: await s.read() });
});

test('B3 completed deletion has no actionable stale warning and query uses surviving cases', async ({ page }, info) => {
  const s = await setup(page);
  const turn = await send(page, `删除用例 ${s.original[0].case_key}`);
  await page.getByRole('button', { name: '确认删除已选用例', exact: true }).click();
  await expect.poll(async () => (await s.read()).length).toBe(2);
  await page.reload();
  await expect(page.locator('.principle-composer textarea')).toBeEnabled();
  await expect(page.getByText('此结果基于历史用例版本，请重新检查后再生成变更。', { exact: true })).toHaveCount(0);
  const query = await send(page, '查询登录模块全部用例');
  expect(query.assistant_message?.target_case_ids).toEqual([s.original[1].id]);
  const next = await ready(page, await send(page, '把刚才查询到的用例优先级改为P2，其他字段不变'));
  expect(next.items.map(i => i.ref)).toEqual([s.original[1].id]);
  await accept(page);
  const after = await s.read();
  expect(after.find(c => c.id === s.original[2].id)).toEqual(s.original[2]);
  expect(after.find(c => c.id === s.original[1].id)?.priority).toBe('P2');
  await evidence(page, info, { turn, query, next, after });
});

test('B4 OR query preserves per-module priority pairing', async ({ page }, info) => {
  const s = await setup(page);
  const turns = [];
  for (const [content, ids] of [
    ['查询登录模块中优先级为P0的用例，或者订单模块中优先级为P1的用例，只查询不修改', [s.original[0].id, s.original[2].id]],
    ['查询登录模块中优先级为P1的用例，或者订单模块中优先级为P0的用例，只查询不修改', [s.original[1].id]],
  ] as [string, string[]][]) {
    const turn = await send(page, content);
    expect(turn.action.type).toBe('case_query');
    expect(new Set(turn.assistant_message?.target_case_ids)).toEqual(new Set(ids));
    expect(await s.read()).toEqual(s.original);
    turns.push(turn);
  }
  await evidence(page, info, { turns, after: await s.read() });
});

test('B5 discarded rewrite does not contaminate a new query-based target', async ({ page }, info) => {
  const s = await setup(page);
  const first = await ready(page, await send(page, `将用例 ${s.original[0].case_key} 的标题改为「不要保存的标题」，其他字段不变`));
  await page.getByRole('button', { name: '放弃当前任务', exact: true }).click();
  await expect(page.locator('.principle-composer textarea')).toBeEnabled();
  const query = await send(page, '查询订单模块的用例');
  expect(query.assistant_message?.target_case_ids).toEqual([s.original[2].id]);
  const next = await ready(page, await send(page, '将刚才查询到的用例优先级改为P2，其他字段不变'));
  expect(next.items.map(i => i.ref)).toEqual([s.original[2].id]);
  await accept(page);
  const after = await s.read();
  expect(after.find(c => c.id === s.original[0].id)).toEqual(s.original[0]);
  expect(after.find(c => c.id === s.original[1].id)).toEqual(s.original[1]);
  expect(after.find(c => c.id === s.original[2].id)?.priority).toBe('P2');
  await evidence(page, info, { first, query, next, after });
});

test('B6 literal query text matching a module name does not constrain the module', async ({ page }, info) => {
  const s = await setup(page, false, ['短信验证码校验', '用户名密码校验', '登录异常提示']);
  const turns = [];
  for (const [content, ids] of [
    ['查询标题包含「登录」的用例', [s.original[2].id]],
    ['查询标题包含登录的用例', [s.original[2].id]],
    ['查询订单模块标题包含「登录」的用例', [s.original[2].id]],
    ['查询登录模块标题包含「登录」的用例', []],
  ] as [string, string[]][]) {
    const turn = await send(page, content);
    expect(turn.action.type).toBe('case_query');
    expect(turn.assistant_message?.target_case_ids).toEqual(ids);
    expect(await s.read()).toEqual(s.original);
    turns.push(turn);
  }
  await evidence(page, info, { turns, after: await s.read() });
});


test('B7 query-result deletion shows thinking and prepares the frozen review', async ({ page }, info) => {
  const s = await setup(page);
  const query = await send(page, '查询登录模块的用例');
  expect(query.assistant_message?.target_case_ids).toHaveLength(2);
  const started = performance.now();
  const turn = await send(page, '删除刚才查询到的用例');
  const elapsedMs = performance.now() - started;
  expect(elapsedMs).toBeLessThan(180_000);
  expect(turn.action.type).toBe('change_set');
  expect(turn.operation_plan?.operations[0].requires_confirmation).toBe(true);
  expect(turn.operation_plan?.operations[0].payload.reason_codes).toContain('EXPLICIT_PREVIOUS_QUERY_DELETE');
  expect(new Set(turn.assistant_message?.target_case_ids)).toEqual(new Set(s.original.slice(0, 2).map(c => c.id)));
  await expect(page.getByRole('button', { name: '确认删除已选用例', exact: true })).toBeVisible();
  expect(await s.read()).toEqual(s.original);
  await page.getByRole('button', { name: '取消变更', exact: true }).click();
  await expect(page.locator('.principle-composer textarea')).toBeEnabled();
  expect(await s.read()).toEqual(s.original);
  await evidence(page, info, { query, turn, elapsedMs, after: await s.read() });
});


test('B8 multi-digit Chinese quantity cannot silently shrink a deletion scope', async ({ page }, info) => {
  const s = await setup(page);
  const query = await send(page, '查询登录模块的用例');
  expect(query.assistant_message?.target_case_ids).toHaveLength(2);
  const turn = await send(page, '删除刚才查询到的二十二条用例');
  expect(turn.action.type).toBe('clarification');
  expect(turn.action.change_set_id).toBeFalsy();
  expect(turn.action.job_id).toBeFalsy();
  await expect(page.getByRole('button', { name: '确认删除已选用例', exact: true })).toHaveCount(0);
  expect(await s.read()).toEqual(s.original);
  const corrected = await send(page, '删除刚才查询到的两条用例');
  expect(corrected.action.type).toBe('change_set');
  expect(new Set(corrected.assistant_message?.target_case_ids)).toEqual(new Set(s.original.slice(0, 2).map(c => c.id)));
  expect(await s.read()).toEqual(s.original);
  await page.getByRole('button', { name: '取消变更', exact: true }).click();
  await expect(page.locator('.principle-composer textarea')).toBeEnabled();
  expect(await s.read()).toEqual(s.original);
  await evidence(page, info, { query, turn, corrected, after: await s.read() });
});
