/* eslint-disable @typescript-eslint/no-explicit-any -- Persisted model contracts are acceptance evidence. */
import { test, expect } from '@playwright/test';
import { mkdir, readFile, writeFile, rm } from 'node:fs/promises';
import path from 'node:path';
import * as XLSX from 'xlsx';

const dataset = JSON.parse(await readFile(new URL('./fixtures/multi-requirement-reuse.json', import.meta.url), 'utf8'));
const api = process.env.CASEPILOT_E2E_API_URL ?? 'http://localhost:8015';
const output = path.resolve(process.env.CASEPILOT_EVAL_OUTPUT ?? '../../output/multi-requirement-eval-20261015');
test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1', 'Requires isolated API, worker, database and real model');
test.use({ viewport: { width: 1600, height: 1100 }, trace: 'retain-on-failure' });
test.setTimeout(600000);

for (const sample of dataset.samples) test(`${sample.id}: ${sample.name}`, async ({ page }) => {
  await mkdir(output, { recursive: true });
  await rm(path.join(output, `${sample.id}-result.json`), { force: true });
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  const email = `eval-${sample.id}-${Date.now()}@casepilot.test`;
  const reg = await page.request.post(`${api}/api/v1/auth/register`, { data: { email, password: 'CasePilot123!', display_name: '多需求评测' } });
  expect(reg.status()).toBe(201);
  const account = await reg.json();
  const collectionResponse = await page.request.post(`${api}/api/v1/spaces/${account.spaces[0].id}/collections`, { data: { name: sample.name } });
  expect(collectionResponse.status()).toBe(201);
  const collection = await collectionResponse.json();
  const createCase = async (data: any) => {
    const response = await page.request.post(`${api}/api/v1/collections/${collection.id}/test-cases`, { data });
    expect(response.status()).toBe(201); return response.json();
  };
  const originals = [];
  for (const item of sample.assets) originals.push(await createCase(item));
  const workspace = await (await page.request.put(`${api}/api/v1/collections/${collection.id}/workspace`)).json();
  const url = `${api}/api/v1/conversations/${workspace.id}`;
  const getState = async () => (await page.request.get(url)).json();
  await writeFile(path.join(output, `${sample.id}-fixture.json`), JSON.stringify({ email, collection, workspaceId: workspace.id, originals }, null, 2));
  await page.goto(`/workbench/collections/${collection.id}`);
  const composer = page.locator('.principle-composer');
  await expect(composer.locator('textarea')).toBeEnabled({ timeout: 60000 });
  if (sample.excel.length) {
    const book = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(book, XLSX.utils.aoa_to_sheet([
      ['用例编号', '用例名称', '前置条件', '测试步骤', '预期结果', '模块'],
      ...sample.excel.map((c: any, i: number) => [`OLD-${i + 1}`, c.title, c.preconditions.join('；'), c.steps[0].action, c.steps[0].expected, c.module]),
    ]), '历史用例');
    await composer.locator('input[type="file"]').setInputFiles({ name: `${sample.id}-历史用例.xlsx`, buffer: XLSX.write(book, { type: 'buffer', bookType: 'xlsx' }), mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    await expect(composer.locator('.principle-attachment[data-status="ready"]')).toBeVisible({ timeout: 90000 });
  }
  const strategy = sample.strategy === 'fresh' ? '完全全新生成，不参考历史用例。' : sample.strategy === 'regression' ? '这是回归补充任务，查询本空间历史用例，复用不变核心，只补充缺口。' : '这是相似需求变更任务，参考历史用例，只修改变化部分、复用不变部分、补充新增部分。';
  const prompt = `测试对象：${sample.name}。${strategy}${sample.assets.length ? '查询本空间已有用例资产作为生成参考，不需要单独查询结果。' : ''}${sample.excel.length ? '同时参考刚上传的Excel历史用例。' : ''}请生成测试规划，严格只生成3个测试点，每个需求对应1个测试点，确认后再生成3条候选用例。不修改原资产，不扩展需求。需求如下：\n${sample.requirements.map((r: any) => `${r.id}：${r.text}`).join('\n')}`;
  const start = Date.now();
  const sent = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/messages'));
  await composer.locator('textarea').fill(prompt);
  await composer.getByRole('button', { name: '发送', exact: true }).click();
  const turn = await (await sent).json();
  expect(turn.operation_plan.operations.map((op: any) => op.intent)).toEqual(['CASE_GENERATE']);
  let state: any;
  await expect.poll(async () => {
    state = await getState();
    const run = state.workflow_runs.at(-1);
    if (run?.status === 'failed') throw new Error(JSON.stringify(run));
    return state.test_briefs.at(-1)?.content.planning?.reuse?.strategy;
  }, { timeout: 300000, intervals: [1000, 2000] }).toBe(sample.strategy);
  const planningMs = Date.now() - start;
  const brief = state.test_briefs.at(-1);
  const plan = brief.content.planning;
  await writeFile(path.join(output, `${sample.id}-planning.json`), JSON.stringify({ sample, plan, brief, turn, planningMs, workflow: state.workflow_runs }, null, 2));
  expect(plan.test_points).toHaveLength(3);
  const counts = { new: 0, reuse: 0, modify: 0 };
  for (const decision of plan.reuse.decisions) counts[decision.action as keyof typeof counts]++;
  expect(counts).toEqual(sample.expected_counts);
  for (const decision of plan.reuse.decisions.filter((d: any) => d.action !== 'new')) expect(decision.source.snapshot.steps.length).toBeGreaterThan(0);
  if (sample.id === 'E04') expect(plan.reuse.decisions.filter((d: any) => d.source).every((d: any) => d.source.kind === 'excel')).toBeTruthy();
  if (sample.id === 'E05') expect(new Set(plan.reuse.decisions.filter((d: any) => d.source).map((d: any) => d.source.kind))).toEqual(new Set(['formal', 'excel']));

  // Existing formal cases can be linked in the UI without altering their bodies.
  const existing = originals[0] ?? await createCase(sample.excel[0] ?? {
    title: '青禾图书借阅：借阅成功人工用例', module: sample.name, priority: 'P1', case_type: '功能',
    preconditions: ['普通读者当前借阅数量为0，目标图书可借'],
    steps: [{ action: '借阅目标图书', expected: '借阅成功' }],
  });
  const pointId = plan.reuse.decisions.find((d: any) => d.source?.snapshot.title === existing.title)?.point_id ?? plan.test_points[0].id;
  const point = plan.test_points.find((p: any) => p.id === pointId);
  const openPoint = async () => {
    await page.getByLabel('规划展开层级').selectOption('20');
    await page.getByRole('button', { name: `查看复用依据：${point.title}`, exact: true }).click();
  };
  await page.reload();
  await openPoint();
  const detail = page.getByRole('complementary', { name: '测试点详情' });
  await detail.getByLabel('选择关联已有用例').selectOption(existing.id);
  await detail.getByRole('button', { name: '关联已有用例', exact: true }).click();
  await expect(page.getByText('用例已关联测试点', { exact: true })).toBeVisible();
  state = await getState();
  expect(state.planning_case_links).toHaveLength(1);
  expect(state.planning_case_links[0]).toMatchObject({ test_point_id: pointId, test_case_id: existing.id, stale: false });
  await page.reload(); await openPoint();
  await expect(detail.getByRole('region', { name: '关联用例' })).toContainText(existing.title);
  await page.screenshot({ path: path.join(output, `${sample.id}-linked-planning.png`), fullPage: true });
  await detail.getByRole('button', { name: `${existing.case_key} · ${existing.title}`, exact: true }).click();
  await expect(page.getByRole('button', { name: '关闭用例详情', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '结构化测试说明', exact: true }).click();
  const confirming = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/test-briefs/confirm'));
  await page.getByRole('button', { name: '确认选择并生成候选', exact: true }).click();
  const confirmed = await confirming;
  expect(confirmed.status()).toBe(202);
  const generation = await confirmed.json();
  await expect.poll(async () => {
    state = await getState(); const run = state.workflow_runs.find((r: any) => r.job_id === generation.action.job_id);
    if (run?.status === 'failed') throw new Error(JSON.stringify(run)); return run?.status;
  }, { timeout: 240000, intervals: [1000, 2000] }).toBe('completed');
  expect(state.candidates).toHaveLength(3);
  const expectations = state.candidates.map((c: any) => c.snapshot.steps.map((step: any) => step.expected).join("；").replace(/\s/g, ""));
  const permutations = [[0,1,2], [0,2,1], [1,0,2], [1,2,0], [2,0,1], [2,1,0]];
  expect(permutations.some(order => sample.requirements.every((r: any, index: number) =>
    new RegExp(r.expected_result_pattern).test(expectations[order[index]]))), JSON.stringify(expectations)).toBeTruthy();

  const covered = new Set(state.candidates.flatMap((c: any) => c.snapshot.test_point_ids));
  expect(covered).toEqual(new Set(plan.test_points.map((p: any) => p.id)));
  for (const decision of plan.reuse.decisions) {
    const candidate = state.candidates.find((c: any) => c.snapshot.test_point_ids.includes(decision.point_id));
    if (decision.action === 'reuse') {
      expect(candidate.snapshot.title).toBe(decision.source.snapshot.title);
      expect(candidate.snapshot.steps.map(({ action, expected }: any) => ({ action, expected }))).toEqual(decision.source.snapshot.steps.map(({ action, expected }: any) => ({ action, expected })));
    }
    if (decision.action === 'modify') for (const forbidden of sample.forbidden_in_modified) {
      expect(JSON.stringify({ preconditions: candidate.snapshot.preconditions, steps: candidate.snapshot.steps })).not.toContain(forbidden);
    }
  }
  const committing = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/candidates/commit'));
  await page.getByRole('button', { name: /^采纳(?:所选|已选（3）)$/ }).click();
  const committedResponse = await committing;
  expect(committedResponse.status()).toBe(200);
  const committed = await committedResponse.json();
  state = await getState();
  const generatedLinks = state.planning_case_links.filter((l: any) => committed.some((c: any) => c.id === l.test_case_id));
  expect(new Set(generatedLinks.map((l: any) => l.test_point_id))).toEqual(covered);
  expect(new Set(generatedLinks.map((l: any) => l.test_case_id))).toEqual(new Set(committed.map((c: any) => c.id)));
  const persisted = await (await page.request.get(`${api}/api/v1/collections/${collection.id}/test-cases`)).json();
  for (const original of [...originals, existing]) expect(persisted.find((c: any) => c.id === original.id).current_revision_id).toBe(original.current_revision_id);
  await page.reload();
  await page.getByRole('button', { name: '结构化测试说明', exact: true }).click();
  await expect(page.getByRole('region', { name: '测试规划脑图' })).toContainText('已关联正式用例 3 个测试点');
  await openPoint();
  await expect(detail.getByRole('region', { name: '关联用例' })).toContainText(/采纳时自动关联|手动关联/);
  await page.screenshot({ path: path.join(output, `${sample.id}-committed-links.png`), fullPage: true });
  await writeFile(path.join(output, `${sample.id}-result.json`), JSON.stringify({ id: sample.id, name: sample.name, planningMs, totalMs: Date.now() - start, counts, plan, candidates: state.candidate_history, committed, links: state.planning_case_links, errors }, null, 2));
  expect(errors).toEqual([]);
});
