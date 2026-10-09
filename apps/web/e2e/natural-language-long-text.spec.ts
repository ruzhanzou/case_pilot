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
async function setup(page: Page, long = false, empty = false, transform: (item: any) => void = () => {}) {
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
    transform(item);
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


test('NL-PER-07 short and hundred long steps preserve all content',async({page})=>{
 const observations:any[]=[];
 for(const long of [false,true]) {
  const s=await setup(page,false,false,item=>{if(item.case_key==='TC-LOGIN-01'&&long)item.steps=Array.from({length:100},(_,i)=>({action:`第${i+1}步：`+'记录登录请求及环境并按编号核对凭证。'.repeat(12),expected:`第${i+1}步：`+'逐字核对会话状态与审计结果，原始记录必须完整。'.repeat(10)}));});
  const old=s.byKey('TC-LOGIN-01');const started=Date.now();
  const change=await ready(page,await send(page,'只把 TC-LOGIN-01 标题改为“长文本性能验收”。'));
  expect(change.items[0].proposed_snapshot.steps.map((x:any)=>({action:x.action,expected:x.expected}))).toEqual(old.steps.map((x:any)=>({action:x.action,expected:x.expected})));
  await apply(page);const final=(await s.read()).find((x:any)=>x.id===old.id);unchangedExcept(old,final,['title']);
  observations.push({long,steps:old.steps.length,characters:JSON.stringify(old.steps).length,elapsedMs:Date.now()-started,timings:journal.timings});journal.comparison=observations;
 }
 journal.model_call_count='Not instrumented per task; functional timing cannot infer call count.';
});
test('NL-UX-02 step eighty diff retains surrounding text and can be located',async({page})=>{
 const s=await setup(page,true),a=s.byKey('TC-LOGIN-01');
 const change=await ready(page,await send(page,'只在 TC-LOGIN-01 第80步预期末尾加“审计可查”，保留原文和其他99步。'));
 const proposed=change.items[0].proposed_snapshot;expect(proposed.steps).toHaveLength(100);
 for(let i=0;i<100;i++) {
  expect(proposed.steps[i].action).toBe(a.steps[i].action);
  if(i===79){expect(proposed.steps[i].expected).toContain(a.steps[i].expected);expect(proposed.steps[i].expected).toContain('审计可查');}
  else expect(proposed.steps[i].expected).toBe(a.steps[i].expected);
 }
 const start=Date.now();let clicks=0;
 const review=page.locator('.collection-changes__review');const row=review.locator('.collection-changes__items > details').first();
 if((await row.getAttribute('open')) === null){await row.locator('summary').click();clicks++;}
 const target=review.getByText(/第80项检查记录可查询.*审计可查/).first();await target.scrollIntoViewIfNeeded();await expect(target).toBeVisible();
 journal.diffLocation={ms:Date.now()-start,clicks,limitation:'Automation locates by text; human discoverability remains unmeasured.'};
 await page.screenshot({path:test.info().outputPath('step-80-diff.png')});expect(await s.read()).toEqual(journal.original);
});
