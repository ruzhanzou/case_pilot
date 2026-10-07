import { expect, test, type Page, type TestInfo } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

test.skip(process.env.CASEPILOT_DEEP_LIVE !== '1', 'Opt in to isolated real-model acceptance');
test.use({ viewport: { width: 1600, height: 1000 }, video: 'on', trace: 'on' });
const api = `${process.env.CASEPILOT_E2E_API_URL ?? 'http://127.0.0.1:8102'}/api/v1`;
const root = resolve('../../artifacts/deep-acceptance-2026-10-07');

type Row = { id: string; case_key: string; title: string; revision_number: number };
async function scenario(page: Page, info: TestInfo) {
  const dir = resolve(root, info.title.split(' ')[0]); mkdirSync(dir, { recursive: true });
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  const errors: string[] = []; const records: unknown[] = [];
  page.on('pageerror', e => errors.push(e.message));
  const login = await page.request.post(`${api}/auth/login`, { data: { email: 'demo@casepilot.local', password: 'CasePilot123!' } });
  expect(login.ok(), await login.text()).toBeTruthy(); const account = await login.json();
  const response = await page.request.post(`${api}/spaces/${account.spaces[0].id}/collections`, { data: { name: `深度验收-${info.title}-${Date.now()}`, lifecycle_status: 'maintenance' } });
  expect(response.ok()).toBeTruthy(); const collection = await response.json();
  const cases: Row[] = [];
  for (let i = 1; i <= 3; i++) {
    const r = await page.request.post(`${api}/collections/${collection.id}/test-cases`, { data: {
      case_key: `DEEP-${Date.now()}-${i}`, title: i < 3 ? '正确账号密码登录成功' : '库存不足禁止下单', module: i < 3 ? '账号登录' : '订单库存', priority: 'P1', case_type: '功能',
      preconditions: [i < 3 ? '已注册并启用的账号，未登录' : '商品库存为零'], steps: [{ action: i < 3 ? '输入正确账号密码，点击登录' : '提交数量为1的订单', expected: i < 3 ? '进入首页' : '提示库存不足，不创建订单' }], source: 'deep-acceptance-isolated', tags: ['深度验收'],
    } }); expect(r.ok()).toBeTruthy(); cases.push(await r.json());
  }
  const workspace = await (await page.request.put(`${api}/collections/${collection.id}/workspace`)).json();
  await page.goto(`/workbench/collections/${collection.id}`);
  await expect(page.locator('.principle-workbench')).toBeVisible();
  const state = async () => (await page.request.get(`${api}/conversations/${workspace.id}`)).json();
  const readCases = async () => (await page.request.get(`${api}/collections/${collection.id}/test-cases`)).json();
  const save = () => writeFileSync(resolve(dir, 'evidence.json'), JSON.stringify({ title: info.title, url: `${process.env.CASEPILOT_E2E_BASE_URL}/workbench/collections/${collection.id}`, collection_id: collection.id, conversation_id: workspace.id, records, errors }, null, 2));
  const shot = async (name: string) => { await page.screenshot({ path: resolve(dir, `${name}.png`), fullPage: true }); save(); };
  const composer = page.locator('.principle-composer textarea');
  async function send(content: string, intent: string, wait = true) {
    await expect(composer).toBeEnabled({ timeout: 30_000 });
    const removers = page.getByRole('button', { name: /移除修改目标|Remove rewrite target/ });
    while (await removers.count()) await removers.first().click();
    await page.getByRole('button', { name: '用例列表', exact: true }).click();
    await composer.fill(content);
    const response = page.waitForResponse(r => r.url().endsWith(`/conversations/${workspace.id}/messages`) && r.request().method() === 'POST');
    await page.locator('.principle-composer button[type="submit"]').click();
    const res = await response; expect(res.ok(), await res.text()).toBeTruthy(); const turn = await res.json();
    records.push({ request: content, expected_intent: intent, turn }); save();
    expect(turn.intent).toBe(intent);
    if (intent !== 'SMALL_TALK') await expect(page.getByRole('button', { name: '用例工作区', exact: true })).toHaveClass(/is-active/);
    else await expect(page.getByRole('button', { name: '用例列表', exact: true })).toHaveClass(/is-active/);
    if (turn.action.job_id && wait) {
      await expect(composer).toBeDisabled();
      await expect(page.getByRole('button', { name: '结束任务', exact: true })).toBeVisible();
      await shot('01-running');
      await expect.poll(async () => (await state()).messages.find((m: { id: string }) => m.id === turn.assistant_message.id)?.status, { timeout: 420_000, intervals: [1500, 3000] }).not.toMatch(/^(running|queued|streaming|pending)$/);
      await expect(composer).toBeEnabled({ timeout: 30_000 });
      const latest = await state(); records.push({ completed_state: latest }); save();
      expect(latest.messages.find((m: { id: string }) => m.id === turn.assistant_message.id)?.status).not.toMatch(/failed|cancelled/);
    }
    return turn;
  }
  info.attachments.push({ name: 'evidence', path: resolve(dir, 'evidence.json'), contentType: 'application/json' });
  save();
  return { cases, collection, state, readCases, send, shot, composer, records, save, errors, workspace };
}

