import { expect, test } from '@playwright/test';

test.use({ viewport: { width: 1600, height: 1000 } });
test('candidate rewrite blocks adoption until review and returns to candidate review', async ({ page }) => {
  let applied = false;
  const base = { title: 'Login', module: 'Account', priority: 'P1', case_type: 'Functional', tags: [], preconditions: ['Account ready'], steps: [{ action: 'Log in', expected: 'Success' }], source_refs: [] };
  const candidates = Array.from({ length: 24 }, (_, i) => ({ id: `candidate-${i}`, ref: `TC-${i}`, position: i, version: 1, included: true, status: 'candidate', generation_job_id: 'generation', snapshot: { ...base } }));
  const collection = { id: 'alpha', space_id: 'space', name: 'Review candidates', lifecycle_status: 'candidate_review', case_count: 0, mind_map_notes: [] };
  const change = () => ({ id: 'change', status: applied ? 'applied' : 'ready', items: [{ ref: 'TC-0', target_type: 'candidate', base_version: 1, status: applied ? 'applied' : 'ready', base_snapshot: base, proposed_snapshot: { ...base, title: 'Improved login' }, field_diff: [{ field: 'title', before: 'Login', after: 'Improved login' }] }] });
  const workspace = () => {
    const operations = [
      { id: 'generate', intent: 'CASE_GENERATE', status: 'awaiting_confirmation', related_job_id: 'generation', target: {}, payload: { task_id: 'generate' }, result: {}, created_at: '2026-10-10T00:00:00Z' },
      { id: 'rewrite', intent: 'CASE_MODIFY', status: applied ? 'completed' : 'awaiting_confirmation', related_change_set_id: 'change', target: {}, payload: { task_id: 'generate', source_operation_id: 'generate' }, result: {}, created_at: '2026-10-10T00:01:00Z' },
    ];
    return { id: 'workspace', space_id: 'space', collection_id: 'alpha', status: 'active', context: { phase: 'candidate_review', active_view: 'plan', active_mutation_task_id: 'generate' }, candidates, test_briefs: [], messages: [], workflow_runs: [], operation_history: operations, operation_plan: { operations } };
  };
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = [];
    if (path.endsWith('/auth/me')) data = { id: 'user', display_name: 'QA', spaces: [{ id: 'space', name: 'Space', role: 'owner' }] };
    else if (path.endsWith('/generation-models')) data = { models: [{ id: 'auto', label: 'Auto' }], default_model_id: 'auto' };
    else if (path.endsWith('/spaces/space/collections')) data = [collection];
    else if (path.endsWith('/collections/alpha')) data = collection;
    else if (path.endsWith('/case-change-sets/change/apply')) {
      applied = true;
      candidates[0].snapshot.title = 'Improved login';
      data = { change_set: change(), test_cases: [], candidate_snapshots: candidates };
    } else if (path.endsWith('/case-change-sets/change')) data = change();
    else if (/\/(workspaces|conversations)\//.test(path) || path.endsWith('/workspace')) data = workspace();
    await route.fulfill({ json: data });
  });
  await page.goto('/workbench/collections/alpha');
  const review = page.getByRole('region', { name: 'Review pending case changes' });
  await expect(review).toBeVisible();
  await page.getByRole('group', { name: 'Result content' }).getByRole('button', { name: 'Candidate cases · 24', exact: true }).click();
  const addCandidates = page.getByRole('button', { name: 'Add selected to collection (24)', exact: true });
  await expect(addCandidates).toBeDisabled();
  await page.getByRole('group', { name: 'Result content' }).getByRole('button', { name: 'Review changes', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Accept all remaining (1)', exact: true })).toBeInViewport();
  await page.getByRole('button', { name: 'Accept all remaining (1)', exact: true }).click();
  await expect(addCandidates).toBeEnabled();
  const activeTask = page.locator('.conversation-task-flow li').filter({ hasText: 'Generate test cases' });
  await expect(activeTask.getByRole('status')).toHaveText('Candidates awaiting review');
  await expect(activeTask).not.toContainText('Awaiting confirmation');
});
