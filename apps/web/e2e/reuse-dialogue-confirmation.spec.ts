import { expect, test } from '@playwright/test';

for (const choice of ['reuse', 'fresh'] as const) {
  test(`case collection reuse requires dialogue confirmation: ${choice}`, async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
    const collection = { id: 'alpha', space_id: 'space', name: '账号', lifecycle_status: 'maintenance', case_count: 0, mind_map_notes: [] };
    const content = { test_object: '账号系统', test_objective: '校验登录', open_questions: [], planning: {
      feature_points: [{ id: 'F1', name: '登录', module: '账号', description: '', requirement_refs: [] }],
      test_points: [{ id: 'P1', title: '有效登录', objective: '验证登录', feature_point_ids: ['F1'] }],
      reuse: { strategy: 'regression', source_count: 1, summary: { reuse: 1 }, note: '', decisions: [{
        point_id: 'P1', action: 'reuse', reason: '测试对象一致', test_object_match: 'same',
        source: { kind: 'formal', label: 'TC-001', locator: '版本1', collections: [{ id: 'old', name: '账号回归用例集' }], snapshot: { title: '有效登录', preconditions: [], steps: [] } },
      }] },
    } };
    // A manually revised brief has no corresponding assistant message.
    const workspace = { id: 'workspace', space_id: 'space', collection_id: 'alpha', status: 'active', context: { phase: 'brief_review', active_view: 'plan' }, messages: [], candidates: [], workflow_runs: [], operation_history: [], operation_plan: null,
      test_briefs: [{ id: 'brief', version: 2, status: 'draft', content, markdown_content: '# 账号', created_at: new Date().toISOString() }] };
    const requests: Record<string, unknown>[] = [];
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname;
      let data: unknown = [];
      if (path.endsWith('/auth/me')) data = { id: 'account', display_name: 'QA', spaces: [{ id: 'space', name: 'Space', role: 'owner' }] };
      else if (path.endsWith('/generation-models')) data = { models: [], default_model_id: 'auto' };
      else if (path.endsWith('/spaces/space/collections')) data = [collection];
      else if (path.endsWith('/collections/alpha')) data = collection;
      else if (path.endsWith('/test-briefs/confirm')) {
        requests.push(route.request().postDataJSON());
        data = { action: {} };
      } else if (path.includes('/workspaces/') || path.includes('/conversations/') || path.endsWith('/workspace')) data = workspace;
      await route.fulfill({ json: data });
    });
    await page.goto('/workbench/collections/alpha');
    await page.getByRole('button', { name: '确认选择并生成候选', exact: true }).click();
    const card = page.locator('article').filter({ has: page.getByText('确认复用用例集', { exact: true }) });
    await expect(card).toBeVisible();
    await expect(card).toContainText('账号回归用例集');
    await expect(card).toContainText('本次测试对象：账号系统');
    expect(requests).toHaveLength(0);
    await card.getByRole('button', { name: choice === 'reuse' ? '确认复用并生成' : '不复用，生成新用例', exact: true }).click();
    await expect.poll(() => requests.length).toBe(1);
    expect(requests[0]).toMatchObject({ version: 2, reuse_confirmation: choice });
  });
}
