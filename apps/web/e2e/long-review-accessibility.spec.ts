import { expect, test } from '@playwright/test';

test.use({ viewport: { width: 1366, height: 900 }, video: 'on' });
for (const status of ['ready'] as string[]) {
  test(`long changes support keyboard scrolling and full content: ${status}`, async ({ page }, info) => {
    const base = { title: 'Login succeeds', module: 'Login', priority: 'P1', case_type: '功能', tags: [], preconditions: ['Account ready'], steps: [{ action: 'Submit', expected: 'Success' }], source_refs: [] };
    const cases = [0].map(i => ({ ...base, id: `case${i}`, case_key: `TC-${i}`, revision_number: 1, collection_ids: ['alpha'] }));
    const collection = { id: 'alpha', space_id: 'space', name: 'Review clarity', lifecycle_status: 'maintenance', case_count: 1, mind_map_notes: [] };
    const longSteps=Array.from({length:40},(_,i)=>({action:`Step ${i+1}: submit a uniquely identified request and inspect all response fields`,expected:`Result ${i+1}: response matches the recorded order and account` }));
    const change = { id: 'change', status, items: cases.map((c, i) => ({ ref: c.id, target_type: 'formal', operation: 'modify', status: status === 'applied' && i === 0 ? 'applied' : status === 'ready' ? 'pending' : 'rejected', accepted_fields: status === 'applied' && i === 0 ? ['title'] : [], base_snapshot: c, proposed_snapshot: { ...c, title: 'Improved login', priority: 'P0' }, field_diff: [{field:'steps',before:longSteps,after:longSteps.map(step=>({...step,expected:step.expected+'; ensure no duplicate record'}))}] })) };
    const workspace = { id: 'workspace', space_id: 'space', collection_id: 'alpha', status: 'active', title: 'Review clarity', context: { phase: 'maintenance', active_view: 'plan' }, test_briefs: [], candidates: [], workflow_runs: [], messages: [{ id: 'answer', role: 'assistant', intent: 'CASE_MODIFY', status: status === 'ready' ? 'awaiting_confirmation' : 'completed', content: 'Review changes', metadata: { change_set_id: 'change', operation_id: 'operation' }, citations: [], target_case_ids: ['case0'] }], operation_plan: { operations: [{ id: 'operation', intent: 'CASE_MODIFY', status: status === 'ready' ? 'awaiting_confirmation' : 'completed', related_change_set_id: 'change', target: {}, payload: {}, result: {} }] } };
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
    const before=review.getByRole('region',{name:'Before · Steps and expected results',exact:true});
    await before.focus();
    await expect(before).toBeFocused();
    await before.press('ArrowDown');
    await expect.poll(()=>before.evaluate(el=>el.scrollTop)).toBeGreaterThan(0);
    const expand=review.getByRole('button',{name:'Expand full content · Before · Steps and expected results',exact:true});
    await expand.focus(); await page.keyboard.press('Enter');
    await expect(expand).toHaveCount(0);
    expect(await before.evaluate(el=>el.scrollHeight-el.clientHeight)).toBeLessThanOrEqual(1);
    await expect(before).toContainText('Step 40');
    await page.screenshot({path:info.outputPath('expanded-long-steps.png'),fullPage:true});
    await review.getByRole('button',{name:'Collapse content · Before · Steps and expected results',exact:true}).click();
    expect(await before.evaluate(el=>el.scrollHeight-el.clientHeight)).toBeGreaterThan(0);
    await page.setViewportSize({width:1024,height:768});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(1024);
    const accept=review.getByRole('button',{name:'Accept this case',exact:true});
    await accept.scrollIntoViewIfNeeded();await expect(accept).toBeInViewport();
    await page.screenshot({path:info.outputPath('narrow-long-review.png'),fullPage:true});
  });
}
