import { expect, test } from '@playwright/test';

test.use({ viewport: { width: 1600, height: 1000 } });

for (const filter of ['search', 'focus'] as const) test(`${filter} limits parent selection and submitted generation scope`, async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  const collection = { id: 'alpha', space_id: 'space', name: '登录', lifecycle_status: 'maintenance', case_count: 0, mind_map_notes: [] };
  const content = { test_object: '登录系统', test_objective: '校验登录', open_questions: [], planning: {
    feature_points: [0, 1].map(i => ({ id: `F${i}`, name: `验证码规则${i}`, module: '登录', description: '', requirement_refs: [] })),
    test_points: ['有效验证码', '过期验证码'].map((title, i) => ({ id: `P${i}`, title, scenario: '提交验证码', objective: title, feature_point_ids: [`F${i}`] })),
  } };
  const workspace = { id: 'workspace', space_id: 'space', collection_id: 'alpha', status: 'active', context: { phase: 'brief_review', active_view: 'plan' }, messages: [], candidates: [], workflow_runs: [], operation_history: [], operation_plan: null,
    test_briefs: [{ id: 'brief', version: 1, status: 'draft', content, markdown_content: '# 登录', created_at: new Date().toISOString() }] };
  const submissions: { selected_test_point_ids: string[] }[] = [];
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = [];
    if (path.endsWith('/auth/me')) data = { id: 'account', display_name: 'QA', spaces: [{ id: 'space', name: 'Space', role: 'owner' }] };
    else if (path.endsWith('/generation-models')) data = { models: [], default_model_id: 'auto' };
    else if (path.endsWith('/spaces/space/collections')) data = [collection];
    else if (path.endsWith('/collections/alpha')) data = collection;
    else if (path.endsWith('/test-briefs/confirm')) {
      submissions.push(route.request().postDataJSON());
      data = { conversation_id: 'workspace', action: {} };
    } else if (path.includes('/workspaces/') || path.includes('/conversations/') || path.endsWith('/workspace')) data = workspace;
    await route.fulfill({ json: data });
  });
  await page.goto('/workbench/collections/alpha');
  const map = page.getByRole('region', { name: '测试规划脑图' });
  await expect(map).toBeVisible();
  if (filter === 'search') await map.getByRole('textbox', { name: '搜索测试规划' }).fill('有效验证码');
  else await map.locator('.planning-node').filter({ has: page.getByRole('button', { name: '验证码规则0', exact: true }) }).getByRole('button', { name: '聚焦分支' }).click();
  await map.getByRole('button', { name: '登录系统', exact: true }).click();
  await expect(map.getByRole('button', { name: '生成选中范围（1）', exact: true })).toBeEnabled();
  await map.getByRole('button', { name: '生成选中范围（1）', exact: true }).click();
  await expect.poll(() => submissions.length).toBe(1);
  expect(submissions[0].selected_test_point_ids).toEqual(['P0']);
  await page.screenshot({ path: test.info().outputPath('filtered-scope.png'), fullPage: true });
});
