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

async function confirm(page: Page) {
  const waiting = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/resume'), { timeout: 180_000 });
  await page.getByRole('button', { name: '确认修改并生成建议', exact: true }).last().click();
  const response = await waiting;
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json() as Promise<ConversationTurnDto>;
}

test('C1 explicit edit waits for confirmation, survives reload and saves only after adoption', async ({ page }, info) => {
  const s = await setup(page, true);
  const first = await send(page, `把用例 ${s.original[0].case_key} 的标题改为「确认后的登录校验」，其他字段保持不变`);
  expect(first.assistant_message?.metadata.modification_confirmation).toBe(true);
  expect(first.action.job_id).toBeFalsy();
  expect(first.action.change_set_id).toBeFalsy();
  expect(await s.read()).toEqual(s.original);
  await expect(page.getByRole('button', { name: '确认修改并生成建议', exact: true })).toBeEnabled();
  await page.screenshot({ path: info.outputPath('before-confirmation.png'), fullPage: true });
  await page.reload();
  const confirmed = await confirm(page);
  const change = await ready(page, confirmed);
  expect(await s.read()).toEqual(s.original);
  await accept(page);
  const after = await s.read();
  expect(after.find(c => c.id === s.original[0].id)?.title).toBe('确认后的登录校验');
  expect(after.find(c => c.id === s.original[0].id)?.steps).toEqual(s.original[0].steps);
  expect(after.find(c => c.id === s.original[1].id)).toEqual(s.original[1]);
  await page.reload();
  expect(await s.read()).toEqual(after);
  await evidence(page, info, { first, confirmed, change, after });
});

test('C2 clarification changes scope and requires a fresh confirmation', async ({ page }, info) => {
  const s = await setup(page);
  const first = await send(page, '重写登录模块的用例');
  expect(first.action.job_id).toBeFalsy();
  expect(first.action.change_set_id).toBeFalsy();
  await page.getByRole('button', { name: '补充信息', exact: true }).last().click();
  const revised = await send(page, `仅修改用例 ${s.original[0].case_key}，标题改为「补充确认后的标题」，不要修改其他用例，步骤保持不变`);
  expect(revised.assistant_message?.metadata.modification_confirmation).toBe(true);
  expect(revised.assistant_message?.target_case_ids).toEqual([s.original[0].id]);
  expect(revised.action.job_id).toBeFalsy();
  expect(revised.operation_plan?.operations[0].id).toBe(first.operation_plan?.operations[0].id);
  expect(await s.read()).toEqual(s.original);
  await ready(page, await confirm(page));
  await accept(page);
  const after = await s.read();
  expect(after.find(c => c.id === s.original[0].id)?.title).toBe('补充确认后的标题');
  expect(after.find(c => c.id === s.original[1].id)).toEqual(s.original[1]);
  await evidence(page, info, { first, revised, after });
});

test('C3 ending a confirmation creates no changes and releases the conversation', async ({ page }, info) => {
  const s = await setup(page);
  const first = await send(page, `将用例 ${s.original[0].case_key} 的优先级改为P0`);
  expect(first.assistant_message?.metadata.modification_confirmation).toBe(true);
  await page.getByRole('button', { name: '结束任务', exact: true }).last().click();
  await expect(page.getByRole('button', { name: '确认修改并生成建议', exact: true })).toHaveCount(0);
  const next = await send(page, '你好');
  expect(next.intent).toBe('SMALL_TALK');
  expect(await s.read()).toEqual(s.original);
  const repeat = await page.request.post(`${api}/conversation-operations/${first.operation_plan!.operations[0].id}/resume`, { data: { confirm_modification: true } });
  expect(repeat.status()).toBe(409);
  await evidence(page, info, { first, next, cases: await s.read() });
});
