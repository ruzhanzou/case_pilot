/* eslint-disable @typescript-eslint/no-explicit-any -- Real acceptance journals preserve full heterogeneous responses. */
import { test, expect, type Page } from '@playwright/test';
import { readFileSync, writeFileSync } from 'node:fs';

test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1', 'Requires real local services and model');
test.use({ viewport: { width: 1600, height: 1000 }, trace: 'on', video: 'retain-on-failure' });
test.setTimeout(900_000);
const api = `${process.env.CASEPILOT_E2E_API_URL ?? "http://localhost:8000"}/api/v1`;
const suite = JSON.parse(readFileSync(new URL('../../../docs/evaluations/casepilot-natural-language-eval-2026-10-09.json', import.meta.url), 'utf8'));
let journal: any;
// Redirect transport to an isolated real API when load tests occupy the main worker.
// No response is mocked; streaming and persistence stay with the real services.
test.beforeEach(async ({page}) => {
  const target = process.env.CASEPILOT_BROWSER_API_OVERRIDE;
  if (target) await page.route('http://localhost:8000/api/v1/**', route =>
    route.continue({url: route.request().url().replace('http://localhost:8000', target)}));
});

test.beforeEach(() => { journal = { turns: [], timings: [], startedAt: new Date().toISOString() }; });
test.afterEach(async ({ page }, info) => {
  journal.status = info.status;
  journal.errors = info.errors.map(error => error.message);
  if (journal.collection) {
    const response = await page.request.get(`${api}/collections/${journal.collection.id}/test-cases`);
    if (response.ok()) journal.final = await response.json();
  }
  writeFileSync(info.outputPath('evidence.json'), JSON.stringify(journal, null, 2));
  if (!page.isClosed()) await page.screenshot({ path: info.outputPath('final.png'), fullPage: true });
});
async function get(page: Page, path: string) {
  const response = await page.request.get(api + path); expect(response.ok()).toBeTruthy(); return response.json();
}
async function setup(page: Page, long = false, empty = false) {
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  const login = await page.request.post(`${api}/auth/register`, { data: { email: `nl-${Date.now()}-${Math.random().toString(36).slice(2)}@casepilot.test`, display_name: '自然语言验收', password: 'CasePilot123!' } });
  expect(login.ok()).toBeTruthy(); const account = await login.json();
  const collection = await page.request.post(`${api}/spaces/${account.spaces[0].id}/collections`, { data: { name: `NL评测-${test.info().title.split(' ')[0]}-${Date.now()}` } });
  expect(collection.ok()).toBeTruthy(); journal.collection = await collection.json();
  journal.keyMap = Object.fromEntries(suite.fixture_definitions.F.cases.map((c: any) => [c.case_key, `${c.case_key}-${Date.now()}`]));
  for (const source of empty ? [] : suite.fixture_definitions.F.cases) {
    const item = { ...source }; delete item.alias;
    if (long && item.case_key === 'TC-LOGIN-01') {
      item.preconditions = [];
      item.steps = Array.from({ length: 100 }, (_, i) => ({ action: `执行第${i + 1}项登录检查`, expected: `第${i + 1}项检查记录可查询` }));
    }
    item.case_key = journal.keyMap[source.case_key];
    const response = await page.request.post(`${api}/collections/${journal.collection.id}/test-cases`, { data: { ...item, case_type: '功能' } });
    expect(response.status()).toBe(201);
  }
  journal.original = await get(page, `/collections/${journal.collection.id}/test-cases`);
  await page.goto(`/workbench/collections/${journal.collection.id}`);
  await expect(page.locator('.principle-composer textarea')).toBeEnabled({ timeout: 60000 });
  return { read: () => get(page, `/collections/${journal.collection.id}/test-cases`), byKey: (key: string) => journal.original.find((c: any) => c.case_key === journal.keyMap[key]) };
}
async function send(page: Page, content: string, confirm = true) {
  for (const [alias, key] of Object.entries(journal.keyMap ?? {})) content = content.replaceAll(alias, String(key));
  const input = page.locator('.principle-composer textarea'); await expect(input).toBeEnabled({ timeout: 480000 });
  await input.fill(content); const started = Date.now();
  const pending = page.waitForResponse(r => r.request().method() === 'POST' && /\/(messages|resume)$/.test(new URL(r.url()).pathname), { timeout: 180000 });
  await page.locator('.principle-composer button[type=submit]').click();
  const response = await pending; expect(response.ok(), await response.text()).toBeTruthy();
  let turn = await response.json(); journal.turns.push({ content, response: turn });
  journal.timings.push({ kind: 'message_response', ms: Date.now() - started });
  if (confirm && turn.assistant_message?.metadata.modification_confirmation) {
    expect(turn.action.job_id).toBeFalsy();
    const pending = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/resume'), { timeout: 180000 });
    await page.getByRole('button', { name: '确认修改并生成建议', exact: true }).last().click();
    const response = await pending; expect(response.ok()).toBeTruthy(); turn = await response.json(); journal.turns.push({ confirmation: turn });
  }
  return turn;
}
async function ready(page: Page, turn: any) {
  expect(turn.action.change_set_id, JSON.stringify(turn.action)).toBeTruthy(); const start = Date.now();
  const path = `/case-change-sets/${turn.action.change_set_id}`;
  await expect.poll(async () => { const c = await get(page, path); if (c.status === 'failed') throw new Error(JSON.stringify(c)); return c.status; }, { timeout: 480000 }).toBe('ready');
  journal.timings.push({ kind: 'proposal_wait_after_response', ms: Date.now() - start });
  await expect(page.locator('.principle-composer textarea')).toBeEnabled({ timeout: 60000 });
  const notice = page.getByTestId('active-mutation-task-notice');
  if (await notice.isVisible()) await notice.getByRole('button', { name: '前往工作区审阅', exact: true }).click();
  const change = await get(page, path); (journal.proposals ??= []).push(change); return change;
}
async function apply(page: Page, partial = false) {
  const start = Date.now();
  const pending = page.waitForResponse(r => r.request().method() === 'POST' && /\/case-change-sets\/[^/]+\/apply$/.test(new URL(r.url()).pathname));
  const review = page.locator('.collection-changes__review');
  await review.getByRole('button', { name: partial ? '应用已选修改' : /一键采纳全部待审阅用例/ }).click();
  const response = await pending; expect(response.ok(), await response.text()).toBeTruthy();
  journal.timings.push({ kind: 'apply_response', ms: Date.now() - start });
  await expect(page.locator('.principle-composer textarea')).toBeEnabled({ timeout: 60000 });
}
function unchangedExcept(before: any, after: any, fields: string[]) {
  const ignored = new Set([...fields, 'revision_number', 'current_revision_id']);
  for (const key of Object.keys(before)) if (!ignored.has(key)) expect(after[key], key).toEqual(before[key]);
  expect(after.revision_number).toBe(before.revision_number + 1);
}

