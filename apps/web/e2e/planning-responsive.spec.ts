import { expect, test } from '@playwright/test';



for (const width of [1280, 1024, 768]) test(`planning controls remain usable at ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 720 });
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  const collection = { id: 'alpha', space_id: 'space', name: '登录', lifecycle_status: 'maintenance', case_count: 0, mind_map_notes: [] };
  const content = { test_object: '登录系统', test_objective: '校验登录', open_questions: [], planning: {
    feature_points: [0, 1].map(i => ({ id: `F${i}`, name: `验证码规则${i}`, module: '登录', description: '', requirement_refs: [] })),
    test_points: ['有效验证码', '过期验证码'].map((title, i) => ({ id: `P${i}`, title, scenario: '提交验证码', objective: title, feature_point_ids: [`F${i}`] })),
  } };
  Object.assign(content.planning, { reuse: { strategy: 'change', decisions: [], user_choices: {}, summary: {}, source_count: 0 } });
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
  const guidance = page.locator('.principle-brief-strategy');
  await expect(guidance).not.toHaveAttribute('open');
  expect((await guidance.boundingBox())!.height).toBeLessThan(45);
  await guidance.locator('summary').click();
  await expect(guidance.getByText(/点击测试点/)).toBeVisible();
  await guidance.locator('summary').click();
  const toolbar = page.locator('.principle-brief-toolbar');
  expect((await toolbar.boundingBox())!.height).toBeLessThan(150);
  await toolbar.getByText('更多', { exact: true }).click();
  await expect(toolbar.getByRole('button', { name: '复制', exact: true })).toBeVisible();
  await expect(toolbar.getByRole('button', { name: '下载 .md', exact: true })).toBeVisible();
  await toolbar.getByText('更多', { exact: true }).click();
  await expect(toolbar.getByRole('button', { name: '确认选择并生成候选', exact: true })).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  const canvas = await map.locator('.test-planning-canvas').boundingBox();
  expect(canvas!.height).toBeGreaterThanOrEqual(240);
  await page.screenshot({ path: info.outputPath('planning.png'), fullPage: true });
});
