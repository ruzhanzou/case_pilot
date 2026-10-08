import { expect, test } from '@playwright/test';

test.use({ viewport: { width: 1366, height: 900 }, video: 'on' });
for (const status of ['ready'] as string[]) {
  test(`100 case selection survives failed apply and failed result reload: ${status}`, async ({ page }, info) => {
    const base = { title: 'Login succeeds', module: 'Login', priority: 'P1', case_type: '功能', tags: [], preconditions: ['Account ready'], steps: [{ action: 'Submit', expected: 'Success' }], source_refs: [] };
    const cases = Array.from({length: 100}, (_, i) => i).map(i => ({ ...base, id: `case${i}`, case_key: `TC-${i}`, revision_number: 1, collection_ids: ['alpha'] }));
    const collection = { id: 'alpha', space_id: 'space', name: 'Review clarity', lifecycle_status: 'maintenance', case_count: 100, mind_map_notes: [] };
    const change = { id: 'change', status, items: cases.map((c, i) => ({ ref: c.id, target_type: 'formal', operation: 'modify', status: status === 'applied' && i === 0 ? 'applied' : status === 'ready' ? 'pending' : 'rejected', accepted_fields: status === 'applied' && i === 0 ? ['title'] : [], base_snapshot: c, proposed_snapshot: { ...c, title: 'Improved login', priority: 'P0' }, field_diff: [{ field: 'title', before: c.title, after: 'Improved login' }, { field: 'priority', before: 'P1', after: 'P0' }] })) };
    const workspace = { id: 'workspace', space_id: 'space', collection_id: 'alpha', status: 'active', title: 'Review clarity', context: { phase: 'maintenance', active_view: 'plan' }, test_briefs: [], candidates: [], workflow_runs: [], messages: [{ id: 'answer', role: 'assistant', intent: 'CASE_MODIFY', status: status === 'ready' ? 'awaiting_confirmation' : 'completed', content: 'Review changes', metadata: { change_set_id: 'change', operation_id: 'operation' }, citations: [], target_case_ids: cases.map(item=>item.id) }], operation_plan: { operations: [{ id: 'operation', intent: 'CASE_MODIFY', status: status === 'ready' ? 'awaiting_confirmation' : 'completed', related_change_set_id: 'change', target: {}, payload: {}, result: {} }] } };
    workspace.messages.unshift({...workspace.messages[0], id:'old-answer', intent:'CASE_QUERY', status:'completed', content:'Old query result', metadata:{change_set_id:'',operation_id:'old'},target_case_ids:[]});
    let attempts = 0; let submitted: Record<string, string[]> = {};
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname;
      let data: unknown = [];
      if (path.endsWith('/case-change-sets/change/apply')) {
        attempts++; submitted = route.request().postDataJSON().accepted_fields;
        if (attempts === 1) { await route.abort('failed'); return; }
        Object.assign(change, {status:'applied'});
        workspace.messages[1].status = 'completed'; workspace.operation_plan.operations[0].status = 'completed';
        await route.fulfill({json:{change_set:change,test_cases:cases,candidate_snapshots:[]}}); return;
      }
      if (path.endsWith('/case-change-sets/change') && attempts === 1) { await route.abort('failed'); return; }
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
    await expect(review.getByRole('status')).toHaveText('Selected 100 of 100 cases · 200 changes');
    await review.getByRole('button', {name:'Clear matching changes',exact:true}).click();
    await expect(review.getByRole('status')).toHaveText('Selected 0 of 100 cases · 0 changes');
    const search=review.getByRole('textbox', {name:'Find changes by case or module'});
    await search.fill('TC-99');
    await expect(review.locator('details')).toHaveCount(1);
    await review.getByRole('button',{name:'Select matching changes',exact:true}).focus();
    await page.keyboard.press('Enter');
    await expect(review.getByRole('status')).toHaveText('Selected 1 of 100 cases · 2 changes');
    await page.getByRole('button',{name:/Result history/}).click();
    await page.locator('.case-task-history > button').filter({hasText:'Query test cases'}).click();
    await page.getByRole('button',{name:/Result history/}).click();
    await page.locator('.case-task-history > button').filter({hasText:'Modify test cases'}).click();
    await expect(review.getByRole('status')).toHaveText('Selected 1 of 100 cases · 2 changes');
    await search.fill('no such case');
    await expect(review).toContainText('No matching changes');
    await expect(review.getByRole('status')).toHaveText('Selected 1 of 100 cases · 2 changes');
    await search.fill('TC-99');
    await review.locator('summary').click();
    await page.screenshot({path:info.outputPath('100-filtered.png'),fullPage:true});
    const apply=review.getByRole('button',{name:'Apply selected changes',exact:true});
    await apply.click();
    await expect.poll(()=>attempts).toBe(1);
    await expect(apply).toBeEnabled();
    await expect(review.getByRole('status')).toHaveText('Selected 1 of 100 cases · 2 changes');
    await expect(search).toHaveValue('TC-99');
    await expect(review.getByRole('checkbox',{name:'Title',exact:true})).toBeChecked();
    await page.screenshot({path:info.outputPath('offline-selection-retained.png'),fullPage:true});
    await apply.click();
    await expect(page.locator('.collection-changes__badge')).toHaveText('Applied');
    expect(attempts).toBe(2);
    expect(Object.entries(submitted).filter(([,fields])=>fields.length)).toEqual([['case99',['title','priority']]]);
    await page.screenshot({path:info.outputPath('retry-applied.png'),fullPage:true});
  });
}