test('NL-EDT-07 existing hundred-step asset survives title-only rewrite', async ({ page }) => {
  const s = await setup(page, true); const old = s.byKey('TC-LOGIN-01');
  const c = await ready(page, await send(page, '只修改 TC-LOGIN-01 标题为“百步兼容用例”。'));
  expect(c.items).toHaveLength(1); expect(c.items[0].proposed_snapshot.steps).toHaveLength(100);
  expect(await s.read()).toEqual(journal.original); await apply(page); await page.reload();
  const after = await s.read(); const changed = after.find((v: any) => v.id === old.id);
  expect(changed.title).toBe('百步兼容用例'); unchangedExcept(old, changed, ['title']);
  expect(after.filter((v: any) => v.id !== old.id)).toEqual(journal.original.filter((v: any) => v.id !== old.id));
});

for (const [id, prompt] of [
  ['NL-SCP-06', '把 TC-NOT-999 改为P0。'],
  ['NL-SCP-07', '把 TC-LOGIN-01 和 TC-NOT-999 都改成P0。'],
  ['NL-EDT-09', '把 TC-LOGIN-01 优先级改成P9。'],
]) test(`${id} invalid request cannot silently mutate`, async ({ page }) => {
  const s = await setup(page); const turn = await send(page, prompt, false);
  expect(turn.action.job_id).toBeFalsy(); expect(turn.action.change_set_id).toBeFalsy();
  expect(turn.action.type).toBe('clarification'); expect(await s.read()).toEqual(journal.original);
});

test('NL-SCP-04 parent module includes descendants only', async ({ page }) => {
  const s = await setup(page);
  const c = await ready(page, await send(page, '把登录模块及所有子模块的用例优先级改为P2。'));
  const ids = journal.original.filter((v: any) => v.module.startsWith('登录/')).map((v: any) => v.id);
  expect(new Set(c.items.map((i: any) => i.ref))).toEqual(new Set(ids));
  expect(await s.read()).toEqual(journal.original); await apply(page);
  for (const v of await s.read()) { const old = journal.original.find((x: any) => x.id === v.id); if (ids.includes(v.id)) { expect(v.priority).toBe('P2'); unchangedExcept(old, v, ['priority']); } else expect(v).toEqual(old); }
});

test('NL-MUL-08 latest value replaces prior pending value', async ({ page }) => {
  const s = await setup(page); const old = s.byKey('TC-LOGIN-01');
  await ready(page, await send(page, '把 TC-LOGIN-01 优先级改P0。'));
  const c = await ready(page, await send(page, '刚才说错了，改P2，标题不要动。'));
  expect(c.items).toHaveLength(1); expect(c.items[0].proposed_snapshot.priority).toBe('P2');
  expect(await s.read()).toEqual(journal.original); await apply(page);
  const changed = (await s.read()).find((v: any) => v.id === old.id); expect(changed.priority).toBe('P2'); unchangedExcept(old, changed, ['priority']);
});

