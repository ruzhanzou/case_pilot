import { expect, test } from '@playwright/test';

test.use({ viewport: { width: 1366, height: 900 }, video: 'on' });
for (const status of ['ready', 'applied', 'rejected'] as const) {
  test(`review distinguishes suggestions from saved results: ${status}`, async ({ page }, info) => {
    const base = { title: 'Login succeeds', module: 'Login', priority: 'P1', case_type: '功能', tags: [], preconditions: ['Account ready'], steps: [{ action: 'Submit', expected: 'Success' }], source_refs: [] };
    const cases = [0, 1].map(i => ({ ...base, id: `case${i}`, case_key: `TC-${i}`, revision_number: 1, collection_ids: ['alpha'] }));
    const collection = { id: 'alpha', space_id: 'space', name: 'Review clarity', lifecycle_status: 'maintenance', case_count: 2, mind_map_notes: [] };
    const change = { id: 'change', status, items: cases.map((c, i) => ({ ref: c.id, target_type: 'formal', operation: 'modify', status: status === 'applied' && i === 0 ? 'applied' : status === 'ready' ? 'pending' : 'rejected', accepted_fields: status === 'applied' && i === 0 ? ['title'] : [], base_snapshot: c, proposed_snapshot: { ...c, title: 'Improved login', priority: 'P0' }, field_diff: [{ field: 'title', before: c.title, after: 'Improved login' }, { field: 'priority', before: 'P1', after: 'P0' }] })) };
    const workspace = { id: 'workspace', space_id: 'space', collection_id: 'alpha', status: 'active', title: 'Review clarity', context: { phase: 'maintenance', active_view: 'plan' }, test_briefs: [], candidates: [], workflow_runs: [], messages: [{ id: 'answer', role: 'assistant', intent: 'CASE_MODIFY', status: status === 'ready' ? 'awaiting_confirmation' : 'completed', content: 'Review changes', metadata: { change_set_id: 'change', operation_id: 'operation' }, citations: [], target_case_ids: ['case0', 'case1'] }], operation_plan: { operations: [{ id: 'operation', intent: 'CASE_MODIFY', status: status === 'ready' ? 'awaiting_confirmation' : 'completed', related_change_set_id: 'change', target: {}, payload: {}, result: {} }] } };
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname;
      let data: unknown = [];
      if (path.endsWith('/auth/me')) data = { id: 'user', display_name: 'QA', spaces: [{ id: 'space', name: 'Space', role: 'owner' }] };
      else if (path.endsWith('/generation-models')) data = { models: [{ id: 'auto', label: 'Auto' }], default_model_id: 'auto' };
      else if (path.endsWith('/spaces/space/collections')) data = [collection];
      else if (path.endsWith('/collections/alpha')) data = collection;
      else if (path.endsWith('/test-cases')) data = cases;
      else if (path.endsWith('/case-change-sets/change')) data = change;
      else if (/\/(workspaces|conversations)\//.test(path) || path.endsWith('/workspace')) data = workspace;
      await route.fulfill({ json: data });
    });
    await page.goto('/workbench/collections/alpha');
    await page.getByRole('button', { name: 'Case workspace', exact: true }).click();
    const review = page.locator('.collection-changes__review');
    await expect(review).toBeVisible();
    for (const summary of await review.locator('summary').all()) await summary.click();
    if (status === 'ready') {
      await expect(review.getByRole('status')).toHaveText('Selected 2 of 2 cases · 4 changes');
      for (const box of await review.getByRole('checkbox').all()) await box.uncheck();
      await expect(review.getByRole('status')).toHaveText('Selected 0 of 2 cases · 0 changes');
      await expect(review.getByRole('button', { name: 'Apply selected changes', exact: true })).toBeDisabled();
      await review.getByRole('checkbox').first().check();
      await expect(review.getByRole('status')).toHaveText('Selected 1 of 2 cases · 1 changes');
      await expect(review.getByRole('button', { name: 'Apply selected changes', exact: true })).toBeEnabled();
    } else {
      await expect(review.getByText('Applied result', { exact: true })).toHaveCount(status === 'applied' ? 1 : 0);
      await expect(review.getByText('Unapplied suggestion', { exact: true })).toHaveCount(status === 'applied' ? 3 : 4);
      for (const box of await review.getByRole('checkbox').all()) await expect(box).toBeDisabled();
      await expect(review.getByRole('button', { name: 'Apply selected changes', exact: true })).toHaveCount(0);
    }
    await page.screenshot({ path: info.outputPath(`${status}.png`), fullPage: true });
    await page.setViewportSize({ width: 1024, height: 768 });
    await expect(review).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1024);
    await page.screenshot({ path: info.outputPath(`${status}-1024.png`), fullPage: true });
  });
}
