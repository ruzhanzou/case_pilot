import { expect, test } from '@playwright/test';

for (const strategy of ['select', 'select_and_generate'] as const) {
  test(`${strategy} confirms assets before any point planning`, async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
    const collection = { id: 'new', space_id: 'space', name: '新集合', lifecycle_status: 'planning', case_count: 0, mind_map_notes: [] };
    const selection = { status: 'awaiting_confirmation', strategy, test_object: '账号系统', sources: [1, 2].map(i => ({
      key: `asset:${i}`, case_id: `case-${i}`, label: `TC-${i}`, match_reason: '相同测试对象', collections: [{ id: `source-${i}`, name: `来源集合${i}` }],
      snapshot: { title: `登录场景${i}`, module: '账号', preconditions: ['已注册'], steps: [{ action: '登录', expected: '成功' }] },
    })) };
    const workspace = { id: 'workspace', space_id: 'space', collection_id: 'new', status: 'active', context: { phase: 'brief_review', active_view: 'plan' }, messages: [], candidates: [], workflow_runs: [], operation_history: [], operation_plan: null,
      test_briefs: [{ id: 'brief', version: 1, status: 'draft', content: { test_object: '账号系统', test_objective: '登录', open_questions: [], planning: {}, generation_strategy: strategy, asset_selection: selection }, markdown_content: '# 账号系统', created_at: new Date().toISOString() }] };
    const calls: { path: string; body: unknown }[] = [];
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname;
      let data: unknown = [];
      if (path.endsWith('/auth/me')) data = { id: 'account', display_name: 'QA', spaces: [{ id: 'space', name: 'Space', role: 'owner' }] };
      else if (path.endsWith('/generation-models')) data = { models: [], default_model_id: 'auto' };
      else if (path.endsWith('/spaces/space/collections')) data = [collection];
      else if (path.endsWith('/collections/new')) data = collection;
      else if (path.endsWith('/generation-assets/confirm') || path.endsWith('/test-briefs/confirm')) {
        calls.push({ path, body: route.request().postDataJSON() });
        data = { action: {} };
      } else if (path.includes('/workspaces/') || path.includes('/conversations/') || path.endsWith('/workspace')) data = workspace;
      await route.fulfill({ json: data });
    });
    await page.goto('/workbench/collections/new');
    const card = page.getByRole('region', { name: '现有用例资产选择' }).first();
    await expect(card).toBeVisible();
    await expect(card).toContainText('来源集合1');
    await expect(card).toContainText('来源集合2');
    const generateButton = page.getByRole('button', { name: '确认规划并生成用例', exact: true });
    if (strategy === 'select') await expect(generateButton).toHaveCount(0);
    else await expect(generateButton).toBeDisabled();
    expect(calls).toHaveLength(0);
    await card.getByRole('checkbox', { name: '登录场景2' }).uncheck();
    await card.getByRole('button', { name: strategy === 'select' ? '确认选用并组成集合' : '确认复用并开始规划' }).click();
    await expect.poll(() => calls.length).toBe(1);
    expect(calls[0]).toEqual({ path: '/api/v1/workspaces/workspace/generation-assets/confirm', body: { version: 1, case_ids: ['case-1'], test_point_ids: [] } });
  });
}