test('NL-REV-02 only selected field is persisted', async ({ page }) => {
  const s = await setup(page); const old = s.byKey('TC-LOGIN-01');
  await ready(page, await send(page, '把 TC-LOGIN-01 标题改成“字段采纳”并把优先级改P0。'));
  const review = page.locator('.collection-changes__review');
  const row = review.locator('.collection-changes__items > details'); await row.evaluate(el => el.setAttribute('open', ''));
  await row.getByRole('checkbox', { name: '优先级', exact: true }).uncheck();
  await apply(page, true); const changed = (await s.read()).find((v: any) => v.id === old.id);
  expect(changed.title).toBe('字段采纳'); expect(changed.priority).toBe('P1'); unchangedExcept(old, changed, ['title']);
});

test('NL-SEC-04 script-like title remains inert text', async ({ page }) => {
  const s = await setup(page); const dialogs: string[] = [];
  page.on('dialog', async dialog => { dialogs.push(dialog.message()); await dialog.dismiss(); });
  const title = '<img src=x onerror=alert(1)>';
  await ready(page, await send(page, `把 TC-LOGIN-01 标题改为「${title}」。`));
  expect(await page.locator('.collection-changes__review').locator('img[src="x"]').count()).toBe(0);
  await apply(page); await page.reload(); await expect(page.locator('.principle-composer textarea')).toBeEnabled();
  expect((await s.read()).find((v: any) => v.id === s.byKey('TC-LOGIN-01').id).title).toBe(title);
  for (const view of ['用例列表', '用例脑图']) {
    await page.getByRole('button', { name: view, exact: true }).click();
    await expect(page.locator('img[src="x"]')).toHaveCount(0);
  }
  await expect(page.locator('img[src="x"]')).toHaveCount(0); expect(dialogs).toEqual([]);
});

test('NL-GEN-01 six synthetic rules generate six candidates before incorporation', async ({ page }) => {
  const s = await setup(page, false, true);
  const prompt = '为账号登录生成恰好6条用例，以下R1至R6每条规则恰好1条，标题保留R编号，不扩充规则，先提供测试规划供确认，不直接纳入正式集合：\n' + suite.fixture_definitions['R-LOGIN'].rules.join('\n');
  const turn = await send(page, prompt); journal.conversationId = turn.conversation_id;
  const state = () => get(page, `/conversations/${turn.conversation_id}`);
  await expect(page.getByRole('button', { name: '确认规划并生成用例', exact: true })).toBeEnabled({ timeout: 480000 });
  journal.planning = await state(); expect(await s.read()).toHaveLength(0);
  await page.getByRole('button', { name: '确认规划并生成用例', exact: true }).click();
  await expect.poll(async () => { const value = await state(); if (value.workflow_runs.some((r: any) => r.status === 'failed')) throw new Error('generation failed'); return value.candidates.length; }, { timeout: 360000 }).toBe(6);
  journal.generated = await state();
  for (let i = 1; i <= 6; i++) expect(journal.generated.candidates.filter((c: any) => c.snapshot.title.includes(`R${i}`))).toHaveLength(1);
  for (const c of journal.generated.candidates) { expect(c.snapshot.steps.length).toBeGreaterThan(0); expect(c.snapshot.steps.length).toBeLessThanOrEqual(4); expect(c.snapshot.steps.every((s: any) => s.action && s.expected)).toBeTruthy(); }
  expect(await s.read()).toHaveLength(0);
  // This synthetic requirement specifies authentication behavior, not page routing.
  // Reject unsupported deterministic assertions even if count/structure are valid.
  for (const c of journal.generated.candidates) {
    expect(c.snapshot.steps.map((s: any) => s.expected).join('\n')).not.toMatch(/跳转至.*首页|停留在登录页面/);
  }
});

test('NL-MUL-08 recovery explicit target preserves baseline and applies corrected value', async ({ page }) => {
  test.skip(!process.env.CASEPILOT_EVAL_RECOVERY, 'Only run against the recorded clarification scenario');
  journal = JSON.parse(readFileSync(process.env.CASEPILOT_EVAL_RECOVERY!, 'utf8'));
  journal.recovery = { originalStatus: journal.status, originalErrors: journal.errors };
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  const login = await page.request.post(`${api}/auth/register`, { data: { email: `nl-${Date.now()}-${Math.random().toString(36).slice(2)}@casepilot.test`, display_name: '自然语言验收', password: 'CasePilot123!' } });
  expect(login.ok()).toBeTruthy();
  const conversation = journal.turns[0].response.conversation_id;
  await page.goto(`/workbench/conversations/${conversation}`);
  const old = journal.original.find((c: any) => c.case_key === journal.keyMap['TC-LOGIN-01']);
  expect(await get(page, `/collections/${journal.collection.id}/test-cases`)).toEqual(journal.original);
  const change = await ready(page, await send(page, '我指 TC-LOGIN-01，将这条用例的优先级改为P2，标题和其他字段不变。'));
  expect(change.items.filter((i: any) => !['applied', 'rejected'].includes(i.status)).map((i: any) => i.ref)).toEqual([old.id]);
  await apply(page);
  const after = await get(page, `/collections/${journal.collection.id}/test-cases`);
  const changed = after.find((c: any) => c.id === old.id);
  expect(changed.priority).toBe('P2'); unchangedExcept(old, changed, ['priority']);
  expect(after.filter((c: any) => c.id !== old.id)).toEqual(journal.original.filter((c: any) => c.id !== old.id));
});
