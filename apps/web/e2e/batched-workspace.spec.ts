/* eslint-disable @typescript-eslint/no-explicit-any -- Live acceptance evidence. */
import { test, expect } from '@playwright/test';
import { readFileSync, writeFileSync } from 'node:fs';

test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1', 'Requires real deployed model');
test.use({ viewport: { width: 1700, height: 1100 }, trace: 'on' });
test('25 test points publish a durable batch, then rewrite all 25 with batch previews', async ({ page }, info) => {
  test.setTimeout(1500000);
  const api = `${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
  const get = async (path: string): Promise<any> => { const r = await page.request.get(api + path); expect(r.ok(), await r.text()).toBeTruthy(); return r.json(); };
  const post = async (path: string, data: any): Promise<any> => { const r = await page.request.post(api + path, { data }); expect(r.ok(), await r.text()).toBeTruthy(); return r.json(); };
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  const account = await post('/auth/login', { email: 'demo@casepilot.local', password: 'CasePilot123!' });
  const collection = await post(`/spaces/${account.spaces[0].id}/collections`, { name: `分批预览验收-${Date.now()}` });
  const conversation = await post('/conversations', { collection_id: collection.id, title: '25测试点批量生成与改写' });
  const content = JSON.parse(readFileSync(new URL('./fixtures/batch-planning.json', import.meta.url), 'utf8'));
  const feature = { ...content.planning.feature_points[0], id: 'FP-BATCH', name: '批量账号登录', module: '批量账号登录' };
  const points = Array.from({ length: 25 }, (_, i) => ({ ...content.planning.test_points[0], id: `TP-BATCH-${i + 1}`, title: `B${String(i + 1).padStart(2, '0')} 账号qa_batch_${i + 1}正确密码登录`, scenario: `账号qa_batch_${i + 1}已启用未锁定，使用正确密码登录，HTTP 200且返回access_token`, feature_point_ids: [feature.id] }));
  await post(`/workspaces/${conversation.id}/test-briefs`, { content: { test_object: '批量账号登录', test_objective: '按25个测试点生成恰好25条用例，每点1条，标题保留B编号和账号，每条最多2步。', planning: { feature_points: [feature], test_points: points } } });
  const evidence: any = { collectionId: collection.id, conversationId: conversation.id };
  const save = () => writeFileSync(info.outputPath('evidence.json'), JSON.stringify(evidence, null, 2)); save();
  const state = () => get(`/conversations/${conversation.id}`);
  const formal = () => get(`/collections/${collection.id}/test-cases`);
  await page.goto(`/workbench/conversations/${conversation.id}`);
  await page.getByRole('button', { name: '确认规划并生成用例', exact: true }).click();
  await expect.poll(async () => {
    const s = await state(); const failed = s.workflow_runs.find((r: any) => r.status === 'failed'); if (failed) throw new Error(JSON.stringify(failed));
    return s.candidate_history.filter((c: any) => c.status === 'generating').length;
  }, { timeout: 720000, intervals: [1000] }).toBe(20);
  evidence.generationPreview = await state(); save();
  await expect(page.getByTestId('generation-batch-preview')).toBeVisible();
  await expect(page.locator('.task-result-cases').getByRole('button', { name: '纳入已选候选', exact: true })).toHaveCount(0);
  expect(await formal()).toHaveLength(0);
  await page.screenshot({ path: info.outputPath('generation-preview.png'), fullPage: true });
  await page.reload(); await expect(page.getByTestId('generation-batch-preview')).toBeVisible();
  await expect.poll(async () => (await state()).candidates.length, { timeout: 720000, intervals: [1000] }).toBe(25);
  evidence.generated = await state(); save();
  expect(evidence.generated.workflow_runs.find((run: any) => run.operation === "generate").stages.filter((stage: any) => stage.stage === "test_case.generated")).toHaveLength(2);
  expect(new Set(evidence.generated.candidates.flatMap((c: any) => c.snapshot.test_point_ids))).toEqual(new Set(points.map(point => point.id)));
  for (const preview of evidence.generationPreview.candidate_history) expect(evidence.generated.candidates.find((c: any) => c.ref === preview.ref).id).toBe(preview.id);
  await expect(page.locator('.principle-composer textarea')).toBeEnabled({ timeout: 60000 });
  await page.getByRole('button', { name: '纳入已选候选', exact: true }).click();
  await expect.poll(async () => (await formal()).length).toBe(25);
  evidence.original = await formal(); save();
  const composer = page.locator('.principle-composer textarea'); await expect(composer).toBeEnabled();
  await composer.fill('改写当前集合全部25条用例：在每条最后一步预期结果中补充“可在审计日志查询到该账号本次登录成功记录”；保留原有预期和所有其他字段，不新增不删除用例。');
  let response = page.waitForResponse(r => r.request().method() === 'POST' && /\/(messages|resume)$/.test(new URL(r.url()).pathname), { timeout: 180000 });
  await page.locator('.principle-composer button[type=submit]').click();
  let turn = await (await response).json();
  if (turn.assistant_message?.metadata.modification_confirmation) {
    response = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/resume'), { timeout: 180000 });
    await page.getByRole('button', { name: '确认修改并生成建议', exact: true }).click(); turn = await (await response).json();
  }
  evidence.rewriteTurn = turn; save(); expect(turn.action.change_set_id).toBeTruthy();
  const change = () => get(`/case-change-sets/${turn.action.change_set_id}`);
  await expect.poll(async () => { const c = await change(); if (c.status === 'failed') throw new Error(JSON.stringify(c)); return [c.status, c.items.length]; }, { timeout: 720000, intervals: [1000] }).toEqual(['generating', 20]);
  evidence.rewritePreview = await change(); save();
  const earlyApply = await page.request.post(`${api}/case-change-sets/${turn.action.change_set_id}/apply`, { data: {} });
  expect(earlyApply.status()).toBe(409);
  await expect(page.getByTestId('rewrite-batch-preview')).toBeVisible();
  await expect(page.getByRole('button', { name: /一键采纳全部待审阅用例/ })).toHaveCount(0);
  expect(await formal()).toEqual(evidence.original);
  await page.screenshot({ path: info.outputPath('rewrite-preview.png'), fullPage: true });
  await page.reload(); await expect(page.getByTestId('rewrite-batch-preview')).toBeVisible();
  await expect.poll(async () => (await change()).status, { timeout: 720000, intervals: [1000] }).toBe('ready');
  evidence.rewritten = await change(); save(); expect(evidence.rewritten.items).toHaveLength(25);
  for (const item of evidence.rewritten.items) {
    expect(item.proposed_snapshot.steps.at(-1).expected).toContain('审计日志');
    expect(item.field_diff.map((d: any) => d.field)).toEqual(['steps']);
  }
  await expect(composer).toBeEnabled({ timeout: 60000 });
  const notice = page.getByTestId('active-mutation-task-notice'); if (await notice.isVisible()) await notice.getByRole('button', { name: '前往工作区审阅', exact: true }).click();
  await page.getByRole('button', { name: /一键采纳全部待审阅用例/ }).click();
  await expect.poll(async () => (await formal()).filter((c: any) => c.steps.at(-1).expected.includes('审计日志')).length).toBe(25);
  evidence.final = await formal(); save(); await page.screenshot({ path: info.outputPath('final.png'), fullPage: true });
});
