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
  const login = await page.request.post(`${api}/auth/register`, { data: { email: `nl-isolation-${Date.now()}@casepilot.test`, display_name: '隔离验收', password: 'CasePilot123!' } });
  expect(login.ok()).toBeTruthy(); const account = await login.json(); journal.accountEmail = account.email;
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


async function post(page:Page,path:string,data:any) {const r=await page.request.post(api+path,{data});expect(r.ok(),await r.text()).toBeTruthy();return r.json();}
test('NL-SCP-10 same key in another authorized space stays unchanged',async({page,browser})=>{
 const s=await setup(page),a=s.byKey('TC-LOGIN-01');
 const other=await browser.newContext(); const p=await other.newPage();
 try {
  const account=await post(p,'/auth/register',{email:`nl-space-${Date.now()}@casepilot.test`,display_name:'隔离空间验收',password:'CasePilot123!'});
  const space=account.spaces[0];
  await post(p,`/spaces/${space.id}/members`,{email:journal.accountEmail});
  const collection=await post(p,`/spaces/${space.id}/collections`,{name:'同编号隔离集合'});
  const original=await post(p,`/collections/${collection.id}/test-cases`,{case_key:a.case_key,title:'不可修改的另一空间资产',priority:'P1',module:'登录',case_type:'功能',preconditions:[],steps:[{action:'另空间提交',expected:'原样保留'}]});
  journal.other={space,collection,original};
  await ready(page,await send(page,'把当前集合 TC-LOGIN-01 标题改为「当前集合登录验证」。'));await apply(page);
  expect((await s.read()).find((c:any)=>c.id===a.id).title).toBe('当前集合登录验证');
  expect(await get(page,`/test-cases/${original.id}`)).toEqual(original);
 } finally {await other.close();}
});
test('NL-SEC-02 unauthorized reads writes and target binding are denied',async({page,browser})=>{
 const s=await setup(page),a=s.byKey('TC-LOGIN-01');
 const change=await ready(page,await send(page,'把 TC-LOGIN-01 优先级改为P0。'));
 const other=await browser.newContext(); const p=await other.newPage();
 try {
  const account=await post(p,'/auth/register',{email:`nl-unprivileged-${Date.now()}@casepilot.test`,display_name:'权限边界验收',password:'CasePilot123!'});
  const results=[];
  for(const path of [`/collections/${journal.collection.id}`,`/collections/${journal.collection.id}/test-cases`,`/test-cases/${a.id}`,`/case-change-sets/${change.id}`]){
   const r=await p.request.get(api+path);const body=await r.text();results.push({path,status:r.status(),body});expect([403,404]).toContain(r.status());expect(body).not.toContain(a.title);
  }
  const apply=await p.request.post(`${api}/case-change-sets/${change.id}/apply`,{data:{}});expect([403,404]).toContain(apply.status());
  const bind=await p.request.post(`${api}/conversations`,{data:{space_id:account.spaces[0].id,collection_id:journal.collection.id}});expect([403,404]).toContain(bind.status());
  journal.denials={results,apply:apply.status(),bind:bind.status()};
  expect(await s.read()).toEqual(journal.original);
 } finally {await other.close();}
});
test('NL-MUL-09 new conversation does not inherit old pending proposal',async({page})=>{
 const s=await setup(page),a=s.byKey('TC-LOGIN-01'),b=s.byKey('TC-LOGIN-02');
 const old=await ready(page,await send(page,'把 TC-LOGIN-01 标题改为“旧会话待采纳”。'));
 const me=await get(page,'/auth/me');
 const fresh=await post(page,'/conversations',{space_id:me.spaces[0].id,collection_id:journal.collection.id,title:'新会话隔离验收'});
 await page.goto(`/workbench/conversations/${fresh.id}`);
 const change=await ready(page,await send(page,'把 TC-LOGIN-02 的优先级改为P0。'));
 expect(change.items.map((i:any)=>i.ref)).toEqual([b.id]);await apply(page);
 const after=await s.read();expect(after.find((c:any)=>c.id===a.id)).toEqual(a);expect(after.find((c:any)=>c.id===b.id).priority).toBe('P0');
 expect((await get(page,`/case-change-sets/${old.id}`)).status).toBe('ready');
});
test('NL-MUL-12 ten pending rounds preserve steps and one final revision',async({page})=>{
 test.setTimeout(1200000);
 const s=await setup(page),a=s.byKey('TC-LOGIN-01');
 for(let n=1;n<=10;n++) {
  const change=await ready(page,await send(page,`把 TC-LOGIN-01 标题改为“第${n}轮登录检查”，保留全部步骤和其他字段。`));
  expect(change.items[0].proposed_snapshot.steps.map((s:any)=>({action:s.action,expected:s.expected}))).toEqual(a.steps.map((s:any)=>({action:s.action,expected:s.expected})));
 }
 await ready(page,await send(page,'继续把 TC-LOGIN-01 优先级改成P2，仍然不要改步骤。'));await apply(page);
 const after=await s.read(),changed=after.find((c:any)=>c.id===a.id);
 expect(changed.title).toBe('第10轮登录检查');expect(changed.priority).toBe('P2');unchangedExcept(a,changed,['title','priority']);
 expect(after.filter((c:any)=>c.id!==a.id)).toEqual(journal.original.filter((c:any)=>c.id!==a.id));
});
test('NL-REV-06 rejecting all keeps assets unchanged after reload',async({page})=>{
 const s=await setup(page);const change=await ready(page,await send(page,'把登录模块全部优先级改P0。'));
 await post(page,`/case-change-sets/${change.id}/reject`,{});await page.reload();
 await expect(page.locator('.principle-composer textarea')).toBeEnabled();
 expect((await get(page,`/case-change-sets/${change.id}`)).status).toBe('rejected');expect(await s.read()).toEqual(journal.original);
 await expect(page.getByRole('button',{name:/一键采纳全部待审阅用例/})).toHaveCount(0);
});
test('NL-REC-02 navigation restores original rewrite task',async({page})=>{
 const s=await setup(page);const turn=await send(page,'给登录模块用例补充审计日志校验。');
 expect(turn.action.job_id).toBeTruthy();
 await page.goto('/workbench');await page.goto(`/workbench/conversations/${turn.conversation_id}`);
 const change=await ready(page,turn);expect(change.items).toHaveLength(2);
 expect(await s.read()).toEqual(journal.original);
 const state=await get(page,`/conversations/${turn.conversation_id}`);journal.restored=state;
 expect(state.operation_history.filter((o:any)=>o.related_change_set_id===change.id)).toHaveLength(1);
});