test('01-query 查询自动进入工作区且保持正式数据不变', async ({ page }, info) => {
  const s = await scenario(page, info); await s.send('查询当前集合账号登录模块有哪些用例，只查询不修改', 'CASE_QUERY');
  await expect(page.locator('.case-task-detail')).toContainText('正确账号密码登录成功');
  expect(await s.readCases()).toEqual(s.cases); await s.shot('02-query-result');
  await page.reload(); await expect(page.locator('.case-task-history > button')).toHaveCount(1); expect(s.errors).toEqual([]);
});

test('02-smalltalk 日常对话不创建任务不切换视图', async ({ page }, info) => {
  const s = await scenario(page, info); await s.send('你好', 'SMALL_TALK');
  await expect(page.locator('.principle-message.is-assistant')).toBeVisible();
  expect((await s.state()).operation_history.filter((o: {intent: string}) => o.intent !== 'SMALL_TALK')).toHaveLength(0);
  expect(await s.readCases()).toEqual(s.cases); await s.shot('01-dialogue');
});

test('03-clarify 模糊修改在对话中澄清并恢复同一任务', async ({ page }, info) => {
  const s = await scenario(page, info); const turn = await s.send('修改不存在模块的用例', 'CASE_MODIFY');
  const operation = turn.operation_plan.operations[0]; expect(operation.status).toMatch(/awaiting/);
  await expect(s.composer).toBeEnabled(); await s.shot('01-clarification');
  const button = page.getByRole('button', { name: '在对话区补充信息', exact: true });
  if (await button.isVisible()) await button.click();
  const clarification = `修改用例 ${s.cases[0].case_key}：仅将标题改为「账号验证通过后进入首页」，其他字段保持不变。`;
  await s.composer.fill(clarification);
  const resumed = page.waitForRequest(r => r.url().endsWith(`/conversation-operations/${operation.id}/resume`));
  await page.locator('.principle-composer button[type="submit"]').click();
  expect((await resumed).postDataJSON().content).toBe(clarification);
  await expect(page.locator('.collection-changes__review')).toBeVisible({ timeout: 60_000 });
  await expect(page.locator('.collection-changes__review')).toContainText('账号验证通过后进入首页');
  await expect(page.locator('.principle-message.is-user').last()).toContainText(clarification);
  expect((await s.state()).operation_history).toHaveLength(1);
  expect(await s.readCases()).toEqual(s.cases); await s.shot('02-clarified-proposal');
});

for (const [id, intent, request] of [
  ['04-coverage', 'COVERAGE_ANALYZE', '检查账号登录模块用例的遗漏，只分析并区分明确需求与潜在遗漏，不生成或修改用例。需求：禁用账号不得登录，连续5次密码错误锁定30分钟。'],
  ['05-dedup', 'CASE_DEDUP', '检查账号登录模块重复冗余用例，说明重复依据和独有覆盖，只检查不修改。'],
  ['06-review', 'CASE_REVIEW', '审阅订单库存模块用例质量，检查步骤与预期是否清晰可执行，只审阅不修改。'],
  ['07-qa', 'KNOWLEDGE_QA', '解释什么是边界值测试，请举例说明，不要生成或修改用例。'],
] as const) {
  test(`${id} ${intent} 真实模型结果与详情分区`, async ({ page }, info) => {
    test.setTimeout(480_000); const s = await scenario(page, info); await s.send(request, intent);
    await expect(page.locator('.principle-message.is-assistant').last()).not.toBeEmpty();
    await expect(page.locator('.case-task-detail > header')).toContainText('已完成');
    if (intent !== 'KNOWLEDGE_QA') await expect(page.locator('.case-review-plan')).toBeVisible();
    expect(await s.readCases()).toEqual(s.cases); await s.shot('02-result-and-details');
    await page.reload(); await expect(s.composer).toBeEnabled(); await expect(page.locator('.case-task-history > button')).toHaveCount(1);
    expect(s.errors).toEqual([]);
  });
}

