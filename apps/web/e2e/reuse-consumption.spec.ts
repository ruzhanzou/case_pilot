/* eslint-disable @typescript-eslint/no-explicit-any -- Acceptance evidence includes persisted contracts. */
import { expect, test } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import * as XLSX from 'xlsx';

const api = process.env.CASEPILOT_E2E_API_URL ?? 'http://localhost:8015';
const output = path.resolve('../../output/reuse-e2e-20261015');
test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1', 'Requires isolated services and a real model');
test.use({ viewport: { width: 1600, height: 1000 }, trace: 'on' });
test.setTimeout(600_000);

for (const origin of ['asset', 'excel'] as const) {
  test(`${origin}: inspect historical cases, persist choices, create and adopt candidates`, async ({ page }) => {
    await mkdir(output, { recursive: true });
    const errors: string[] = [];
    const stages: string[] = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
    const registered = await page.request.post(`${api}/api/v1/auth/register`, { data: {
      email: `reuse-${origin}-${Date.now()}@casepilot.test`, password: 'CasePilot123!', display_name: '复用验收',
    } });
    expect(registered.status()).toBe(201);
    const account = await registered.json();
    const createCollection = async (name: string) => {
      const response = await page.request.post(`${api}/api/v1/spaces/${account.spaces[0].id}/collections`, { data: { name } });
      expect(response.status()).toBe(201); return response.json();
    };
    const history = await createCollection('星桥登录历史用例');
    const oldCases = [
      { title: '星桥登录：有效验证码登录成功', module: '星桥登录', priority: 'P0', case_type: '功能',
        preconditions: ['手机号已注册，持有刚发送且未使用的正确验证码'],
        steps: [{ action: '输入注册手机号和刚发送的正确验证码，提交登录', expected: '登录成功' }] },
      { title: '星桥登录：验证码超过5分钟失效', module: '星桥登录', priority: 'P1', case_type: '功能',
        preconditions: ['手机号已注册，验证码已发送超过5分钟'],
        steps: [{ action: '输入该手机号及超过5分钟的验证码，提交登录', expected: '登录失败，提示验证码已过期' }] },
    ];
    const originals: any[] = [];
    if (origin === 'asset') for (const data of oldCases) {
      const response = await page.request.post(`${api}/api/v1/collections/${history.id}/test-cases`, { data });
      expect(response.status()).toBe(201); originals.push(await response.json());
    }
    const collection = await createCollection(`星桥新版验收-${origin}`);
    const workspace = await (await page.request.put(`${api}/api/v1/collections/${collection.id}/workspace`)).json();
    const url = `${api}/api/v1/conversations/${workspace.id}`;
    await page.goto(`/workbench/collections/${collection.id}`);
    const composer = page.locator('.principle-composer');
    await expect(composer.locator('textarea')).toBeEnabled({ timeout: 60000 });
    if (origin === 'excel') {
      const book = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(book, XLSX.utils.aoa_to_sheet([
        ['用例编号', '用例名称', '前置条件', '测试步骤', '预期结果', '模块'],
        ...oldCases.map((c, i) => [`OLD-00${i + 1}`, c.title, c.preconditions[0], c.steps[0].action, c.steps[0].expected, c.module]),
      ]), '历史登录');
      const buffer = XLSX.write(book, { type: 'buffer', bookType: 'xlsx' });
      await composer.locator('input[type="file"]').setInputFiles({ name: '星桥历史用例.xlsx', buffer,
        mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
      await expect(composer.locator('.principle-attachment[data-status="ready"]')).toContainText('星桥历史用例.xlsx', { timeout: 90000 });
    }
    const prompt = `为星桥验证码登录新版生成3个测试点和对应候选用例。这是相似需求改版任务，${origin === 'asset' ? '请查询本空间的星桥登录历史用例资产' : '请参考刚上传的历史用例Excel'}，保留适用的核心用例，只对变化部分修改或新增，不覆盖原资产。当前要求：1.已注册手机号输入刚发送、未使用的正确验证码，登录成功，这条规则不变，可直接复用；2.验证码有效期从5分钟改为2分钟，超过2分钟提交登录失败并提示验证码已过期，需修改历史过期用例；3.新增同一手机号发送后60秒内不能重复发送，提示稍后重试，需新增一条。严格只规划这三个场景，不增加其他维度。`;
    const start = Date.now();
    const sent = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/messages'));
    await composer.locator('textarea').fill(prompt);
    await composer.getByRole('button', { name: '发送', exact: true }).click();
    const turn = await (await sent).json();
    expect(turn.operation_plan.operations.map((op: any) => op.intent)).toEqual(["CASE_GENERATE"]);
    let state: any;
    await expect.poll(async () => {
      state = await (await page.request.get(url)).json();
      const run = state.workflow_runs.find((r: any) => r.job_id === turn.action?.job_id)
        ?? state.workflow_runs.findLast((r: any) => r.operation === 'draft_brief');
      if (run?.current_stage && stages.at(-1) !== run.current_stage) stages.push(run.current_stage);
      if (run?.status === 'failed') throw new Error(`Planning failed: ${JSON.stringify(run)}`);
      return state.test_briefs.at(-1)?.content.planning?.reuse?.strategy;
    }, { timeout: 240000, intervals: [1000, 2000] }).toBe('change');
    const planningMs = Date.now() - start;
    const brief = state.test_briefs.at(-1);
    const plan = brief.content.planning;
    await writeFile(path.join(output, `${origin}-planning.json`), JSON.stringify({ plan, planningMs, stages, turn }, null, 2));
    expect(plan.test_points).toHaveLength(3);
    const reusable = plan.reuse.decisions.find((d: any) => d.action === 'reuse');
    const modified = plan.reuse.decisions.find((d: any) => d.action === 'modify');
    const added = plan.reuse.decisions.find((d: any) => d.action === 'new');
    expect(reusable, 'At least one unchanged case must be reusable').toBeTruthy();
    expect(modified, 'Changed expiry must not reuse stale expectations').toBeTruthy();
    expect(added).toBeTruthy();
    expect(reusable.source.kind).toBe(origin === 'asset' ? 'formal' : 'excel');
    await expect(page.getByLabel('筛选处理方式')).toBeVisible();
    await page.getByLabel('筛选处理方式').selectOption('reuse');
    const point = (id: string) => plan.test_points.find((p: any) => p.id === id);
    await page.getByRole('button', { name: `查看复用依据：${point(reusable.point_id).title}`, exact: true }).click();
    const detail = page.getByRole('complementary', { name: '测试点详情' });
    await expect(detail).toContainText(reusable.source.snapshot.title);
    await expect(detail).toContainText(reusable.source.snapshot.steps[0].expected);
    await page.screenshot({ path: path.join(output, `${origin}-inspect.png`), fullPage: true });
    // A reviewer can override and restore the suggestion; both must survive refresh.
    await detail.getByLabel('本次处理方式').selectOption('new');
    await expect(page.getByText('处理方式已保存', { exact: true })).toBeVisible();
    await page.reload();
    await page.getByLabel('筛选处理方式').selectOption('new');
    await page.getByRole('button', { name: `查看复用依据：${point(reusable.point_id).title}`, exact: true }).click();
    await expect(detail.getByLabel('本次处理方式')).toHaveValue('new');
    await detail.getByLabel('本次处理方式').selectOption('suggested');
    await expect(detail.getByLabel('本次处理方式')).toHaveValue('suggested');
    await page.getByLabel('筛选处理方式').selectOption('new');
    await page.getByRole('button', { name: `查看复用依据：${point(added.point_id).title}`, exact: true }).click();
    await detail.getByLabel('本次处理方式').selectOption('exclude');
    await expect(detail.getByLabel('本次处理方式')).toHaveValue('exclude');
    await expect(page.locator('.planning-consumption-summary')).toContainText('纳入 2 个测试点');
    await page.reload();
    await expect(page.locator('.planning-consumption-summary')).toContainText('排除 1 个');
    await page.screenshot({ path: path.join(output, `${origin}-choices.png`), fullPage: true });
    // Real confirm endpoint + worker + candidate persistence, without response mocking.
    const confirming = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/test-briefs/confirm'));
    await page.getByRole('button', { name: '确认选择并生成候选', exact: true }).click();
    const confirmation = await confirming;
    expect(confirmation.status()).toBe(202);
    const generation = await confirmation.json();
    await expect.poll(async () => {
      state = await (await page.request.get(url)).json();
      const run = state.workflow_runs.find((r: any) => r.job_id === generation.action.job_id);
      if (run?.status === 'failed') throw new Error(`Generation failed: ${JSON.stringify(run)}`);
      return run?.status;
    }, { timeout: 180000, intervals: [1000, 2000] }).toBe('completed');
    expect(state.candidates).toHaveLength(2);
    const reused = state.candidates.find((c: any) => c.snapshot.test_point_ids.includes(reusable.point_id));
    expect(reused.snapshot.title).toBe(reusable.source.snapshot.title);
    expect(reused.snapshot.steps.map(({ action, expected }: any) => ({ action, expected }))).toEqual(reusable.source.snapshot.steps.map(({ action, expected }: any) => ({ action, expected })));
    expect(state.candidates.flatMap((c: any) => c.snapshot.test_point_ids)).not.toContain(added.point_id);
    const changed = state.candidates.find((c: any) => c.snapshot.test_point_ids.includes(modified.point_id));
    expect(JSON.stringify({ preconditions: changed.snapshot.preconditions, steps: changed.snapshot.steps })).toMatch(/2\s*分钟|两分钟/);
    expect(JSON.stringify({ preconditions: changed.snapshot.preconditions, steps: changed.snapshot.steps })).not.toMatch(/5\s*分钟|五分钟/);
    await expect(page.getByRole('button', { name: /^采纳(?:所选|已选（2）)$/ })).toBeVisible();
    await page.screenshot({ path: path.join(output, `${origin}-candidates.png`), fullPage: true });
    const committing = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/candidates/commit'));
    await page.getByRole('button', { name: /^采纳(?:所选|已选（2）)$/ }).click();
    expect((await committing).status()).toBe(200);
    const persisted = await (await page.request.get(`${api}/api/v1/collections/${collection.id}/test-cases`)).json();
    expect(persisted).toHaveLength(2);
    if (origin === 'asset') {
      const unchanged = await (await page.request.get(`${api}/api/v1/collections/${history.id}/test-cases`)).json();
      expect(unchanged.map((c: any) => c.current_revision_id).sort()).toEqual(originals.map(c => c.current_revision_id).sort());
    }
    await page.reload();
    await expect(page.locator('body')).toContainText(reused.snapshot.title);
    await writeFile(path.join(output, `${origin}-result.json`), JSON.stringify({ planningMs, totalMs: Date.now() - start, stages, candidates: state.candidates, persisted, errors }, null, 2));
    expect(errors.filter(e => !e.includes('ResizeObserver'))).toEqual([]);
  });
}
