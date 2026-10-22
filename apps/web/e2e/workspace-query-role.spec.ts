import { test, expect } from '@playwright/test';

test('query workspace filters snapshots without changing cases or exposing adoption', async ({ page }) => {
  const collection = { id: 'alpha', space_id: 'space', name: 'Query acceptance', case_count: 25, lifecycle_status: 'maintenance', mind_map_notes: [] };
  const cases = Array.from({ length: 25 }, (_, index) => ({ id: `case-${index}`, case_key: `TC-${index}`, title: `Login ${index}`, module: index === 0 ? '' : 'Account', priority: 'P1', preconditions: ['Ready'], steps: [{ action: 'Submit', expected: 'Success' }], tags: [], source_refs: [], collection_ids: ['alpha'], revision_number: 1 }));
  const workspace = { id: 'workspace', space_id: 'space', collection_id: 'alpha', status: 'active', title: 'Query', context: { phase: 'maintenance', active_view: 'plan' }, candidates: [], test_briefs: [], workflow_runs: [], operation_plan: null,
    operation_history: [{ id: 'query-op', intent: 'CASE_QUERY', status: 'completed', sequence: 0, payload: {}, target: {}, result: { query_cases: cases }, source_message_id: 'request' }],
    messages: [{ id: 'request', role: 'user', content: 'Find login cases', metadata: {}, citations: [], status: 'completed' }, { id: 'result', role: 'assistant', intent: 'CASE_QUERY', status: 'completed', content: 'Found 25 cases', metadata: { operation_id: 'query-op' }, citations: [] }] };
  const writes: string[] = [];
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (!['GET', 'HEAD'].includes(route.request().method()) && !path.includes('/state') && !path.endsWith('/workspace')) writes.push(path);
    let data: unknown = [];
    if (path.endsWith('/auth/me')) data = { id: 'user', email: 'qa@example.com', display_name: 'QA', spaces: [{ id: 'space', name: 'Space', role: 'owner' }] };
    else if (path.endsWith('/generation-models')) data = { models: [], default_model_id: 'auto' };
    else if (path.endsWith('/spaces/space/collections')) data = [collection];
    else if (path.endsWith('/collections/alpha')) data = collection;
    else if (path.endsWith('/test-cases')) data = cases;
    else if (path.endsWith('/workspace') || path.includes('/conversations/') || path.includes('/workspaces/')) data = workspace;
    await route.fulfill({ json: data });
  });
  await page.goto('/workbench/collections/alpha');
  const results = page.getByRole('region', { name: 'Query results', exact: true });
  await expect(results.locator('tbody tr')).toHaveCount(20);
  await expect(page.locator('.case-task-detail h3')).toHaveText('Query results');
  await results.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(results.locator('tbody tr')).toHaveCount(5);
  await results.getByLabel('Filter by module').selectOption('__unassigned__');
  await expect(results.locator('tbody tr')).toHaveCount(1);
  await expect(results).toContainText('TC-0');
  await results.getByLabel('Search query results').fill('not-found');
  await expect(results).toContainText('No cases match these filters.');
  await results.getByRole('button', { name: 'Clear filters' }).click();
  await expect(results.locator('tbody tr')).toHaveCount(20);
  await expect(results.getByRole('button', { name: /Accept|Apply|Add selected/ })).toHaveCount(0);
  expect(writes).toEqual([]);
});