test('08-modify 改写仅确认后落库并保留任务历史', async ({ page }, info) => {
  const s = await scenario(page, info); await s.send(`修改用例 ${s.cases[2].case_key}：仅将标题改为「库存不足时拒绝创建订单」，其他字段保持不变。`, 'CASE_MODIFY');
  const review = page.locator('.collection-changes__review'); await expect(review).toBeVisible();
  expect(await s.readCases()).toEqual(s.cases); await s.shot('01-proposed-change');
  await review.getByRole('button', { name: '应用已选修改', exact: true }).click();
  await expect.poll(async () => (await s.readCases()).find((c: Row) => c.id === s.cases[2].id)?.title).toBe('库存不足时拒绝创建订单');
  await page.getByRole('button', { name: '用例工作区', exact: true }).click();
  await expect(page.locator('.case-task-detail > header')).toContainText('已完成');
  await expect(page.locator('.principle-messages')).toContainText('已应用');
  await page.reload(); await expect(page.locator('.case-task-detail')).toContainText('库存不足时拒绝创建订单'); await s.shot('02-applied-history');
});

test('09-delete 删除取消与确认互不串任务', async ({ page }, info) => {
  const s = await scenario(page, info); await s.send(`删除用例 ${s.cases[1].case_key}，保留其他用例。`, 'CASE_DELETE');
  await page.getByRole('button', { name: '取消变更', exact: true }).click(); expect(await s.readCases()).toEqual(s.cases);
  await s.shot('01-rejected');
  await s.send(`删除用例 ${s.cases[1].case_key}，保留其他用例。`, 'CASE_DELETE');
  await page.getByRole('button', { name: '确认删除已选用例', exact: true }).click();
  await expect.poll(async () => (await s.readCases()).length).toBe(2);
  await page.getByRole('button', { name: '用例工作区', exact: true }).click();
  await expect(page.locator('.case-task-history > button')).toHaveCount(2); await s.shot('02-deleted');
});

test('10-generate 新增模块从测试说明到候选纳入', async ({ page }, info) => {
  test.setTimeout(900_000); const s = await scenario(page, info);
  await s.send('新增密码重置模块的2条用例。需求：已注册邮箱申请重置后收到有效期10分钟的链接；过期链接禁止重置并提示重新申请。仅这两个场景。', 'CASE_GENERATE');
  await expect(page.getByRole('button', { name: '确认范围并生成用例', exact: true })).toBeVisible(); await s.shot('02-brief');
  expect(await s.readCases()).toEqual(s.cases);
  await page.getByRole('button', { name: '确认范围并生成用例', exact: true }).click();
  await expect(s.composer).toBeDisabled(); await s.shot('03-generating');
  await expect(page.getByRole('button', { name: '纳入已选候选', exact: true })).toBeVisible({ timeout: 600_000 });
  const state = await s.state(); s.records.push({ candidates: state.candidates, workflows: state.workflow_runs }); s.save();
  expect(state.candidates.length).toBeGreaterThan(0); expect(await s.readCases()).toEqual(s.cases); await s.shot('04-candidates');
  await page.getByRole('button', { name: '纳入已选候选', exact: true }).click();
  await expect.poll(async () => (await s.readCases()).length).toBe(3 + state.candidates.filter((c: {included: boolean}) => c.included).length);
  await page.getByRole('button', { name: '用例工作区', exact: true }).click(); await page.reload();
  await expect(page.locator('.case-task-detail > header')).toContainText('已完成'); await s.shot('05-incorporated');
  s.records.push({ check: 'explicit-count-and-scope', expected_count: 2, actual_count: state.candidates.length }); s.save();
  expect(state.candidates, '用户明确要求仅两个场景，不能扩展为更多候选').toHaveLength(2);
});

