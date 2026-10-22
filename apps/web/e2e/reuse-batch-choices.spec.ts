import { expect, test } from '@playwright/test';



test('bulk choices save one version and expose Excel parsing diagnostics', async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  const collection = { id: 'alpha', space_id: 'space', name: '登录', lifecycle_status: 'maintenance', case_count: 0, mind_map_notes: [] };
  const content = { test_object: '登录系统', test_objective: '校验登录', open_questions: [], planning: {
    feature_points: [0, 1].map(i => ({ id: `F${i}`, name: `验证码规则${i}`, module: '登录', description: '', requirement_refs: [] })),
    test_points: ['有效验证码', '过期验证码'].map((title, i) => ({ id: `P${i}`, title, scenario: '提交验证码', objective: title, feature_point_ids: [`F${i}`] })),
  } };
  Object.assign(content.planning, { reuse: { strategy: 'change', decisions: [], user_choices: {}, summary: {}, source_count: 0, import_report: [{ row: 2, valid: true, default_fields: ['priority'], label: 'history.xlsx', sheet: '登录', reason: '' }, { row: 3, valid: false, default_fields: [], label: 'history.xlsx', sheet: '登录', reason: '缺少预期' }] } });
  const workspace = { id: 'workspace', space_id: 'space', collection_id: 'alpha', status: 'active', context: { phase: 'brief_review', active_view: 'plan' }, messages: [], candidates: [], workflow_runs: [], operation_history: [], operation_plan: null,
    test_briefs: [{ id: 'brief', version: 1, status: 'draft', content, markdown_content: '# 登录', created_at: new Date().toISOString() }] };
  const saves: { planning: { reuse: { user_choices: Record<string, string> } } }[] = [];
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = [];
    if (path.endsWith('/auth/me')) data = { id: 'account', display_name: 'QA', spaces: [{ id: 'space', name: 'Space', role: 'owner' }] };
    else if (path.endsWith('/generation-models')) data = { models: [], default_model_id: 'auto' };
    else if (path.endsWith('/spaces/space/collections')) data = [collection];
    else if (path.endsWith('/collections/alpha')) data = collection;
    else if (path.endsWith('/test-briefs') && route.request().method() === 'POST') {
      const saved = route.request().postDataJSON().content;
      saves.push(saved);
      const brief = { ...workspace.test_briefs[0], id: 'brief2', version: 2, content: saved };
      workspace.test_briefs[0].status = "superseded";
      workspace.test_briefs.push(brief);
      data = brief;
    } else if (path.includes('/workspaces/') || path.includes('/conversations/') || path.endsWith('/workspace')) data = workspace;
    await route.fulfill({ json: data });
  });
  await page.goto('/workbench/collections/alpha');
  const map = page.getByRole('region', { name: '测试规划脑图' });
  await expect(map).toBeVisible();
  await map.getByRole('button', { name: '登录系统', exact: true }).click();
  await map.getByRole('button', { name: '不纳入本次', exact: true }).click();
  await expect.poll(() => saves.length).toBe(1);
  expect(saves[0].planning.reuse.user_choices).toEqual({ P0: 'exclude', P1: 'exclude' });
  await expect(page.getByRole('combobox', { name: '测试说明版本' })).toHaveValue('2');
  await expect(map.getByRole('button', { name: '生成选中范围（0）', exact: true })).toBeDisabled();
  await map.getByText('复用检索与附件解析结果', { exact: true }).click();
  await expect(map.getByText(/Excel：识别 1 行，跳过 1 行/)).toBeVisible();
  await expect(map.getByText(/第3行：缺少预期/)).toBeVisible();
  await expect(map.getByText(/第2行：默认字段：优先级P1/)).toBeVisible();
  await page.screenshot({ path: info.outputPath('batch-review.png'), fullPage: true });
});
