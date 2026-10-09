import { writeFileSync } from 'node:fs';
import { expect, test, type Page, type TestInfo } from '@playwright/test';
import type { CaseChangeSetDto, ConversationDto, ConversationTurnDto, TestCaseDto } from '../lib/casepilot-api';

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
async function setup(page: Page, long = false) {
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  const login = await page.request.post(`${api}/auth/login`, { data: { email: 'demo@casepilot.local', password: 'CasePilot123!' } });
  expect(login.ok()).toBeTruthy();
  const account = await login.json();
  const stamp = Date.now();
  const response = await page.request.post(`${api}/spaces/${account.spaces[0].id}/collections`, { data: { name: `修改回归验收-${stamp}` } });
  expect(response.ok()).toBeTruthy();
  const collection = await response.json() as { id: string };
  const original: TestCaseDto[] = [];
  for (const [index, title] of ['短信验证码校验', '用户名密码校验', '库存不足禁止下单'].entries()) {
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
async function send(page: Page, content: string, confirm = true): Promise<ConversationTurnDto> {
  const composer = page.locator('.principle-composer textarea');
  await expect(composer).toBeEnabled({ timeout: 240_000 });
  await composer.fill(content);
  const waiting = page.waitForResponse(r => r.request().method() === 'POST' && /\/(messages|resume)$/.test(new URL(r.url()).pathname), { timeout: 180_000 });
  await page.locator('.principle-composer button[type=submit]').click();
  await expect(page.getByTestId('scope-thinking')).toBeVisible();
  await page.getByTestId('scope-thinking').screenshot({ path: test.info().outputPath('thinking.png') });
  const response = await waiting;
  await expect(page.getByTestId('scope-thinking')).toHaveCount(0);
  expect(response.ok(), await response.text()).toBeTruthy();
  const turn = await response.json() as ConversationTurnDto;
  writeFileSync(test.info().outputPath(`turn-${Date.now()}.json`), JSON.stringify({ content, turn }, null, 2));
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
    if (result.status === 'failed') throw new Error('Rewrite worker failed');
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

test('Q1 exact query scope, exclusion and empty result never mutate', async ({ page }, info) => {
  const s = await setup(page);
  const queries: [string, string[]][] = [
    [`查询用例 ${s.original[1].case_key}`, [s.original[1].id]],
    ['查询登录模块优先级为P0的用例', [s.original[0].id]],
    ['查询登录模块优先级不是P0的用例', [s.original[1].id]],
    ['查询标题包含「库存不足」的用例', [s.original[2].id]],
    ['查询标题包含「火星支付XYZ」的用例', []],
  ];
  for (const [content, ids] of queries) {
    await test.step(content, async () => {
      const turn = await send(page, content);
      expect(turn.intent).toBe('CASE_QUERY'); expect(turn.action.type).toBe('case_query');
      expect(new Set(turn.assistant_message?.target_case_ids)).toEqual(new Set(ids));
      expect(await s.read()).toEqual(s.original);
    });
  }
  await page.reload(); await expect(page.locator('.principle-composer textarea')).toBeEnabled();
  await evidence(page, info, { after: await s.read() });
});

test('N1 questions and negated deletion cannot start writes', async ({ page }, info) => {
  const s = await setup(page);
  for (const content of ['如何删除用例？请解释操作方法，不执行删除。', '不要删除登录模块的用例，只查询登录模块有哪些用例']) {
    const turn = await send(page, content);
    expect(['CASE_QUERY', 'KNOWLEDGE_QA']).toContain(turn.intent);
    expect(turn.action.change_set_id).toBeFalsy();
    await expect(page.locator('.principle-composer textarea')).toBeEnabled({ timeout: 240000 });
    expect(await s.read()).toEqual(s.original);
    const state = await get<ConversationDto>(page, `/conversations/${turn.conversation_id}`);
    expect(state.operation_history?.filter(o => ['CASE_DELETE','CASE_MODIFY','CASE_GENERATE'].includes(o.intent))).toHaveLength(0);
  }
  await evidence(page, info, { after: await s.read() });
});

test('M1 excluded case remains intact in natural language batch edit', async ({ page }, info) => {
  const s = await setup(page);
  const turn = await send(page, `将登录模块的用例优先级改为P2，但排除用例 ${s.original[0].case_key}，其他字段和订单模块不变`);
  const change = await ready(page, turn);
  expect(change.items.map(i => i.ref)).toEqual([s.original[1].id]); expect(await s.read()).toEqual(s.original);
  await accept(page);
  const after = await s.read();
  for (const old of s.original) {
    const current = after.find(c => c.id === old.id)!;
    if (old.id !== s.original[1].id) expect(current).toEqual(old);
    else { expect(current.priority).toBe('P2'); expect(current.title).toBe(old.title); expect(current.steps).toEqual(old.steps); }
  }
  await evidence(page, info, { change, after });
});

test('M2 revise scope during confirmation before any worker starts', async ({ page }, info) => {
  const s = await setup(page);
  const preview = await send(page, '把登录模块所有用例优先级改为P2，其他字段不变', false);
  expect(preview.assistant_message?.metadata.modification_confirmation).toBe(true); expect(preview.action.job_id).toBeFalsy();
  const turn = await send(page, `范围缩小为仅用例 ${s.original[1].case_key}，优先级改为P2，其他用例及字段不变`);
  const change = await ready(page, turn);
  expect(change.items.map(i => i.ref)).toEqual([s.original[1].id]); expect(await s.read()).toEqual(s.original);
  await accept(page); const after = await s.read();
  expect(after.find(c => c.id === s.original[0].id)).toEqual(s.original[0]);
  expect(after.find(c => c.id === s.original[1].id)?.priority).toBe('P2');
  expect(after.find(c => c.id === s.original[2].id)).toEqual(s.original[2]);
  await evidence(page, info, { preview, change, after });
});

test('S1 query during pending rewrite preserves proposal and followup target', async ({ page }, info) => {
  const s = await setup(page); const target = s.original[0];
  const first = await ready(page, await send(page, `将用例 ${target.case_key} 标题改为「待采纳的短信验证」，其他字段不变`));
  const query = await send(page, '查询订单模块的用例，只查询不修改');
  expect(query.assistant_message?.target_case_ids).toEqual([s.original[2].id]);
  expect((await get<CaseChangeSetDto>(page, `/case-change-sets/${first.id}`)).status).toBe('ready');
  const turn = await send(page, `继续修改刚才的建议：用例 ${target.case_key} 优先级改为P2，保留上一版标题，订单用例不变`);
  const next = await ready(page, turn);
  expect(next.items.map(i => i.ref)).toEqual([target.id]);
  expect(next.items[0].proposed_snapshot.title).toBe('待采纳的短信验证'); expect(next.items[0].proposed_snapshot.priority).toBe('P2');
  expect(await s.read()).toEqual(s.original); await accept(page);
  const after = await s.read(); expect(after.find(c => c.id === s.original[2].id)).toEqual(s.original[2]);
  await evidence(page, info, { first, query, next, after });
});

test('D1 empty query cannot fall back to previous nonempty result for deletion', async ({ page }, info) => {
  const s = await setup(page);
  const found = await send(page, '查询登录模块的用例'); expect(found.assistant_message?.target_case_ids).toHaveLength(2);
  const empty = await send(page, '查询标题包含「火星支付XYZ」的用例'); expect(empty.assistant_message?.target_case_ids).toHaveLength(0);
  const turn = await send(page, '删除刚才查询到的用例');
  expect(turn.action.job_id).toBeFalsy(); expect(turn.action.change_set_id).toBeFalsy(); expect(await s.read()).toEqual(s.original);
  await expect(page.getByRole('button', { name: '确认删除已选用例', exact: true })).toHaveCount(0);
  await evidence(page, info, { found, empty, turn, after: await s.read() });
});

test('D2 delete query results supports cancel, retry and durable exact scope', async ({ page }, info) => {
  const s = await setup(page);
  await send(page, '查询登录模块的用例');
  const first = await send(page, '删除刚才查询到的用例');
  expect(await s.read()).toEqual(s.original);
  await page.getByRole('button', { name: '取消变更', exact: true }).click();
  await expect(page.locator('.principle-composer textarea')).toBeEnabled(); expect(await s.read()).toEqual(s.original);
  const second = await send(page, '删除刚才查询到的用例'); expect(await s.read()).toEqual(s.original);
  await page.getByRole('button', { name: '确认删除已选用例', exact: true }).click();
  await expect.poll(async () => (await s.read()).length).toBe(1);
  expect(await s.read()).toEqual([s.original[2]]);
  await page.reload(); await expect(page.locator('.principle-composer textarea')).toBeEnabled();
  expect(await s.read()).toEqual([s.original[2]]);
  await evidence(page, info, { first, second, after: await s.read() });
});

test('N2 vague rewrite clarifies then concrete followup can be discarded', async ({ page }, info) => {
  const s = await setup(page);
  const vague = await send(page, '重写登录模块的用例', false);
  expect(vague.action.job_id).toBeFalsy(); expect(vague.action.change_set_id).toBeFalsy();
  expect(vague.action.type).toBe('clarification'); expect(await s.read()).toEqual(s.original);
  const turn = await send(page, `仅把用例 ${s.original[1].case_key} 的标题改为「澄清后登录校验」，其他字段和用例不变`);
  const change = await ready(page, turn); expect(change.items.map(i => i.ref)).toEqual([s.original[1].id]);
  expect(change.items[0].proposed_snapshot.title).toBe('澄清后登录校验');
  await page.getByRole('button', { name: '放弃当前任务', exact: true }).click();
  await expect(page.locator('.principle-composer textarea')).toBeEnabled(); expect(await s.read()).toEqual(s.original);
  await evidence(page, info, { vague, change, after: await s.read() });
});

test('S2 stop a running rewrite after reload then accept new dialogue', async ({ page }, info) => {
  const s = await setup(page);
  const turn = await send(page, `重写用例 ${s.original[1].case_key} 的测试步骤：明确输入正确用户名和密码、提交请求、检查登录成功，其他字段不变`);
  expect(turn.action.job_id).toBeTruthy();
  const composer = page.locator('.principle-composer textarea'); await expect(composer).toBeDisabled();
  const blocked = await page.request.post(`${api}/conversations/${turn.conversation_id}/messages`, { data: { content: '查询用例' } });
  expect(blocked.status()).toBe(409);
  await page.reload(); await page.getByRole('button', { name: '结束任务', exact: true }).click();
  await expect(composer).toBeEnabled({ timeout: 60000 }); expect(await s.read()).toEqual(s.original);
  const query = await send(page, '查询订单模块的用例'); expect(query.assistant_message?.target_case_ids).toEqual([s.original[2].id]);
  await page.reload(); await expect(composer).toBeEnabled();
  const state = await get<ConversationDto>(page, `/conversations/${turn.conversation_id}`);
  expect(state.operation_history?.find(o => o.related_job_id === turn.action.job_id)?.status).toBe('cancelled');
  expect(state.context.active_mutation_task_id).toBeNull();
  const deletion = await send(page, `删除用例 ${s.original[2].case_key}`);
  expect(deletion.action.change_set_id).toBeTruthy();
  await page.getByRole('button', { name: '取消变更', exact: true }).click();
  await expect(composer).toBeEnabled();
  expect(await s.read()).toEqual(s.original); await evidence(page, info, { turn, query, deletion, state, after: await s.read() });
});

test('D3 explicit exclusion in deletion binds only remaining cases', async ({ page }, info) => {
  const s = await setup(page);
  const turn = await send(page, `删除登录模块的用例，但排除用例 ${s.original[0].case_key}，订单模块保持不变`);
  expect(turn.action.change_set_id).toBeTruthy();
  const change = await get<CaseChangeSetDto>(page, `/case-change-sets/${turn.action.change_set_id}`);
  expect(change.items.map(i => i.ref)).toEqual([s.original[1].id]); expect(await s.read()).toEqual(s.original);
  await page.getByRole('button', { name: '取消变更', exact: true }).click();
  await expect(page.locator('.principle-composer textarea')).toBeEnabled(); expect(await s.read()).toEqual(s.original);
  await evidence(page, info, { turn, change, after: await s.read() });
});

test('M3 priority-like title text is an assignment not a source filter', async ({ page }, info) => {
  const s = await setup(page); const target = s.original[1];
  const turn = await send(page, `将用例 ${target.case_key} 的标题改为「P0登录验收」，其他字段和其他用例保持不变`);
  const change = await ready(page, turn); expect(change.items.map(i => i.ref)).toEqual([target.id]);
  expect(change.items[0].proposed_snapshot.title).toBe('P0登录验收'); expect(change.items[0].proposed_snapshot.priority).toBe('P1');
  expect(await s.read()).toEqual(s.original); await accept(page);
  const after = await s.read();
  const saved = after.find(c => c.id === target.id)!;
  expect(saved.title).toBe('P0登录验收'); expect(saved.priority).toBe('P1');
  expect(saved.revision_number).toBe(target.revision_number + 1);
  expect({ ...saved, title: target.title, revision_number: target.revision_number, current_revision_id: target.current_revision_id }).toEqual(target);
  for (const other of s.original.filter(c => c.id !== target.id)) expect(after.find(c => c.id === other.id)).toEqual(other);
  await evidence(page, info, { change, after });
});
