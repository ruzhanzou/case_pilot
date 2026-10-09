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
  for (const [index, title] of ['短信验证码校验', '用户名密码校验'].entries()) {
    const created = await page.request.post(`${api}/collections/${collection.id}/test-cases`, { data: {
      case_key: `QA-${stamp}-${index}`, title, module: '登录', priority: 'P1', case_type: '功能',
      preconditions: long && index === 0 ? [] : ['测试账号已注册'],
      steps: Array.from({ length: long && index === 0 ? 5 : 1 }, (_, n) => ({ action: `第${n + 1}步提交登录请求`, expected: `第${n + 1}步返回登录成功` })),
    } });
    expect(created.status()).toBe(201);
    original.push(await created.json());
  }
  await page.goto(`/workbench/collections/${collection.id}`);
  await expect(page.locator('.principle-composer textarea')).toBeEnabled({ timeout: 60_000 });
  return { collection, original, read: () => get<TestCaseDto[]>(page, `/collections/${collection.id}/test-cases`) };
}
async function send(page: Page, content: string): Promise<ConversationTurnDto> {
  const composer = page.locator('.principle-composer textarea');
  await expect(composer).toBeEnabled({ timeout: 240_000 });
  await composer.fill(content);
  const waiting = page.waitForResponse(r => r.request().method() === 'POST' && /\/(messages|resume)$/.test(new URL(r.url()).pathname), { timeout: 180_000 });
  await page.locator('.principle-composer button[type=submit]').click();
  const response = await waiting;
  expect(response.ok(), await response.text()).toBeTruthy();
  const turn = await response.json() as ConversationTurnDto;
  if (turn.assistant_message?.metadata.modification_confirmation === true) {
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

test('R1 content condition selects only matching cases before modification', async ({ page }, info) => {
  const s = await setup(page);
  let turn = await send(page, '把登录模块中涉及短信验证码的用例优先级改为P0');
  const initial = turn;
  if (turn.action.type === 'clarification') {
    expect(turn.action.job_id).toBeFalsy();
    expect(await s.read()).toEqual(s.original);
    turn = await send(page, `只修改用例 ${s.original[0].case_key}，优先级改为P0，其他用例不变`);
  }
  const change = await ready(page, turn);
  expect(change.items.map(item => item.ref)).toEqual([s.original[0].id]);
  expect(await s.read()).toEqual(s.original);
  await accept(page);
  const after = await s.read();
  expect(after.find(item => item.id === s.original[0].id)?.priority).toBe('P0');
  expect(after.find(item => item.id === s.original[1].id)).toEqual(s.original[1]);
  await evidence(page, info, { initial, turn, change, after });
});

test('R2 existing empty setup and five steps survive rewrite and save', async ({ page }, info) => {
  const s = await setup(page, true);
  const target = s.original[0];
  const turn = await send(page, `把用例 ${target.case_key} 的标题改为「长步骤登录验收」`);
  const change = await ready(page, turn);
  expect(change.items).toHaveLength(1);
  expect(change.items[0].proposed_snapshot.preconditions).toEqual([]);
  expect(change.items[0].proposed_snapshot.steps).toHaveLength(5);
  expect(await s.read()).toEqual(s.original);
  await accept(page);
  const after = await s.read();
  const saved = after.find(c => c.id === target.id)!;
  expect(saved.title).toBe('长步骤登录验收');
  expect(saved.preconditions).toEqual([]);
  expect(saved.steps.map(({ action, expected }) => ({ action, expected }))).toEqual(target.steps.map(({ action, expected }) => ({ action, expected })));
  expect(saved.revision_number).toBe(target.revision_number + 1);
  expect(after.find(c => c.id === s.original[1].id)).toEqual(s.original[1]);
  await page.reload();
  await expect(page.locator('.principle-composer textarea')).toBeEnabled();
  await evidence(page, info, { change, after });
});

test('R3 unresolved intermediate round preserves the previous proposal', async ({ page }, info) => {
  const s = await setup(page);
  const target = s.original[0];
  const first = await ready(page, await send(page, `把用例 ${target.case_key} 的标题改为「累计修改后的验证码校验」`));
  const invalid = await send(page, '修改「不存在的验收模块」模块，优先级改为P0');
  expect(invalid.action.job_id).toBeFalsy();
  const turn = await send(page, `修改用例 ${target.case_key}，优先级改为P0，保留上一版标题`);
  const change = await ready(page, turn);
  const item = change.items.find(i => i.ref === target.id)!;
  expect(item.proposed_snapshot.title).toBe('累计修改后的验证码校验');
  expect(item.proposed_snapshot.priority).toBe('P0');
  expect(item.field_diff.map(d => d.field)).toEqual(expect.arrayContaining(['title', 'priority']));
  expect(await s.read()).toEqual(s.original);
  await accept(page);
  expect((await s.read()).find(c => c.id === target.id)?.title).toBe('累计修改后的验证码校验');
  await evidence(page, info, { first, invalid, change, after: await s.read() });
});

test('R4 compound assignment also performs the semantic step rewrite', async ({ page }, info) => {
  const s = await setup(page);
  const target = s.original[0];
  const turn = await send(page, `把用例 ${target.case_key} 的标题改为「弱网登录校验」，并补充断网后重试的验证：断网时点击重试，恢复网络后再次登录成功。`);
  const change = await ready(page, turn);
  const proposed = change.items.find(i => i.ref === target.id)!.proposed_snapshot;
  expect(proposed.title).toBe('弱网登录校验');
  expect(await s.read()).toEqual(s.original);
  await accept(page);
  // The real planner may split a compound instruction into dependent tasks.
  // Review every resulting proposal, then verify that the whole request closed.
  let state = await get<ConversationDto>(page, `/conversations/${turn.conversation_id}`);
  for (let round = 0; round < 8; round += 1) {
    const pending = state.operation_history?.find(op => ['awaiting_confirmation', 'awaiting_target'].includes(op.status));
    if (!pending) break;
    if (!pending.related_change_set_id) {
      const confirming = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/resume'));
      await page.getByRole('button', { name: '确认修改并生成建议', exact: true }).last().click();
      const response = await confirming;
      expect(response.ok()).toBeTruthy();
      await ready(page, await response.json());
      await accept(page);
      state = await get<ConversationDto>(page, `/conversations/${turn.conversation_id}`);
      continue;
    }
    const next = await get<CaseChangeSetDto>(page, `/case-change-sets/${pending.related_change_set_id}`);
    expect(next.status).toBe('ready');
    const notice = page.getByTestId('active-mutation-task-notice');
    await expect(notice).toBeVisible();
    await notice.getByRole('button', { name: '前往工作区审阅', exact: true }).click();
    await accept(page);
    state = await get<ConversationDto>(page, `/conversations/${turn.conversation_id}`);
  }
  expect(state.operation_history?.filter(op => ['queued', 'running', 'awaiting_confirmation', 'failed', 'awaiting_target'].includes(op.status))).toEqual([]);
  const finalTarget = (await s.read()).find(c => c.id === target.id)!;
  expect(finalTarget.title).toBe('弱网登录校验');
  expect(JSON.stringify(finalTarget.steps)).toContain('重试');
  expect(JSON.stringify(finalTarget.steps)).toMatch(/断网|网络/);
  expect((await s.read()).find(c => c.id === s.original[1].id)).toEqual(s.original[1]);
  await evidence(page, info, { change, state, after: await s.read() });
});

test('R5 unchecked stale case does not block applying the selected case', async ({ page }, info) => {
  const s = await setup(page);
  const turn = await send(page, '把登录模块全部用例的优先级改为P0');
  const change = await ready(page, turn);
  expect(change.items).toHaveLength(2);
  const stale = s.original[1];
  const manual = await page.request.patch(`${api}/test-cases/${stale.id}`, { data: { ...stale, base_revision_id: stale.current_revision_id, title: '人工编辑保留标题' } });
  expect(manual.ok(), await manual.text()).toBeTruthy();
  const edited = await manual.json();
  const row = page.locator('.collection-changes__items > details').filter({ hasText: stale.case_key });
  await row.evaluate(el => el.setAttribute('open', ''));
  await row.getByRole('checkbox').uncheck();
  const applying = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/apply'));
  await page.getByRole('button', { name: '应用已选修改', exact: true }).click();
  const response = await applying;
  expect(response.ok(), await response.text()).toBeTruthy();
  const after = await s.read();
  expect(after.find(c => c.id === s.original[0].id)?.priority).toBe('P0');
  expect(after.find(c => c.id === stale.id)).toEqual(edited);
  await page.reload();
  await expect(page.locator('.principle-composer textarea')).toBeEnabled();
  await evidence(page, info, { change, after });
});

test('R6 unchanged subset retains cumulative pending results and status', async ({ page }, info) => {
  const s = await setup(page);
  await ready(page, await send(page, `用例 ${s.original[0].case_key}标题改为「待采纳的累计标题」`));
  const turn = await send(page, `用例 ${s.original[1].case_key}标题改为「${s.original[1].title}」`);
  const change = await ready(page, turn);
  expect(change.items).toHaveLength(2);
  const state = await get<ConversationDto>(page, `/conversations/${turn.conversation_id}`);
  const operation = state.operation_history?.find(op => op.related_change_set_id === change.id);
  expect(operation?.status).toBe('awaiting_confirmation');
  expect(operation?.result.no_changes).toBe(false);
  expect(operation?.result.items).toHaveLength(2);
  expect(await s.read()).toEqual(s.original);
  await accept(page);
  const after = await s.read();
  expect(after.find(c => c.id === s.original[0].id)?.title).toBe('待采纳的累计标题');
  expect(after.find(c => c.id === s.original[1].id)).toEqual(s.original[1]);
  await evidence(page, info, { change, operation, after });
});

test('R7 query body-only evidence then modify the previous results', async ({ page }, info) => {
  const s = await setup(page);
  const originals: TestCaseDto[] = [];
  for (const [index, item] of s.original.entries()) {
    const response = await page.request.patch(`${api}/test-cases/${item.id}`, { data: {
      ...item, base_revision_id: item.current_revision_id, title: `登录校验${index + 1}`,
      steps: [{ action: index === 0 ? '输入短信验证码并提交' : '输入密码并提交', expected: '登录成功' }],
    } });
    expect(response.ok()).toBeTruthy();
    originals.push(await response.json());
  }
  await page.reload();
  const query = await send(page, '查询登录模块中步骤包含短信验证码的用例');
  expect(query.action.type).toBe('case_query');
  expect(query.assistant_message?.target_case_ids).toEqual([originals[0].id]);
  const turn = await send(page, '把刚才查询到的用例优先级改为P0，其他内容保持不变');
  const change = await ready(page, turn);
  expect(change.items.map(item => item.ref)).toEqual([originals[0].id]);
  expect(await s.read()).toEqual(originals);
  await accept(page);
  const after = await s.read();
  expect(after.find(item => item.id === originals[0].id)?.priority).toBe('P0');
  expect(after.find(item => item.id === originals[1].id)).toEqual(originals[1]);
  await evidence(page, info, { query, change, after });
});

test('R8 priority predicates survive semantic scope extraction', async ({ page }, info) => {
  const s = await setup(page);
  const target = s.original[0];
  const edited = await page.request.patch(`${api}/test-cases/${target.id}`, { data: {
    ...target, base_revision_id: target.current_revision_id, priority: 'P0',
  } });
  expect(edited.ok()).toBeTruthy();
  await page.reload();
  const query = await send(page, '查询登录模块优先级为P1的用例');
  expect(query.action.type).toBe('case_query');
  expect(query.assistant_message?.target_case_ids).toEqual([s.original[1].id]);
  const negative = await send(page, '查询登录模块中优先级不是P0的用例');
  expect(negative.action.type).toBe('case_query');
  expect(negative.assistant_message?.target_case_ids).toEqual([s.original[1].id]);
  await evidence(page, info, { query, negative, after: await s.read() });
});
