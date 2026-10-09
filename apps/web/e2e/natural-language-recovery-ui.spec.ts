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
async function keyboardReach(page:Page,target:ReturnType<Page['locator']>) {
 for(let i=0;i<180;i++) {
  if(await target.evaluateAll(elements=>elements.some(element => element === document.activeElement))) return;
  await page.keyboard.press('Tab');
 }
 throw new Error('Keyboard Tab cannot reach requested control');
}
test('NL-UX-05 keyboard submits confirms reviews and applies',async({page})=>{
 const s=await setup(page),a=s.byKey('TC-LOGIN-01');const input=page.locator('.principle-composer textarea');
 await keyboardReach(page,input);await page.keyboard.type(`把 ${a.case_key} 优先级改P0。`);
 await keyboardReach(page,page.locator('.principle-composer button[type=submit]'));
 const pending=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/messages'));
 await page.keyboard.press('Enter');const first=await(await pending).json();journal.turns.push(first);
 expect(first.action.job_id).toBeFalsy();expect(await s.read()).toEqual(journal.original);
 await keyboardReach(page,page.getByRole('button',{name:'确认修改并生成建议',exact:true}).last());
 const response=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/resume'));
 await page.keyboard.press('Enter');const turn=await(await response).json();journal.turns.push(turn);
 await expect.poll(async()=> (await get(page,`/case-change-sets/${turn.action.change_set_id}`)).status,{timeout:360000}).toBe('ready');
 const reviewLink=page.getByRole('button',{name:'前往工作区审阅',exact:true});
 if(await reviewLink.isVisible()){await keyboardReach(page,reviewLink);await page.keyboard.press('Enter');}
 const button=page.locator('.collection-changes__review').getByRole('button',{name:/一键采纳全部待审阅用例/});
 await keyboardReach(page,button);await expect(button).toBeFocused();await page.screenshot({path:test.info().outputPath('keyboard-focus.png')});
 const save=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/apply'));
 await page.keyboard.press('Enter');expect((await save).ok()).toBeTruthy();
 expect((await s.read()).find((x:any)=>x.id===a.id).priority).toBe('P0');
});
test('NL-UX-06 review and partial apply at 200 percent equivalent viewport',async({page})=>{
 // 640x360 CSS pixels reproduces the layout area of 1280x720 at 200% browser zoom.
 await page.setViewportSize({width:640,height:360});const s=await setup(page);
 await ready(page,await send(page,'把登录模块全部优先级改P0。'));
 const rows=page.locator('.collection-changes__items > details');await expect(rows).toHaveCount(2);
 await rows.last().locator('summary').click();await rows.last().getByRole('checkbox').first().uncheck();
 await page.screenshot({path:test.info().outputPath('small-review.png')});await apply(page,true);
 const after=await s.read();expect(after.filter((x:any)=>x.priority==='P0')).toHaveLength(1);
});
test('NL-REC-07 concurrent workspace draft update survives task completion',async({page})=>{
 const s=await setup(page);const turn=await send(page,'把 TC-LOGIN-01 标题改为“并发草稿验证”。');
 const draft='下一轮草稿：暂时不要提交';
 const saved=await page.request.patch(`${api}/workspaces/${turn.conversation_id}`,{data:{draft_text:draft}});expect(saved.ok()).toBeTruthy();
 await ready(page,turn);const state=await get(page,`/conversations/${turn.conversation_id}`);journal.concurrentState=state;
 expect(state.context.draft_text).toBe(draft);expect(await s.read()).toEqual(journal.original);
 await page.reload();await expect(page.locator('.principle-composer textarea')).toHaveValue(draft,{timeout:60000});
});
test('NL-REC-08 lost submit response is discoverable after reload',async({page})=>{
 const s=await setup(page),a=s.byKey('TC-LOGIN-01');let created:any;
 await page.route('**/api/v1/conversations/*/messages',async route=>{
  if(route.request().method()!=='POST')return route.continue();
  const response=await route.fetch({url:route.request().url().replace('http://localhost:8000/api/v1',api)});expect(response.ok()).toBeTruthy();created=await response.json();journal.lostResponse=created;await route.abort('failed');
 },{times:1});
 await page.locator('.principle-composer textarea').fill(`把 ${a.case_key} 优先级改P0。`);await page.locator('.principle-composer button[type=submit]').click();
 await expect.poll(()=>Boolean(created),{timeout:180000}).toBe(true);expect(await s.read()).toEqual(journal.original);
 await page.reload();await expect(page.getByRole('button',{name:'确认修改并生成建议',exact:true})).toBeVisible({timeout:60000});
 const p=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/resume'));
 await page.getByRole('button',{name:'确认修改并生成建议',exact:true}).click();const turn=await(await p).json();await ready(page,turn);await apply(page);
 const state=await get(page,`/conversations/${created.conversation_id}`);journal.recovered=state;
 expect(state.workflow_runs.filter((x:any)=>x.operation==='conversation_modify')).toHaveLength(1);
 expect((await s.read()).find((x:any)=>x.id===a.id).revision_number).toBe(a.revision_number+1);
});
test('NL-PER-08 twenty refresh cycles keep a single task and bounded streams',async({page})=>{
 await setup(page);const extra=Array.from({length:96},(_,i)=>({case_key:`EXTRA-${i}`,title:`登录${i}`,module:'登录',priority:'P1',steps:[{action:'提交',expected:'会话建立'}]}));
 expect((await page.request.post(`${api}/collections/${journal.collection.id}/test-cases/batch`,{data:{cases:extra}})).ok()).toBeTruthy();
 await page.reload();const turn=await send(page,'给当前集合全部100条用例最后一步预期补充“审计记录可查询”，其他不变。');
 let active=0,peak=0;const streams=new Set<any>();
 page.on('request',r=>{if(r.url().includes('/events')){streams.add(r);active++;peak=Math.max(peak,active);}});
 const done=(r:any)=>{if(streams.delete(r))active--;};page.on('requestfinished',done);page.on('requestfailed',done);
 journal.refresh=[];
 for(let i=0;i<20;i++) {
  const start=Date.now();await page.reload();await expect(page.locator('.principle-composer textarea')).toBeVisible({timeout:60000});
  journal.refresh.push({index:i,ms:Date.now()-start,active,peak,heap:await page.evaluate(()=>(performance as any).memory?.usedJSHeapSize??null)});
 }
 const state=await get(page,`/conversations/${turn.conversation_id}`);journal.afterCycles=state;
 expect(state.workflow_runs.filter((x:any)=>x.operation==='conversation_modify')).toHaveLength(1);expect(active).toBeLessThanOrEqual(2);expect(peak).toBeLessThanOrEqual(3);
});
