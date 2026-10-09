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
test('NL-PER-01 records first visible feedback and complete queued task timeline',async({page})=>{
 const s=await setup(page);const a=s.byKey('TC-LOGIN-01');
 await page.locator('.principle-composer textarea').fill(`给 ${a.case_key} 补充断网恢复验证。`);
 await page.evaluate(()=>{
  (window as any).__qaFeedback={start:performance.now()};
  const observer=new MutationObserver(()=>{
   if(document.querySelector('[data-testid="scope-thinking"]')){(window as any).__qaFeedback.ack=performance.now();observer.disconnect();}
  });observer.observe(document.body,{subtree:true,childList:true});
 });
 const start=Date.now();const response=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/messages'));
 await page.locator('.principle-composer button[type=submit]').click();const turn=await(await response).json();
 journal.turns.push(turn);journal.feedback=await page.evaluate(()=>(window as any).__qaFeedback);journal.feedback.apiMs=Date.now()-start;
 expect(journal.feedback.ack).toBeTruthy();journal.feedback.ackMs=journal.feedback.ack-journal.feedback.start;
 const p=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/resume'));const confirming=Date.now();
 await page.getByRole('button',{name:'确认修改并生成建议',exact:true}).click();const work=await(await p).json();journal.feedback.confirmationMs=Date.now()-confirming;
 journal.queue=[];let change:any;
 await expect.poll(async()=>{
  const state=await get(page,`/conversations/${work.conversation_id}`);const run=state.workflow_runs.find((x:any)=>x.job_id===work.action.job_id);
  change=await get(page,`/case-change-sets/${work.action.change_set_id}`);journal.queue.push({elapsedMs:Date.now()-confirming,status:run?.status,stage:run?.stage,items:change.items.length});return change.status;
 },{timeout:600000,intervals:[1000,2000,5000]}).toBe('ready');
 journal.feedback.totalMs=Date.now()-start;journal.feedback.readyAfterConfirmationMs=Date.now()-confirming;
 journal.loadCondition='Shared provider; inspect concurrency journals for overlapping users. Not an isolated SLA benchmark.';
 expect(await s.read()).toEqual(journal.original);
});
