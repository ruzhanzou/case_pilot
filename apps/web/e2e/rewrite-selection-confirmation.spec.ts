import { expect, test, type Page } from '@playwright/test';

test.use({ viewport: { width: 1600, height: 1000 } });
async function setup(page: Page, count = 2, previousTask = false, unresolvedCurrent = false) {
  const calls: Record<string, unknown>[] = [];
  const collection = { id: 'alpha', space_id: 'space', name: 'Confirmation selection', lifecycle_status: 'maintenance', case_count: count, mind_map_notes: [] };
  const cases = Array.from({ length: count }, (_, i) => `Case ${i}`).map((title, i) => ({ id: `case${i}`, case_key: `TC-${i}`, title, module: 'Login', priority: 'P1', case_type: '功能', tags: [], preconditions: [], steps: [{ action: 'Login', expected: 'Success' }], current_revision_id: `rev${i}`, revision_number: 1 }));
  const ids = cases.map(item => item.id);
  const selections = Array.from({ length: Math.ceil(count / 100) }, (_, index) => ({ label: 'Cases', target: { kind: 'case', case_ids: ids.slice(index * 100, index * 100 + 100), candidate_refs: [] } }));
  let context = { phase: 'maintenance', active_view: 'list', selected_targets: selections };
  const operation = { id: 'operation', source_message_id: 'user', sequence: 0, intent: 'CASE_MODIFY', status: 'awaiting_target', target: { resolved: !unresolvedCurrent, case_ids: ids, candidate_refs: [] }, payload: { instruction: '步骤更清晰' }, result: {} };
  const operations = previousTask ? [{ ...operation, id: 'previous', intent: 'CASE_QUERY', status: 'completed', target: { resolved: true, case_ids: ['case0'], candidate_refs: [] } }, operation] : [operation];
  const user = { id: 'user', role: 'user', intent: 'CASE_MODIFY', status: 'completed', content: '步骤更清晰', metadata: {}, target_case_ids: [], citations: [] };
  const assistant = { ...user, id: 'answer', role: 'assistant', status: 'awaiting_clarification', content: '请确认本轮修改', metadata: { operation_id: 'operation', modification_confirmation: true } };
  const workspace = () => ({ id: 'workspace', space_id: 'space', collection_id: 'alpha', status: 'active', context, messages: [user, assistant], candidates: [], workflow_runs: [], test_briefs: [], operation_plan: { current_operation_id: 'operation', operations } });
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname; let data: unknown = [];
    if (path.endsWith('/auth/me')) data = { id: 'account', display_name: 'Tester', spaces: [{ id: 'space', name: 'Space', role: 'owner' }] };
    else if (path.endsWith('/generation-models')) data = { models: [], default_model_id: 'auto' };
    else if (path.endsWith('/spaces/space/collections')) data = [collection];
    else if (path.endsWith('/collections/alpha')) data = collection;
    else if (path.endsWith('/collections/alpha/test-cases')) data = cases;
    else if (path.endsWith('/resume')) {
      calls.push(route.request().postDataJSON());
      data = { conversation_id: 'workspace', user_message: user, assistant_message: assistant, intent: 'CASE_MODIFY', action: { type: 'clarification' }, operation_plan: { operations } };
    } else if (path.includes('/conversations/') || path.includes('/workspaces/') || path.endsWith('/workspace')) {
      if (route.request().method() === 'PATCH') context = { ...context, ...route.request().postDataJSON() };
      data = workspace();
    }
    await route.fulfill({ json: data });
  });
  await page.goto('/workbench/collections/alpha');
  const checks = page.locator('.principle-case-row input[type=checkbox]');
  await expect(checks).toHaveCount(count);
  return { calls, checks, confirm: page.getByRole('button', { name: 'Confirm modification', exact: true }) };
}
test('removing a grouped case and confirming previews the changed scope', async ({ page }) => {
  const s = await setup(page);
  await s.checks.nth(0).uncheck();
  await expect(s.checks.nth(0)).not.toBeChecked();
  await expect(s.checks.nth(1)).toBeChecked();
  await s.confirm.click();
  await expect.poll(() => s.calls.length).toBe(1);
  expect(s.calls[0].confirm_modification).toBe(false);
  expect(s.calls[0].targets).toEqual([{ kind: 'case', case_ids: ['case1'], candidate_refs: [] }]);
});
test('unsubmitted requirements cannot execute the old confirmation', async ({ page }) => {
  const s = await setup(page);
  await page.locator('.principle-composer textarea').fill('保持标题不变');
  await s.confirm.click();
  await expect.poll(() => s.calls.length).toBe(1);
  expect(s.calls[0].confirm_modification).toBe(false);
  expect(s.calls[0].content).toBe('保持标题不变');
});
test('clearing every target blocks confirmation instead of modifying the old scope', async ({ page }) => {
  const s = await setup(page);
  await s.checks.nth(0).uncheck(); await s.checks.nth(1).uncheck();
  await s.confirm.click();
  await expect(page.getByText('Select the cases to modify before confirming.', { exact: true })).toBeVisible();
  expect(s.calls).toEqual([]);
});
test('unchanged scope still confirms without an extra preview', async ({ page }) => {
  const s = await setup(page); await s.confirm.click();
  await expect.poll(() => s.calls.length).toBe(1);
  expect(s.calls[0].confirm_modification).toBe(true);
});

test('more than one selection batch survives a clarification reply and reload', async ({ page }) => {
  const s = await setup(page, 101);
  await page.locator('.principle-composer textarea').fill('步骤写清楚');
  await page.locator('.principle-composer button[type=submit]').click();
  await expect.poll(() => s.calls.length).toBe(1);
  await expect(page.locator('.principle-composer textarea')).toBeEnabled();
  await page.reload();
  await page.getByRole('button', { name: 'Test case list', exact: true }).click();
  await expect(page.locator('.principle-case-row input:checked')).toHaveCount(101);
});

test('a resumed task does not inherit the earlier completed operation scope', async ({ page }) => {
  const s = await setup(page, 2, true);
  await page.locator('.principle-composer textarea').fill('步骤写清楚');
  await page.locator('.principle-composer button[type=submit]').click();
  await expect.poll(() => s.calls.length).toBe(1);
  await expect(page.locator('.principle-composer textarea')).toBeEnabled();
  await page.reload();
  await page.getByRole('button', { name: 'Test case list', exact: true }).click();
  await expect(page.locator('.principle-case-row input:checked')).toHaveCount(2);
});
test('an unresolved task does not inherit the earlier completed operation scope', async ({ page }) => {
  const s = await setup(page, 2, true, true);
  await page.locator('.principle-composer textarea').fill('步骤写清楚');
  await page.locator('.principle-composer button[type=submit]').click();
  await expect.poll(() => s.calls.length).toBe(1);
  await expect(page.locator('.principle-composer textarea')).toBeEnabled();
  await page.reload();
  await page.getByRole('button', { name: 'Test case list', exact: true }).click();
  await expect(page.locator('.principle-case-row input:checked')).toHaveCount(2);
});
