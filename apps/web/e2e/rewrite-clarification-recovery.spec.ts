import { expect, test } from '@playwright/test';

for (const selected of [true, false]) {
  test(`short rewrite reply resumes after reload with scope ${selected ? 'resolved' : 'unresolved'}`, async ({ page }) => {
    const collection = { id: 'alpha', space_id: 'space', name: 'Rewrite recovery', lifecycle_status: 'maintenance', case_count: 1, mind_map_notes: [] };
    const snapshot = { title: '登录成功', module: '登录', priority: 'P1', case_type: '功能', tags: [], preconditions: [], steps: [{ action: '登录', expected: '成功' }] };
    let request: Record<string, unknown> | undefined;
    let context = { phase: 'maintenance', active_view: 'plan', selected_targets: selected ? [{ label: '登录成功', target: { kind: 'case', case_ids: ['case0'] } }] : [] };
    const operation = { id: 'operation', source_message_id: 'user', sequence: 0, intent: 'CASE_MODIFY', status: 'awaiting_target', confidence: 1,
      target: { resolved: selected, case_ids: selected ? ['case0'] : [] }, payload: { instruction: '步骤太简单，丰富以下' }, result: {} };
    const user = { id: 'user', role: 'user', content: '步骤太简单，丰富以下', intent: 'CASE_MODIFY', status: 'completed', metadata: {}, target_case_ids: [], citations: [] };
    const assistant = () => ({ id: request ? 'reply' : 'question', role: 'assistant', content: request ? selected ? '请确认本轮修改：丰富操作细节' : '请选择要修改的用例。' : '希望重点补充哪些内容？',
      intent: 'CASE_MODIFY', status: 'awaiting_clarification', metadata: { operation_id: 'operation', modification_confirmation: Boolean(request && selected) }, target_case_ids: selected ? ['case0'] : [], citations: [] });
    const workspace = () => ({ id: 'workspace', space_id: 'space', collection_id: 'alpha', status: 'active', context, candidates: [], test_briefs: [], workflow_runs: [],
      messages: [user, assistant()], operation_plan: { operations: [operation] } });
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname;
      let data: unknown = [];
      if (path.endsWith('/auth/me')) data = { id: 'account', display_name: 'Tester', spaces: [{ id: 'space', name: 'Space', role: 'owner' }] };
      else if (path.endsWith('/generation-models')) data = { models: [], default_model_id: 'auto' };
      else if (path.endsWith('/spaces/space/collections')) data = [collection];
      else if (path.endsWith('/collections/alpha')) data = collection;
      else if (path.endsWith('/collections/alpha/test-cases')) data = [{ ...snapshot, id: 'case0', case_key: 'TC-1', current_revision_id: 'rev', revision_number: 1 }];
      else if (path.endsWith('/conversation-operations/operation/resume')) {
        request = route.request().postDataJSON();
        data = { conversation_id: 'workspace', user_message: user, assistant_message: assistant(), intent: 'CASE_MODIFY', action: { type: 'clarification' }, operation_plan: { operations: [operation] } };
      } else if (path.includes('/conversations/') || path.includes('/workspaces/') || path.endsWith('/workspace')) {
        if (route.request().method() === 'PATCH') context = { ...context, ...route.request().postDataJSON() };
        data = workspace();
      }
      await route.fulfill({ json: data });
    });
    await page.goto('/workbench/collections/alpha');
    await page.reload();
    await expect(page.locator('.case-task-running')).toContainText('希望重点补充哪些内容？');
    await page.locator('.principle-composer textarea').fill('操作细节');
    const submit = page.locator('.principle-composer button[type="submit"]');
    await expect(submit).toBeEnabled();
    await submit.click();
    await expect.poll(() => request?.content).toBe('操作细节');
    expect(request?.targets).toEqual(selected ? [{ kind: 'case', case_ids: ['case0'] }] : []);
    await expect(page.locator('.case-task-running')).toContainText(selected ? '请确认本轮修改：丰富操作细节' : '请选择要修改的用例。');
  });
}
