import { expect, test } from '@playwright/test';

for (const { targetSpace, bound } of [
  { targetSpace: 'personal', bound: true },
  { targetSpace: 'shared', bound: true },
  { targetSpace: 'personal', bound: false },
]) {
  test(`conversation link waits for its collection in ${targetSpace} space (bound=${bound})`, async ({ page }) => {
    let releaseConversation!: () => void;
    const conversationGate = new Promise<void>(resolve => { releaseConversation = resolve; });
    let releaseCases!: () => void;
    const casesGate = new Promise<void>(resolve => { releaseCases = resolve; });
    const requests: string[] = [];
    const collections = [
      { id: 'wrong', space_id: 'personal', name: 'Wrong default collection', case_count: 0, lifecycle_status: 'maintenance', mind_map_notes: [] },
      { id: 'target', space_id: targetSpace, name: 'Target collection', case_count: 0, lifecycle_status: 'maintenance', mind_map_notes: [] },
    ];
    const conversation = {
      id: 'target-conversation', space_id: targetSpace, collection_id: bound ? 'target' : null,
      title: 'Target conversation', status: 'active', context: { phase: 'maintenance' },
      messages: [], test_briefs: [], candidates: [], workflow_runs: [], operation_history: [], operation_plan: null,
    };
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname;
      requests.push(path);
      let data: unknown = [];
      if (path.endsWith('/auth/me')) data = {
        id: 'user', email: 'test@example.com', display_name: 'Tester',
        spaces: [{ id: 'personal', name: 'Personal', role: 'owner' }, { id: 'shared', name: 'Shared', role: 'member' }],
      };
      else if (path.endsWith('/generation-models')) data = { models: [], default_model_id: 'auto' };
      else if (path.endsWith('/conversations/target-conversation')) {
        await conversationGate;
        data = conversation;
      } else if (path.includes('/spaces/') && path.endsWith('/collections')) {
        data = collections.filter(collection => path.includes(`/spaces/${collection.space_id}/`));
      } else if (path.endsWith('/collections/target/test-cases')) {
        await casesGate;
      } else if (path.endsWith('/collections/target')) data = collections[1];
      else if (path.endsWith('/workspace')) data = { ...conversation, id: 'wrong-conversation', collection_id: 'wrong' };
      await route.fulfill({ json: data });
    });
    await page.goto('/workbench/conversations/target-conversation');
    await expect.poll(() => requests.some(path => path.endsWith('/conversations/target-conversation'))).toBe(true);
    await expect(page.locator('.management-loading--page')).toBeVisible();
    expect(requests.filter(path => path.includes('/collections'))).toEqual([]);
    releaseConversation();
    if (bound) {
      await expect.poll(() => requests.some(path => path.endsWith('/collections/target/test-cases'))).toBe(true);
      await expect(page.locator('.management-loading--page')).toBeVisible();
      await expect(page.getByRole('heading', { name: 'Wrong default collection', exact: true })).toHaveCount(0);
      releaseCases();
      await expect(page.getByRole('heading', { name: 'Target collection', exact: true })).toBeVisible();
    } else {
      await expect(page.locator('.new-conversation__composer')).toBeVisible();
      expect(requests.some(path => path.endsWith('/test-cases'))).toBe(false);
    }
    await expect(page).toHaveURL(/\/workbench\/conversations\/target-conversation$/);
    expect(requests.some(path => path.includes('/collections/wrong/'))).toBe(false);
    expect(requests.some(path => path.endsWith('/workspace'))).toBe(false);
  });
}
