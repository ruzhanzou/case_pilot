import { expect, test } from '@playwright/test';

test('task adoption submits only visible selected candidates from that generation', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  const collection = { id: 'alpha', space_id: 'space', name: '局部重新生成', lifecycle_status: 'maintenance', case_count: 0, mind_map_notes: [] };
  const candidates = ['old', 'new'].map((id, position) => ({ id, ref: `TC-${id}`, version: 1, position, generation_job_id: `job-${id}`, status: 'candidate', included: true, updated_at: '', snapshot: { id: `TC-${id}`, title: `${id}用例`, module: '登录', priority: 'P1', case_type: '功能', preconditions: ['账号可用'], steps: [{ action: '登录', expected: '成功' }], tags: [], source_refs: [] } }));
  const workspace = {
    id: 'workspace', space_id: 'space', collection_id: 'alpha', status: 'active', title: collection.name,
    context: { phase: 'candidate_review', active_view: 'plan' }, test_briefs: [], candidates, candidate_history: candidates, workflow_runs: [],
    messages: ['old', 'new'].map(id => ({ id: `message-${id}`, role: 'assistant', intent: 'CASE_GENERATE', status: 'completed', content: `${id}候选生成完成`, related_job_id: `job-${id}`, target_case_ids: [], citations: [], metadata: { operation_id: `operation-${id}` }, created_at: id === 'old' ? '2026-10-15' : '2026-10-16' })),
    operation_plan: { operations: ['old', 'new'].map((id, sequence) => ({ id: `operation-${id}`, sequence, intent: 'CASE_GENERATE', status: 'completed', related_job_id: `job-${id}`, target: {}, payload: {}, result: { candidate_ids: [id] } })) },
  };
  let submitted: unknown;
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = [];
    if (path.endsWith('/candidates/commit')) {
      submitted = route.request().postDataJSON().candidate_ids;
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
  await result.getByRole('button', { name: '纳入正式集合（1）', exact: true }).click();
  await expect.poll(() => submitted).toEqual(['new']);
  expect(workspace.candidates.find(c => c.id === 'old')?.included).toBe(true);
});
