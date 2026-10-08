import { expect, test, type Page } from '@playwright/test';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { TestCaseDto, CaseChangeSetDto } from '../lib/casepilot-api';

test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1', 'Real services and model required');
test.describe.configure({ mode: 'serial' });
test.use({ viewport: { width: 1600, height: 1000 }, video: { mode: 'on', size: { width: 1600, height: 1000 } }, trace: 'on' });
const dir = resolve('../../output/module-hundred-acceptance');
const api = `${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
const save = (name: string, data: unknown) => writeFileSync(`${dir}/${name}.json`, JSON.stringify(data, null, 2));
const read = (name: string) => JSON.parse(readFileSync(`${dir}/${name}.json`, 'utf8'));
const manifests = new WeakMap<Page, string[]>();
test.beforeEach(async ({ page }) => {
  mkdirSync(dir, { recursive: true });
  const documents: string[] = []; manifests.set(page, documents);
  page.on('request', request => { if (request.resourceType() === 'document' && request.frame() === page.mainFrame()) documents.push(request.url()); });
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  expect((await page.request.post(`${api}/auth/login`, { data: { email: 'demo@casepilot.local', password: 'CasePilot123!' } })).ok()).toBeTruthy();
});
test.afterEach(async ({ page }, info) => {
  await info.attach('document-loads', { body: JSON.stringify(manifests.get(page)), contentType: 'application/json' });
  if (info.status === 'passed') expect(manifests.get(page)).toHaveLength(1);
});
async function cases(page: Page): Promise<TestCaseDto[]> { return (await page.request.get(`${api}/collections/${read('manifest').collection.id}/test-cases`)).json(); }
async function shot(page: Page, name: string) { await page.screenshot({ path: `${dir}/${name}.png`, fullPage: true }); }
async function open(page: Page) { await page.goto(`/workbench/conversations/${read('manifest').conversationId}`); await expect(page.locator('.principle-composer textarea')).toBeEnabled({ timeout: 60000 }); }
async function send(page: Page, content: string, intent: string | string[]) {
  const composer = page.locator('.principle-composer textarea'); await expect(composer).toBeEnabled({ timeout: 900000 }); await composer.fill(content);
  const pending = page.waitForResponse(r => r.request().method() === 'POST' && /\/(messages|resume)$/.test(new URL(r.url()).pathname), { timeout: 180000 });
  await page.locator('.principle-composer button[type=submit]').click(); const response = await pending;
  expect(response.ok(), await response.text()).toBeTruthy(); const result = await response.json();
  save(`request-${Date.now()}`, { content, response: result });
  expect(Array.isArray(intent) ? intent : [intent]).toContain(result.intent);
  expect(result.assistant_message.status, result.assistant_message.content).not.toMatch(/awaiting_clarification|awaiting_target|awaiting_intent/);
  await expect(composer).toBeEnabled({ timeout: 60000 });
  return result;
}
async function proposal(page: Page, id: string): Promise<CaseChangeSetDto> {
  await expect.poll(async () => (await (await page.request.get(`${api}/case-change-sets/${id}`)).json()).status, { timeout: 900000, intervals: [2000, 4000] }).toBe('ready');
  const result = await (await page.request.get(`${api}/case-change-sets/${id}`)).json();
  await expect(page.locator('.collection-changes__review')).toContainText(`涉及 ${result.items.length} 条用例`);
  return result;
}

test('01 query all 100 cases individually and verify ten module scopes', async ({ page }) => {
  test.setTimeout(600000);
  const account = await (await page.request.get(`${api}/auth/me`)).json();
  const collectionResponse = await page.request.post(`${api}/spaces/${account.spaces[0].id}/collections`, { data: { name: `100条用例-整模块重写与新增模块-${Date.now()}`, description: '10个模块各10条；真实模型整模块语义重写和新增模块验收' } });
  expect(collectionResponse.ok()).toBeTruthy(); const collection = await collectionResponse.json();
  const fixture: TestCaseDto[] = JSON.parse(readFileSync(resolve('../../output/acceptance-hundred/100-cases.json'), 'utf8'));
  for (let offset = 0; offset < fixture.length; offset += 5) {
    await Promise.all(fixture.slice(offset, offset + 5).map(async (c, index) => {
      const response = await page.request.post(`${api}/collections/${collection.id}/test-cases`, { data: { case_key: `M100-${collection.id.slice(0, 8)}-${String(offset + index + 1).padStart(3, "0")}`, title: c.title, module: c.module, priority: c.priority, case_type: c.case_type, tags: c.tags, preconditions: c.preconditions, steps: c.steps.map(s => ({ action: s.action, expected: s.expected })), source: '已有100条真实生成用例的隔离验收副本', source_refs: c.source_refs } });
      expect(response.ok(), await response.text()).toBeTruthy();
    }));
  }
  const stateResponse = await page.request.put(`${api}/collections/${collection.id}/workspace`); expect(stateResponse.ok()).toBeTruthy(); const state = await stateResponse.json();
  save('manifest', { collection, conversationId: state.id, url: `${process.env.CASEPILOT_E2E_BASE_URL}/workbench/conversations/${state.id}`, fixtureSource: 'output/acceptance-hundred/100-cases.json' });
  const original = await cases(page); expect(original).toHaveLength(100); save('original-cases', original);
  await open(page); await send(page, '查询当前集合的全部100条用例，只查询不修改。', 'CASE_QUERY');
  const result = page.locator('.task-query-results'); await expect(result).toContainText('匹配 100 条用例', { timeout: 60000 });
  await expect(result.locator('tbody tr')).toHaveCount(20); await shot(page, '01-hundred-query');
  for (let p = 2; p <= 5; p++) { await result.getByRole('button', { name: '下一页', exact: true }).click(); await expect(result.locator('footer')).toContainText(`第 ${p} / 5 页`); await expect(result.locator('tbody tr')).toHaveCount(20); }
  await expect(result.getByRole('button', { name: '下一页', exact: true })).toBeDisabled();
  for (const module of new Set(original.map(c => c.module))) {
    await result.getByLabel('按模块筛选').selectOption(module); await expect(result.locator('tbody tr')).toHaveCount(10);
    for (const cell of await result.locator('tbody tr td:nth-child(3)').allTextContents()) expect(cell).toBe(module);
  }
  await result.getByLabel('按模块筛选').selectOption('');
  const audit: unknown[] = [];
  for (const c of original) {
    await result.getByRole('searchbox', { name: '搜索查询结果' }).fill(c.case_key);
    // Match the full ID: M100-1 also matches M100-10; use the title when needed.
    await result.getByRole('searchbox', { name: '搜索查询结果' }).fill(c.title);
    const row = result.locator('tbody tr').filter({ has: page.getByText(c.case_key, { exact: true }) });
    await expect(row).toHaveCount(1); await row.locator('summary').click();
    await expect(row).toContainText(c.preconditions[0]); for (const step of c.steps) { await expect(row).toContainText(step.action); await expect(row).toContainText(step.expected); }
    audit.push({ id: c.id, caseKey: c.case_key, module: c.module, title: c.title, queryDetail: 'passed', originalVersion: c.revision_number, moduleRewrite: 'pending', moduleAdditionIsolation: 'pending' }); save('100-case-audit', audit);
  }
  await result.getByRole('searchbox', { name: '搜索查询结果' }).fill('无匹配QA模块XYZ'); await expect(result).toContainText('没有符合筛选条件的用例');
  await result.getByRole('searchbox', { name: '搜索查询结果' }).fill(''); expect(await cases(page)).toEqual(original);
  await shot(page, '02-all-modules-query-complete'); save('query-result', { passed: true, individualCases: 100, modules: 10, pages: 5 });
});

test('02 rewrite every case in a whole module semantically and refine the whole proposal', async ({ page }) => {
  test.setTimeout(2400000); await open(page); const original: TestCaseDto[] = read('original-cases'); const login = original.filter(c => c.module === '账号登录');
  const first = await send(page, '整体重写「账号登录」模块的全部10条用例，保留每条原测试目标、标题、优先级和业务规则，其他9个模块不得改动。不是只改标题或优先级：请把每条操作步骤重写为至少2个可执行步骤，将准备输入、提交登录、观察对应结果分开，每个步骤给出明确可验证的预期。正常、异常、密码长度边界、连续5次错误锁定30分钟等原有规则必须保留。在每条前置条件补充「模块重写验收环境已就绪」。只生成修改方案供我审阅，暂不应用。', 'CASE_MODIFY');
  const p1 = await proposal(page, first.action.change_set_id); save('module-proposal-v1', p1);
  expect(p1.items).toHaveLength(10); expect(p1.items.map(i => i.ref).sort()).toEqual(login.map(c => c.id).sort());
  for (const item of p1.items) { expect(item.field_diff.some(d => d.field === 'steps')).toBeTruthy(); expect((item.proposed_snapshot.steps as unknown[]).length).toBeGreaterThanOrEqual(2); expect(item.proposed_snapshot.title).toBe(login.find(c => c.id === item.ref)!.title); expect(JSON.stringify(item.proposed_snapshot.preconditions)).toContain('模块重写验收环境已就绪'); }
  expect(await cases(page)).toEqual(original);
  const review = page.locator('.collection-changes__review'); await review.locator('details').first().locator('summary').click(); await shot(page, '03-whole-module-steps-before-after');
  await review.getByRole('button', { name: '继续调整这版结果', exact: true }).click();
  const second = await send(page, '这一版继续调整整个账号登录模块的10条用例：保留上一版已经拆分的全部操作步骤、预期结果和「模块重写验收环境已就绪」前置条件。只在每条前置条件再补充「每条用例使用独立账号，错误次数互不影响」，标题、优先级、所属模块和测试目标保持不变。仍先让我审阅。', 'CASE_MODIFY');
  const p2 = await proposal(page, second.action.change_set_id); save('module-proposal-v2', p2);
  expect(p2.items).toHaveLength(10);
  for (const item of p2.items) {
    expect(item.proposal_version).toBe(2); const previous = p1.items.find(i => i.ref === item.ref)!;
    expect(item.proposed_snapshot.steps).toEqual(previous.proposed_snapshot.steps); expect(item.proposed_snapshot.title).toBe(previous.proposed_snapshot.title);
    expect(JSON.stringify(item.proposed_snapshot.preconditions)).toContain('每条用例使用独立账号，错误次数互不影响');
    expect(JSON.stringify(item.proposed_snapshot.preconditions)).toContain('模块重写验收环境已就绪'); expect(item.field_diff.some(d => d.field === 'steps')).toBeTruthy();
  }
  expect(await cases(page)).toEqual(original); await expect(review).toContainText('修改方案 V2');
  await review.locator('details').first().locator('summary').click(); await review.getByRole('button', { name: '相对上一版变化', exact: true }).click();
  await expect(review.locator('.collection-changes__field')).toHaveCount(10); await shot(page, '04-whole-module-second-round-only');
  await review.getByRole('button', { name: '累计待应用变化', exact: true }).click(); await shot(page, '05-whole-module-cumulative-diff');
  const old = await (await page.request.get(`${api}/case-change-sets/${p1.id}`)).json(); expect(old.status).toBe('superseded');
  await review.getByRole('button', { name: '应用已选修改', exact: true }).click();
  await expect.poll(async () => (await cases(page)).filter(c => c.module === '账号登录' && c.revision_number === 2).length).toBe(10);
  const updated = await cases(page); expect(updated).toHaveLength(100);
  const audit = read('100-case-audit');
  for (const c of updated) {
    const old = original.find(o => o.id === c.id)!;
    if (c.module === '账号登录') { const draft = p2.items.find(i => i.ref === c.id)!.proposed_snapshot; expect(c.steps.map(s => ({ action: s.action, expected: s.expected }))).toEqual(draft.steps); expect(c.preconditions).toEqual(draft.preconditions); expect(c.title).toBe(old.title); expect(c.priority).toBe(old.priority); }
    else expect(c).toEqual(old);
    Object.assign(audit.find((a: {id:string}) => a.id === c.id), { moduleRewrite: 'passed', rewriteExpectation: c.module === '账号登录' ? '整模块语义重写，两轮累积结果准确保存' : '非目标模块所有字段与版本完全不变', currentVersion: c.revision_number });
  }
  save('100-case-audit', audit); save('after-module-rewrite', updated); save('module-rewrite-result', { passed: true, scope: 10, untouched: 90, rounds: 2 }); await shot(page, '06-whole-module-applied');
});

test('03 add a new module with ten generated cases and cancel deleting the whole module', async ({ page }) => {
  test.setTimeout(1800000); await open(page); const before: TestCaseDto[] = read('after-module-rewrite');
  await send(page, '新增「发票管理」模块，并生成恰好10条新的候选用例。测试对象是电商电子发票系统，现有100条用例和其他模块不得改写或删除。只覆盖以下10个独立场景，每场景1条：1已支付订单申请个人发票成功；2未支付订单不能开票；3企业发票缺少税号被拒绝；4合法企业税号可开票；5重复提交同一订单不重复开票；6用户不能为他人订单开票；7发票金额等于实付金额；8已全额退款订单禁止开票；9已开票订单可下载PDF；10开票服务暂时失败允许重试且最终仅一张发票。前置条件为测试环境可用，有个人用户、企业用户、已支付/未支付/已退款订单及发票服务。每条必须有明确步骤、预期和优先级。所属模块必须是「发票管理」，先生成候选供我审阅，不直接纳入正式集合。', 'CASE_GENERATE');
  const confirm = page.getByRole('button', { name: /确认范围并生成用例|确认并生成用例/ }).first(); await expect(confirm).toBeEnabled({ timeout: 600000 });
  expect(await cases(page)).toEqual(before); await shot(page, '07-new-module-scope'); await confirm.click();
  const result = page.locator('.task-result-cases'); await expect(result.getByRole('button', { name: '纳入已选候选', exact: true })).toBeEnabled({ timeout: 900000 });
  const state = await (await page.request.get(`${api}/conversations/${read('manifest').conversationId}`)).json();
  const generated = state.candidates.filter((c: {status:string}) => c.status === 'candidate'); expect(generated).toHaveLength(10); save('new-module-candidates', generated);
  for (const c of generated) { expect(c.snapshot.module).toBe('发票管理'); expect(c.snapshot.preconditions.length).toBeGreaterThan(0); expect(c.snapshot.steps.length).toBeGreaterThan(0); }
  expect(new Set(generated.map((c: {snapshot:{title:string}}) => c.snapshot.title)).size).toBe(10); expect(await cases(page)).toEqual(before);
  await expect(result.locator(':scope > details')).toHaveCount(10); await result.locator(':scope > details').first().locator('summary').click(); await expect(result).toContainText('前置条件'); await shot(page, '08-new-module-candidates');
  await result.getByRole('button', { name: '纳入已选候选', exact: true }).click(); await expect.poll(async () => (await cases(page)).length).toBe(110);
  const added = await cases(page); expect(added.filter(c => c.module === '发票管理')).toHaveLength(10);
  const audit = read('100-case-audit'); for (const old of before) { expect(added.find(c => c.id === old.id)).toEqual(old); Object.assign(audit.find((a: {id:string}) => a.id === old.id), { moduleAdditionIsolation: 'passed', status: 'passed' }); }
  save('100-case-audit', audit); save('final-cases', added);
  await page.getByRole('button', { name: '用例脑图', exact: true }).click(); await expect(page.locator('.principle-workbench')).toContainText('发票管理'); await shot(page, '09-eleven-modules-110-cases');
  const deletion = await send(page, '删除「发票管理」模块下的全部10条用例，其他100条用例保持不变，先让我在工作区确认。', 'CASE_DELETE');
  const change = await proposal(page, deletion.action.change_set_id); expect(change.items).toHaveLength(10); expect(change.items.map(i => i.ref).sort()).toEqual(added.filter(c => c.module === '发票管理').map(c => c.id).sort());
  expect(await cases(page)).toEqual(added); await shot(page, '10-module-delete-review'); await page.locator('.collection-changes__review').getByRole('button', { name: '取消变更', exact: true }).click();
  await expect(page.locator('.collection-changes__badge')).toHaveText('未应用'); expect(await cases(page)).toEqual(added); await shot(page, '11-module-delete-cancelled');
  save('module-addition-result', { passed: true, generated: 10, finalTotal: 110, untouchedOriginalCases: 100, wholeModuleDeleteCancelled: true });
});

test('04 create an empty module and avoid duplicate module nodes', async ({ page }) => {
  test.setTimeout(300000);
  const collectionId = read('manifest').collection.id;
  const readCollection = async () => (await page.request.get(`${api}/collections/${collectionId}`)).json();
  // Reset only the empty node created by this isolated acceptance fixture.
  const fixture = await readCollection();
  expect((await page.request.patch(`${api}/collections/${collectionId}`, { data: { mind_map_notes: fixture.mind_map_notes.filter((n: {kind:string;module:string}) => !(n.kind === 'module' && n.module === '审计日志')) } })).ok()).toBeTruthy();
  await open(page); const before = await cases(page);
  await page.getByRole('button', { name: '用例脑图', exact: true }).click();
  await page.getByRole('button', { name: '全局显示脑图', exact: true }).click();
  await expect(page.locator('.case-map-node--module').filter({ hasText: '发票管理' })).toHaveCount(1);
  const instruction = '新增「审计日志」空模块，只创建模块节点，不生成用例。';
  const first = await send(page, instruction, ['CASE_GENERATE', 'CASE_MODIFY']); expect(first.action.type).toBe('module_created');
  await page.getByRole('button', { name: '用例脑图', exact: true }).click();
  const emptyNode = page.locator('.case-map-node--module').filter({ hasText: '审计日志' });
  await expect(emptyNode).toHaveCount(1);
  await expect.poll(async () => (await emptyNode.boundingBox())?.width ?? 0).toBeGreaterThan(100);
  expect(await cases(page)).toEqual(before); await shot(page, '12-empty-module-created');
  let collection = await readCollection(); const nodes = collection.mind_map_notes.filter((n: {kind:string;module:string}) => n.kind === 'module' && n.module === '审计日志'); expect(nodes).toHaveLength(1);
  const repeated = await send(page, instruction, ['CASE_GENERATE', 'CASE_MODIFY']); expect(repeated.action.type).toBe('module_created');
  collection = await readCollection(); expect(collection.mind_map_notes.filter((n: {kind:string;module:string}) => n.kind === 'module' && n.module === '审计日志')).toEqual(nodes);
  expect(await cases(page)).toEqual(before); await shot(page, '13-empty-module-no-duplicate');
  save('empty-module-result', { passed: true, createdNodes: 1, casesAdded: 0, repeatCreatesDuplicate: false });
});
