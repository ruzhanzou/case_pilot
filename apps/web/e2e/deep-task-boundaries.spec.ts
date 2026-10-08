import { expect, test, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
const evidence = '../../artifacts/deep-acceptance-2026-10-07/controlled';
test.use({ viewport: { width: 1600, height: 1000 }, video: 'on', trace: 'on' });
test.beforeAll(() => mkdirSync(evidence, { recursive: true }));

async function setup(page: Page, kind: 'failed' | 'ambiguous' | 'no_changes' | 'history') {
  const calls: string[] = [];
  const collection = { id: 'alpha', space_id: 'space', name: '任务边界验收 · 受控场景', lifecycle_status: 'maintenance', case_count: 1, mind_map_notes: [] };
  const snapshot = { title: '登录成功', module: '账号登录', priority: 'P1', case_type: '功能', tags: [], preconditions: [], steps: [{action: '提交凭据', expected: '进入首页'}] };
  let status = kind === 'failed' ? 'failed' : kind === 'ambiguous' ? 'awaiting_intent' : 'completed';
  let intent = kind === 'ambiguous' ? 'UNRESOLVED' : kind === 'history' ? 'CASE_QUERY' : 'CASE_MODIFY';
  let view = 'plan'; let created = false;
  const operation = () => ({ id: 'operation', source_message_id: 'request', sequence: 0, intent, status, confidence: 1, target: {}, payload: {}, result: kind === 'no_changes' ? { no_changes: true } : {}, related_job_id: null, related_change_set_id: kind === 'no_changes' ? 'change' : null, created_at: '2026-10-07T01:00:00Z' });
  const workspace = () => ({ id: 'workspace', space_id: 'space', collection_id: 'alpha', context: { phase: 'maintenance', active_view: view }, candidates: [], test_briefs: [], workflow_runs: [],
    messages: [{ id: 'request', role: 'user', content: '请处理这组用例', intent, status: 'completed', metadata: {}, citations: [], target_case_ids: [] }, { id: 'answer', role: 'assistant', content: status === 'failed' ? '任务处理失败，请重试' : status === 'awaiting_intent' ? '请确认你要执行的操作' : kind === 'no_changes' ? '无需修改，原用例已经满足要求' : '回答已完成', intent, status, metadata: { operation_id: 'operation', ...(kind === 'no_changes' ? { change_set_id: 'change' } : {}) }, citations: [], target_case_ids: [] }, ...(created ? [{ id: 'new-answer', role: 'assistant', content: '找到一条用例', intent: 'CASE_QUERY', status: 'completed', metadata: { operation_id: 'new-operation' }, citations: [], target_case_ids: [] }] : [])],
    operation_history: [operation(), ...(created ? [{ ...operation(), id: 'new-operation', intent: 'CASE_QUERY', created_at: '2026-10-07T02:00:00Z' }] : [])], operation_plan: { operations: [operation()] },
  });
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname; let data: unknown = [];
    if (path.endsWith('/auth/me')) data = { id: 'user', display_name: '验收员', spaces: [{ id: 'space', name: '验收空间', role: 'owner' }] };
    else if (path.endsWith('/generation-models')) data = { models: [{ id: 'auto', label: '受控响应' }], default_model_id: 'auto' };
    else if (path.endsWith('/spaces/space/collections')) data = [collection];
    else if (path.endsWith('/collections/alpha')) data = collection;
    else if (path.endsWith('/collections/alpha/test-cases')) data = [{ ...snapshot, id: 'case', case_key: 'TC-1', current_revision_id: 'rev', revision_number: 1 }];
    else if (path.endsWith('/case-change-sets/change')) data = { id: 'change', status: 'no_changes', items: [{ ref: 'case', target_type: 'formal', operation: 'modify', base_snapshot: snapshot, proposed_snapshot: snapshot, field_diff: [] }] };
    else if (path.endsWith('/resume') || path.endsWith('/confirm-intent')) { calls.push(path); status = 'completed'; intent = route.request().postDataJSON()?.intent ?? intent; data = { intent, action: {}, operation_plan: { operations: [operation()] } }; }
    else if (path.endsWith('/messages') && route.request().method() === 'POST') { created = true; data = { intent: 'CASE_QUERY', action: { type: 'case_query' }, operation_plan: { current_operation_id: 'new-operation', operations: [{ ...operation(), id: 'new-operation' }] } }; }
    else if (path.includes('/workspaces/') || path.includes('/conversations/') || path.endsWith('/workspace')) { if (route.request().method() === 'PATCH') view = route.request().postDataJSON().active_view ?? view; data = workspace(); }
    await route.fulfill({ json: data });
  });
  await page.goto('/workbench/collections/alpha');
  return { calls };
}

test('failed task releases input and retries the same history entry', async ({ page }) => {
  const s = await setup(page, 'failed'); await expect(page.locator('.principle-composer textarea')).toBeEnabled();
  await page.screenshot({ path: `${evidence}/01-failed.png`, fullPage: true });
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(page.locator('.case-task-detail > header')).toContainText('Completed');
  await expect(page.locator('.case-task-history > button')).toHaveCount(1); expect(s.calls).toHaveLength(1);
  await page.screenshot({ path: `${evidence}/02-retried.png`, fullPage: true });
});

test('intent clarification offers every supported intent in conversation', async ({ page }) => {
  await setup(page, 'ambiguous'); const choices = page.locator('.conversation-intent-confirmation');
  await expect(choices.getByRole('button')).toHaveCount(9);
  await page.screenshot({ path: `${evidence}/03-intent-clarification.png`, fullPage: true });
  await page.getByRole('button', { name: 'Test case list', exact: true }).click();
  await choices.getByRole('button', { name: 'Query test cases', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Case workspace', exact: true })).toHaveClass(/is-active/);
  await expect(page.locator('.case-task-detail > header')).toContainText('Completed');
});

test('no-change result is terminal without an apply action', async ({ page }) => {
  await setup(page, 'no_changes'); await expect(page.locator('.case-task-detail')).toContainText('No changes needed');
  await expect(page.locator('.case-task-detail').getByRole('button', { name: 'Apply selected changes' })).toHaveCount(0);
  await expect(page.locator('.principle-composer textarea')).toBeEnabled();
  await page.screenshot({ path: `${evidence}/04-no-changes.png`, fullPage: true });
});

test('new task replaces selected historical detail and opens workspace', async ({ page }) => {
  await setup(page, 'history');
  await page.getByRole('button', { name: /Result history/ }).click();
  await page.locator('.case-task-history > button').click();
  await page.getByRole('button', { name: 'Test case list', exact: true }).click();
  await page.locator('.principle-composer textarea').fill('查询账号登录用例'); await page.locator('.principle-composer button[type="submit"]').click();
  await expect(page.getByRole('button', { name: 'Case workspace', exact: true })).toHaveClass(/is-active/);
  await expect(page.locator('.case-task-detail > header')).toContainText('Query test cases');
  await expect(page.locator('.case-task-history > button')).toHaveCount(2);
  await page.screenshot({ path: `${evidence}/05-auto-focus.png`, fullPage: true });
});
