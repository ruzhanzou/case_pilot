import { expect, test } from '@playwright/test';

test('opening case management during initial loading finishes loading the collection', async ({ page }) => {
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  let requested!: () => void;
  const initialRequest = new Promise<void>(resolve => { requested = resolve; });
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  const collection = { id: 'navigation-race', space_id: 'space', name: '导航时序验收', case_count: 0, lifecycle_status: 'empty', mind_map_notes: [] };
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = [];
    if (path.endsWith('/auth/me')) data = { id: 'tester', email: 'test@example.com', display_name: 'Tester', spaces: [{ id: 'space', name: 'Space', role: 'owner' }] };
    else if (path.endsWith('/generation-models')) data = { models: [], default_model_id: 'auto' };
    else if (path.endsWith('/spaces/space/collections')) { requested(); await gate; data = [collection]; }
    else if (path.endsWith('/collections/navigation-race')) data = collection;
    await route.fulfill({ json: data });
  });
  await page.goto('/');
  await initialRequest;
  await page.getByRole('button', { name: '用例资产管理', exact: true }).click();
  await expect(page).toHaveURL(/\/cases/);
  release();
  await expect(page.getByRole('button', { name: '创建用例集合', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '导航时序验收', exact: true })).toBeVisible();
  await expect(page.getByText('正在准备工作区…', { exact: true })).toHaveCount(0);
});
