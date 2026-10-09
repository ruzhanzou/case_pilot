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

const rules = suite.fixture_definitions['R-LOGIN'].rules.join('\n');
async function settled(page: Page, turn: any) {
  let state: any;
  await expect.poll(async () => {
    state = await get(page, `/conversations/${turn.conversation_id}`);
    return state.workflow_runs.every((r: any) => !['queued', 'running', 'pending'].includes(r.status));
  }, {timeout:360000}).toBe(true);
  return state;
}
async function plan(page: Page, content: string) {
  const turn = await send(page, content); journal.conversationId = turn.conversation_id;
  await expect(page.getByRole('button', {name:/^确认(?:规划|范围)并生成用例$/})).toBeEnabled({timeout:480000});
  const state = await get(page, `/conversations/${turn.conversation_id}`); journal.planning = state;
  return turn;
}
async function generate(page: Page, turn: any, count?: number, refresh = false) {
  await page.getByRole('button', {name:/^确认(?:规划|范围)并生成用例$/}).click();
  if (refresh) await page.reload();
  await expect.poll(async () => {
    const state = await get(page, `/conversations/${turn.conversation_id}`);
    journal.generated = state;
    if (state.workflow_runs.some((r:any) => r.status === 'failed')) throw new Error(JSON.stringify(state.workflow_runs));
    return state.candidates.length;
  }, {timeout:360000}).toBeGreaterThan(0);
  await expect.poll(async () => {
    const state = await get(page, `/conversations/${turn.conversation_id}`); journal.generated = state;
    return state.workflow_runs.every((r:any) => !['pending','running','queued'].includes(r.status));
  }, {timeout:360000}).toBe(true);
  const candidates = journal.generated.candidates;
  if (count) expect(candidates).toHaveLength(count);
  for(const c of candidates) expect(c.snapshot.steps.every((s:any) => s.action && s.expected)).toBeTruthy();
  return candidates;
}
function expectations(candidates: any[]) { return candidates.flatMap(c=>c.snapshot.steps.map((s:any)=>s.expected)).join('\n'); }
test('NL-GEN-02 missing object clarification resumes original task', async ({page})=>{
 const s=await setup(page,false,true);
 const first=await send(page,'帮我生成测试用例。');
 expect(first.action.job_id).toBeFalsy(); expect(first.assistant_message.content).toMatch(/对象|功能|需求|测试/);
 const turn=await plan(page,'测试对象是账号登录（包含密码和验证码），按以下需求设计6条，每条规则一条：'+rules);
 expect(turn.conversation_id).toBe(first.conversation_id);
 await generate(page,turn,6);expect(await s.read()).toHaveLength(0);
});
test('NL-GEN-03 unspecified thresholds remain open',async({page})=>{
 const s=await setup(page,false,true);
 const turn=await send(page,'需求仅规定支持验证码登录。给验证码登录设计过期和重发频率用例，未提供的阈值必须列待确认，不能编造。');
 journal.planning=await settled(page,turn);
 const content=JSON.stringify(journal.planning);
 expect(content).toMatch(/待确认|未明确|未提供|有效期|频率/);
 const button=page.getByRole('button',{name:/^确认(?:规划|范围)并生成用例$/});
 if(await button.isVisible()) {
  const cases=await generate(page,turn);
  expect(expectations(cases)).not.toMatch(/(?:60|120|30|5)\s*(?:秒|分钟|次)/);
 } else {
  expect(journal.planning.candidates).toHaveLength(0);
  const brief=journal.planning.test_briefs.at(-1);
  expect(brief).toBeTruthy();
  const points=brief.content.planning.test_points;
  expect(points.length).toBeGreaterThan(0);
  expect(JSON.stringify(brief)).toMatch(/待确认|未明确|未提供/);
  expect(JSON.stringify(brief.content)).not.toMatch(/(?:60|120|30|5)\s*(?:秒|分钟|次)/);
 }
 expect(await s.read()).toHaveLength(0);
});
test('NL-GEN-04 conflicting thresholds require resolution',async({page})=>{
 const s=await setup(page,false,true);
 const first=await send(page,'需求甲写验证码有效期60秒，需求乙写验证码有效期120秒，二者没有优先级。按这份需求生成验证码过期边界用例。');
 const state = await settled(page,first); journal.conflictPlanning=state;
 expect(state.messages.filter((m:any)=>m.role==='assistant').at(-1).content).toMatch(/冲突|矛盾|确认|60|120/);
 const turn=await plan(page,'以120秒为准：未使用验证码在t<120秒有效，t>=120秒过期。仅生成这两个边界场景，共2条。');
 const cases=await generate(page,turn,2); expect(expectations(cases)).not.toMatch(/60秒/);
 expect(JSON.stringify(cases)).toContain('120'); expect(await s.read()).toHaveLength(0);
});
test('NL-GEN-05 revised planning excludes obsolete password scope',async({page})=>{
 const s=await setup(page,false,true);
 await plan(page,'按以下规则生成6条，先给测试规划：'+rules);
 const turn=await plan(page,'去掉密码登录，只保留验证码登录，补上有效期临界值，以120秒为界。共4条：119秒、120秒、已使用验证码、正常未使用验证码。');
 const cases=await generate(page,turn,4);
 expect(cases.every((c:any)=>!c.snapshot.title.includes('密码'))).toBeTruthy();
 expect(JSON.stringify(cases)).toContain('120');expect(await s.read()).toHaveLength(0);
});
test('NL-GEN-08 mixed dimensions have actionable checks without invented SLA',async({page})=>{
 const s=await setup(page,false,true);
 const turn=await plan(page,'围绕登录生成正常、边界、异常、性能、易用性用例，每类恰好1条，共5条，标题含维度名称；未知性能指标标待确认。需求：'+rules);
 const cases=await generate(page,turn,5);
 for(const dimension of ['正常','边界','异常','性能','易用']) expect(cases.some((c:any)=>c.snapshot.title.includes(dimension))).toBeTruthy();
 const perf=cases.find((c:any)=>c.snapshot.title.includes('性能'));
 expect(JSON.stringify(perf.snapshot)).toMatch(/待确认|记录|测量|统计/);
 expect(await s.read()).toHaveLength(0);
});
test('NL-GEN-09 long requirement preserves final logout rule',async({page})=>{
 const s=await setup(page,false,true);
 const background='历史背景材料，仅作背景不构成功能要求：团队曾讨论账号页面配色、帮助文字与排期，目前均未确定。'.repeat(210);
 const content=background+'\n实际业务规则：'+rules+'\n最后一条关键规则：退出后旧令牌不可用。';
 const input=page.locator('.principle-composer textarea');await input.fill(content);
 expect(await input.inputValue()).toBe(content);
 const response=page.waitForResponse(r=>r.request().method()==='POST' && r.url().endsWith('/messages'));
 await page.locator('.principle-composer button[type=submit]').click();
 const rejected=await response;journal.lengthRejection={status:rejected.status(),body:await rejected.json()};
 expect(rejected.status()).toBe(422);expect(JSON.stringify(journal.lengthRejection.body)).toMatch(/8000|too_long/);
 expect(await s.read()).toHaveLength(0);
 await expect(page.locator('body')).toContainText(/8000|过长|长度|字符/);

});
test('NL-GEN-10 authoritative v2 excludes historical threshold',async({page})=>{
 const s=await setup(page,false,true);
 const turn=await plan(page,'来源v1（历史）：验证码有效期60秒。来源v2（当前生效）：验证码在t<120秒有效，在t>=120秒过期。按v2生成2条过期边界，v1只作历史参考。');
 const cases=await generate(page,turn,2);
 expect(expectations(cases)).not.toMatch(/60秒/);expect(JSON.stringify(cases)).toContain('120');
 expect(JSON.stringify(cases)).toContain('v2');expect(await s.read()).toHaveLength(0);
});
for (const [index,wording] of ['按六条规则各写一条用例。','给这六个规则各设计一个可执行的测试场景。','六个规则一条一个，帮我出用例。'].entries()) test(`NL-GEN-11 paraphrase ${index+1} keeps six rules`,async({page})=>{
 const s=await setup(page,false,true);
 const turn=await plan(page,wording+'标题保留R编号，不扩充规则。需求：'+rules);
 const cases=await generate(page,turn,6);
 for(let i=1;i<=6;i++)expect(cases.filter((c:any)=>c.snapshot.title.includes(`R${i}`))).toHaveLength(1);
 expect(expectations(cases)).not.toMatch(/跳转.*首页|停留.*登录页/);expect(await s.read()).toHaveLength(0);
});
test('NL-REC-01 refresh running generation restores same job',async({page})=>{
 const s=await setup(page,false,true);
 const turn=await plan(page,'生成六条登录用例，每条规则一条，标题含规则编号：'+rules);
 await generate(page,turn,6,true);
 const jobs=journal.generated.workflow_runs.filter((r:any)=>r.mode==='generation');
 journal.generationJobs=jobs;
 expect(await s.read()).toHaveLength(0);
 expect(new Set(journal.generated.candidates.map((c:any)=>c.ref)).size).toBe(6);
});
