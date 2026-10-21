import { expect, test } from '@playwright/test';

for (const width of [1280, 768]) test(`generation workspace keeps scope compact and sources visible at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  const collection = { id: 'alpha', space_id: 'space', name: '局部重新生成', lifecycle_status: 'maintenance', case_count: 0, mind_map_notes: [] };
  const candidates = ['old', 'new'].map((id, position) => ({ id, ref: `TC-${id}`, version: 1, position, generation_job_id: `job-${id}`, status: 'candidate', included: true, updated_at: '', snapshot: { id: `TC-${id}`, title: `${id}用例`, module: '登录', priority: 'P1', case_type: '功能', preconditions: ['账号可用'], steps: [{ action: '登录', expected: '成功' }], tags: [], source_refs: [], test_point_ids: ['P1'] } }));
  const workspace = {
    id: 'workspace', space_id: 'space', collection_id: 'alpha', status: 'active', title: collection.name,
    context: { phase: 'candidate_review', active_view: 'plan' }, test_briefs: [1, 2].map(version => ({ id: `brief-${version}`, version, status: 'confirmed', source_operation_id: version === 1 ? 'operation-new' : null, markdown_content: '', content: { test_object: '登录', scope: [], open_questions: [], planning: { feature_points: [{ id: 'F1', name: '登录', module: '账号' }], test_points: [{ id: 'P1', title: version === 1 ? '原始登录测试点' : '新版登录测试点', objective: '验证登录', feature_point_ids: ['F1'] }, { id: 'P2', title: '未覆盖测试点', objective: '验证失败', feature_point_ids: ['F1'] }], reuse: { strategy: 'regression', source_count: 1, decisions: [{ point_id: 'P1', action: 'reuse', reason: '核心流程不变', source: { label: '历史Excel', locator: 'Sheet1第2行', snapshot: { title: '登录', preconditions: [], steps: [] } } }] } } } })), candidates, candidate_history: candidates, workflow_runs: [],
    messages: ['old', 'new'].map(id => ({ id: `message-${id}`, role: 'assistant', intent: 'CASE_GENERATE', status: 'completed', content: `${id}候选生成完成`, related_job_id: `job-${id}`, target_case_ids: [], citations: [], metadata: { brief_version: 1, operation_id: `operation-${id}` }, created_at: id === 'old' ? '2026-10-15' : '2026-10-16' })),
    operation_plan: { operations: ['old', 'new'].map((id, sequence) => ({ id: `operation-${id}`, sequence, intent: 'CASE_GENERATE', status: 'completed', related_job_id: `job-${id}`, target: {}, payload: {}, result: { candidate_ids: [id] } })) },
  };
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = [];
    if (path.endsWith('/candidates/commit')) {
      await route.fulfill({ status: 409, json: { detail: 'test_stop_after_capture' } }); return;
    }
    if (path.endsWith('/auth/me')) data = { id: 'account', display_name: 'QA', spaces: [{ id: 'space', name: 'Space', role: 'owner' }] };
    else if (path.endsWith('/generation-models')) data = { models: [], default_model_id: 'auto' };
    else if (path.endsWith('/spaces/space/collections')) data = [collection];
    else if (path.endsWith('/collections/alpha')) data = collection;
    else if (/\/(workspaces|conversations)\//.test(path) || path.endsWith('/workspace')) data = workspace;
    await route.fulfill({ json: data });
  });
  await page.goto('/workbench/collections/alpha');
  const result = page.locator('.task-result-cases');
  await expect(result).toContainText('new用例');
  await expect(result).not.toContainText('old用例');
  await expect(result.locator('summary').first()).toContainText('关联测试点 1 个');
  await expect(result.locator('.task-candidate-count')).toHaveText('1');
  await expect(result.locator('.task-candidate-stats')).toBeVisible();
  await expect(result.locator('summary').first()).toContainText('直接复用');
  await expect(result.locator('summary').first()).toContainText('历史Excel / Sheet1第2行');
  await expect(result.locator('summary').first()).not.toContainText('TC-new');
  const scope = page.locator('details.task-brief-result');
  await expect(scope).not.toHaveAttribute('open');
  await scope.locator('summary').click();
  await expect(scope.getByRole('button', { name: '查看完整说明' })).toBeVisible();
  await scope.locator('summary').click();
  await expect(scope).not.toHaveAttribute('open');
  await page.screenshot({ path: `../../output/generation-workspace-ui/summary-${width}.png`, fullPage: true });
  await result.locator('summary').first().click();
  const pointLinks = result.getByRole('region', { name: '候选关联测试点' });
  await expect(pointLinks).toContainText('直接复用');
  expect((await pointLinks.boundingBox())!.height).toBeLessThan(60);
  await pointLinks.locator('summary').click();
  await expect(pointLinks).toContainText('历史Excel / Sheet1第2行');
  await pointLinks.locator('summary').click();
  await page.screenshot({ path: `../../output/point-relations-compact/candidate-${width}.png`, fullPage: true });
  await pointLinks.getByRole('button', { name: 'V1 · 原始登录测试点' }).click();
  const detail = page.getByRole('complementary', { name: '测试点详情' });
  await expect(detail).toContainText('原始登录测试点');
  await expect(page.getByLabel('测试点覆盖概览')).toContainText('待补齐 1 个测试点');
  await detail.getByRole('button', { name: 'TC-new · new用例', exact: true }).click();
  const reverse = page.getByRole('region', { name: '候选关联测试点' }).last();
  await expect(reverse).toContainText('原始登录测试点');
  await reverse.getByRole('button', { name: 'V1 · 原始登录测试点' }).click();
  await expect(detail).toContainText('原始登录测试点');
  await detail.scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  await page.screenshot({ path: `../../output/point-relations-20261016/candidate-navigation-${width}.png`, fullPage: true });
  await page.getByLabel('测试说明版本', { exact: true }).selectOption('2');
  await expect(detail).toContainText('新版登录测试点');
  await expect(detail.getByRole('region', { name: '关联候选用例' })).toContainText('候选用例（0）');
  await expect(page.getByLabel('测试点覆盖概览')).toContainText('待补齐 2 个测试点');
});
