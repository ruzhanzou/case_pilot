import { expect, test } from '@playwright/test';
import type { TestCaseDto, ConversationDto, WorkspaceCandidateDto } from '../lib/casepilot-api';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Opt-in: uses the configured live model, real API, and a dedicated collection.
test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1', 'Requires live services and model credentials');
test.use({ viewport: { width: 1440, height: 1000 } });
const api = `${process.env.CASEPILOT_E2E_API_URL ?? 'http://localhost:8101'}/api/v1`;
const evidence = resolve('../../artifacts/real-workspace-acceptance');

test('real chat → review → mind map → confirmed changes → generation', async ({ page }) => {
  test.setTimeout(900_000);
  mkdirSync(evidence, { recursive: true });
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await page.request.post(`${api}/auth/login`, { data: { email: 'demo@casepilot.local', password: 'CasePilot123!' } });
  expect(login.ok()).toBeTruthy();
  const account = await login.json();
  const stamp = Date.now();
  const response = await page.request.post(`${api}/spaces/${account.spaces[0].id}/collections`, { data: { name: `真实联动验收-${stamp}`, lifecycle_status: 'maintenance' } });
  expect(response.ok()).toBeTruthy();
  const collection = await response.json();
  const cases: TestCaseDto[] = [];
  for (let i = 1; i <= 3; i++) {
    const r = await page.request.post(`${api}/collections/${collection.id}/test-cases`, { data: {
      case_key: `LINK-${stamp}-${i}`, title: i < 3 ? '正确账号密码登录成功' : '库存不足禁止下单',
      module: i < 3 ? '账号登录' : '订单库存', priority: 'P1', case_type: '功能',
      preconditions: [i < 3 ? '已注册且启用的账号，处于未登录状态' : '商品库存为零'],
      steps: [{ action: i < 3 ? '输入正确账号密码，点击登录' : '提交数量为1的订单', expected: i < 3 ? '登录成功并进入首页' : '提示库存不足，不创建订单' }],
      source: 'isolated-real-acceptance', tags: ['独立真实验收'],
    } });
    expect(r.ok()).toBeTruthy(); cases.push(await r.json());
  }
  const readCases = async () => (await page.request.get(`${api}/collections/${collection.id}/test-cases`)).json();
  await page.goto(`/workbench/collections/${collection.id}`);
  await expect(page.locator('.principle-workbench')).toBeVisible();
  const workspaceResponse = await page.request.get(`${api}/collections/${collection.id}/workspace`);
  expect(workspaceResponse.ok()).toBeTruthy();
  const workspace = await workspaceResponse.json();
  const cid = workspace.id;
  const records: unknown[] = [];
  const save = () => writeFileSync(`${evidence}/result.json`, JSON.stringify({ collection, conversation_id: cid, url: `http://localhost:3105/workbench/collections/${collection.id}`, records, errors }, null, 2));
  save();
  async function send(content: string, intent: string) {
    const removers = page.getByRole('button', { name: /Remove rewrite target|移除修改目标/ });
    while (await removers.count()) await removers.first().click();
    await page.locator('.principle-composer textarea').fill(content);
    const responsePromise = page.waitForResponse(r => r.url().includes(`/conversations/${cid}/messages`) && r.request().method() === 'POST');
    await page.locator('.principle-composer button[type="submit"]').click();
    const res = await responsePromise;
    expect(res.ok(), await res.text()).toBeTruthy();
    const turn = await res.json();
    const id = turn.assistant_message.id;
    let state!: ConversationDto;
    await expect.poll(async () => {
      state = await (await page.request.get(`${api}/conversations/${cid}`)).json();
      return state.messages.find((m) => m.id === id)?.status;
    }, { timeout: 240_000, intervals: [2000, 4000] }).not.toMatch(/^(queued|pending|running|streaming)$/);
    const assistant = state.messages.find((m) => m.id === id)!;
    records.push({ request: content, expected_intent: intent, assistant, workflow_runs: state.workflow_runs }); save();
    console.log('REAL TURN', intent, assistant.intent, assistant.status);
    expect(assistant.intent).toBe(intent);
    expect(assistant.status).not.toMatch(/failed|cancelled/);
    return assistant;
  }
  await send('查询当前集合有哪些账号登录用例，只查询，不修改。', 'CASE_QUERY');
  expect(await readCases()).toEqual(cases);
  await send('Review 当前整个集合，检查重复冗余用例，说明依据并给出保留建议，只检查不修改。', 'CASE_DEDUP');
  await expect(page.getByRole('button', { name: /View plan in workspace|在工作区查看计划/ }).last()).toBeVisible({ timeout: 30_000 });
  await page.getByRole('button', { name: /View plan in workspace|在工作区查看计划/ }).last().click();
  const plan = page.locator('.case-review-plan');
  await expect(plan).toBeVisible();
  expect(await readCases()).toEqual(cases);
  await plan.getByRole('button', { name: cases[0].case_key, exact: true }).first().click();
  const node = page.locator(`[data-id="case-${cases[0].id}"]`);
  await expect(node).toBeVisible();
  await expect(node).toHaveClass(/selected/);
  await page.screenshot({ path: `${evidence}/01-review-map.png`, fullPage: true });
  await page.getByRole('button', { name: /Case workspace|用例工作区/, exact: true }).click();
  const finding = plan.locator('.case-review-plan__finding').filter({ has: page.getByRole('radio') }).first();
  await finding.getByRole('radio', { name: cases[0].case_key, exact: true }).check();
  await finding.getByRole('button', { name: /Preview changes|预览变更/ }).click();
  await finding.getByRole('button', { name: /Create deletion review|生成删除审阅单/ }).click();
  const review = page.locator('.collection-changes__review');
  await expect(review).toBeVisible();
  await expect(review).toContainText(cases[1].case_key);
  expect(await readCases()).toEqual(cases);
  await review.getByRole('button', { name: /Cancel changes|取消变更/ }).click();
  await expect(review).toHaveCount(0);
  expect(await readCases()).toEqual(cases);
  records.push({ check: 'review-map-selection-and-delete-cancel', passed: true }); save();

  await send(`修改用例 ${cases[2].case_key}：仅将标题改为「库存不足时拒绝创建订单」，其他字段保持不变。`, 'CASE_MODIFY');
  await expect(review).toBeVisible({ timeout: 30_000 });
  expect(await readCases()).toEqual(cases);
  await expect(review).toContainText('库存不足时拒绝创建订单');
  await page.screenshot({ path: `${evidence}/02-modify-review.png`, fullPage: true });
  await review.getByRole('button', { name: /Apply selected changes|应用已选修改/ }).click();
  await expect(review).toHaveCount(0);
  const modified = await readCases();
  expect(modified.find((c: TestCaseDto) => c.id === cases[2].id).title).toBe('库存不足时拒绝创建订单');
  expect(modified.find((c: TestCaseDto) => c.id === cases[2].id).revision_number).toBe(cases[2].revision_number + 1);
  expect(modified.filter((c: TestCaseDto) => c.id !== cases[2].id)).toEqual(cases.slice(0, 2));
  await page.getByRole('button', { name: /Mind map|用例脑图/, exact: true }).click();
  await expect(page.locator(`[data-id="case-${cases[2].id}"]`)).toContainText('库存不足时拒绝创建订单');

  await send(`删除用例 ${cases[1].case_key}，保留其他全部用例。`, 'CASE_DELETE');
  await expect(review).toBeVisible();
  expect(await readCases()).toEqual(modified);
  await review.getByRole('button', { name: /Apply selected deletions|确认删除已选用例/ }).click();
  await expect(review).toHaveCount(0);
  expect((await readCases()).map((c: TestCaseDto) => c.id).sort()).toEqual([cases[0].id, cases[2].id].sort());
  await page.reload();
  await page.getByRole('button', { name: /Mind map|用例脑图/, exact: true }).click();
  await expect(page.locator(`[data-id="case-${cases[1].id}"]`)).toHaveCount(0);
  await expect(page.locator(`[data-id="case-${cases[2].id}"]`)).toContainText('库存不足时拒绝创建订单');
  records.push({ check: 'modify-delete-confirmation-and-reload', passed: true }); save();

  await send('为当前集合新增2条密码重置功能测试用例：已注册邮箱申请重置后收到有效期10分钟的链接；过期链接禁止重置并提示重新申请。生成候选用例供我审阅。', 'CASE_GENERATE');
  await expect(page.getByRole('button', { name: /Confirm and generate|确认并生成用例/ })).toBeVisible({ timeout: 30_000 });
  expect((await readCases()).length).toBe(2);
  await page.getByRole('button', { name: /Confirm and generate|确认并生成用例/ }).click();
  await expect(page.getByRole('button', { name: /Add selected|纳入已选用例/, exact: true })).toBeVisible({ timeout: 600_000 });
  expect((await readCases()).length).toBe(2);
  const generatedState = await (await page.request.get(`${api}/conversations/${cid}`)).json();
  expect(generatedState.candidates.length).toBe(2);
  records.push({ check: 'real-generated-candidates', candidate_count: generatedState.candidates.length, workflows: generatedState.workflow_runs }); save();
  await page.screenshot({ path: `${evidence}/03-candidate-review.png`, fullPage: true });
  await page.getByRole('button', { name: /Add selected|纳入已选用例/, exact: true }).click();
  await expect.poll(async () => (await readCases()).length).toBe(2 + generatedState.candidates.filter((c: WorkspaceCandidateDto) => c.included).length);
  await expect(page).toHaveURL(new RegExp(collection.id));
  await page.getByRole('button', { name: /Mind map|用例脑图/, exact: true }).click();
  await page.reload();
  await expect(page.locator('.principle-workbench')).toBeVisible();
  await page.screenshot({ path: `${evidence}/04-final-workspace.png`, fullPage: true });
  records.push({ check: 'generation-commit-stays-workspace-and-persists', passed: true, final_cases: await readCases() }); save();
  expect(errors).toEqual([]);
});