test('11-stop 执行中结束任务刷新后解锁且停止后续任务', async ({ page }, info) => {
  const s = await scenario(page, info); const turn = await s.send('检查账号登录模块遗漏；检查账号登录模块冗余', 'COVERAGE_ANALYZE', false);
  await expect(s.composer).toBeDisabled(); await s.shot('01-running');
  const blocked = await page.request.post(`${api}/conversations/${s.workspace.id}/messages`, { data: { content: '查询用例' } }); expect(blocked.status()).toBe(409);
  await page.reload(); await expect(page.getByRole('button', { name: '结束任务', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '结束任务', exact: true }).click();
  await expect(s.composer).toBeEnabled({ timeout: 30_000 }); await page.reload(); await expect(s.composer).toBeEnabled();
  const state = await s.state(); s.records.push({ ended_state: state }); s.save();
  expect(state.operation_history.find((o: {related_job_id: string}) => o.related_job_id === turn.action.job_id)?.status).toBe('cancelled');
  expect(state.operation_history.every((o: {status: string}) => o.status === 'cancelled')).toBe(true);
  expect(await s.readCases()).toEqual(s.cases); await s.shot('02-ended');
});

test('12-empty-module 创建空模块持久化且不触发生成', async ({ page }, info) => {
  const s = await scenario(page, info); const turn = await s.send('只创建退款模块，不生成用例', 'CASE_GENERATE');
  expect(turn.action.type).toBe('module_created'); expect(turn.action.job_id).toBeUndefined();
  await page.getByRole('button', { name: '用例脑图', exact: true }).click(); await expect(page.locator('.react-flow')).toContainText('退款');
  await page.reload(); await expect(page.locator('.react-flow')).toContainText('退款'); expect(await s.readCases()).toEqual(s.cases); await s.shot('01-empty-module');
});

test('13-module-rewrite 模块改写真实模型逐项预览并确认', async ({ page }, info) => {
  test.setTimeout(480_000); const s = await scenario(page, info);
  await s.send('改写账号登录模块的全部用例：前置条件补充「浏览器已清除登录状态」，预期结果补充「页面右上角显示当前用户名」，保留原有业务语义和编号。', 'CASE_MODIFY');
  const review = page.locator('.collection-changes__review'); await expect(review).toBeVisible();
  expect(await s.readCases()).toEqual(s.cases); await s.shot('02-module-diff');
  await review.getByRole('button', { name: '应用已选修改', exact: true }).click();
  await expect.poll(async () => (await s.readCases()).filter((c: Row) => c.revision_number === 2).length).toBe(2);
  expect((await s.readCases()).find((c: Row) => c.id === s.cases[2].id)).toEqual(s.cases[2]);
  await page.getByRole('button', { name: '用例工作区', exact: true }).click(); await s.shot('03-module-applied');
});

test('14-end-clarification 澄清中的任务可在对话区结束', async ({ page }, info) => {
  const s = await scenario(page, info); await s.send('修改不存在模块的用例', 'CASE_MODIFY');
  await page.locator('.principle-chat').getByRole('button', { name: '结束任务', exact: true }).click();
  await expect(s.composer).toBeEnabled(); expect((await s.state()).operation_history[0].status).toBe('cancelled');
  await s.send('你好', 'SMALL_TALK'); expect(await s.readCases()).toEqual(s.cases); await s.shot('01-clarification-ended');
});

test('15-module-scope 新增模块范围与测试对象正确且可放弃方案', async ({ page }, info) => {
  test.setTimeout(480_000); const s = await scenario(page, info);
  await s.send('新增密码重置模块的2条用例。需求：已注册邮箱申请重置后收到有效期10分钟的链接；过期链接禁止重置并提示重新申请。仅这两个场景。', 'CASE_GENERATE');
  const state = await s.state();
  expect(state.context.generation_target_module_path).toBe('密码重置');
  expect(state.test_briefs.at(-1).content.test_object).toBe('密码重置模块');
  await s.shot('01-correct-module-scope');
  await page.getByRole('button', { name: '放弃本次方案', exact: true }).click();
  await expect.poll(async () => (await s.state()).operation_history.at(-1).status).toBe('cancelled');
  await expect(page.locator('.principle-messages')).toContainText('已放弃本次生成方案');
  expect(await s.readCases()).toEqual(s.cases); await s.shot('02-proposal-discarded');
});
