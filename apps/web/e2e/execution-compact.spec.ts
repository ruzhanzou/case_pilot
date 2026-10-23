import { expect, test } from '@playwright/test';

for (const locale of ['zh-CN', 'en']) for (const width of [1280, 1024, 768, 390]) {
  test(`execution keeps case space at ${width}px in ${locale}`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 720 });
    await page.addInitScript(value => localStorage.setItem('casepilot.locale.v1', value), locale);
    const now = new Date().toISOString();
    const run = {
      id: 'run', collection_id: 'alpha', collection_name: 'Cases', playlist_id: null,
      source_type: 'collection', source_name: 'Life Logger Streaming Mode', source_collection_count: 1,
      description: 'Stream Mode ODP L2+L4 测试', status: 'active', creator_name: 'QA', creator_id: 'account',
      assignee_ids: ['account'], assignee_names: ['QA', 'Reviewer'], can_manage: true, contributor_names: ['QA'],
      created_at: now, last_activity_at: now, completed_at: null,
      records: Array.from({ length: 15 }, (_, i) => ({
        id: `record-${i}`, status: 'not_run', completed_step_ids: [], actual_result: '', defect_ref: '',
        assignee_id: 'account', assignee_name: 'QA', can_edit: true, updated_by_name: 'QA', updated_at: now,
        test_case: { id: `case-${i}`, case_key: `CASE-${i}`, collection_ids: ['alpha'], current_revision_id: `rev-${i}`,
          revision_number: 1, title: `Life Logger: Phase_E2E_Usecase_ODP_Tags_Selective_Logging_Activity_Stationary_and_Location_Home_${i}`,
          module: 'Selective Logging / ODP / Activity + Location', priority: 'P1', case_type: 'functional', tags: [],
          preconditions: ['LifeLogger and required services are ready.'],
          steps: [{ id: 'step', action: 'Start logging', expected: 'Logging starts' }], source: 'manual', source_refs: [],
        },
      })),
    };
    const collection = { id: 'alpha', space_id: 'space', name: 'Cases', lifecycle_status: 'maintenance', case_count: 15, mind_map_notes: [] };
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname;
      let data: unknown = [];
      if (path.endsWith('/auth/me')) data = { id: 'account', display_name: 'QA', spaces: [{ id: 'space', name: 'Quality Space', role: 'owner' }] };
      else if (path.endsWith('/spaces/space/collections')) data = [collection];
      else if (path.endsWith('/collections/alpha')) data = collection;
      else if (path.endsWith('/execution-runs/run')) data = run;
      else if (path.endsWith('/execution-runs')) data = [{ ...run, total_count: 15, not_run_count: 15, passed_count: 0, failed_count: 0, skipped_count: 0, blocked_count: 0 }];
      else if (path.endsWith('/members')) data = [{ account_id: 'account', display_name: 'QA', role: 'owner', email: 'qa@example.com', created_at: now }];
      await route.fulfill({ json: data });
    });
    await page.goto('/executions');
    await page.locator('.execution-task-card__open').click();
    const header = page.locator('.execution-header--detail');
    await expect(header.getByRole('heading', { name: run.description })).toBeVisible();
    await expect(header.locator('.management-kicker')).toHaveCount(0);
    const layout = page.locator('.execution-layout');
    if (width >= 768) {
      const box = (await layout.boundingBox())!;
      expect(box.y).toBeLessThan(220);
      expect(box.height).toBeGreaterThan(480);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    const details = page.locator('.execution-run-info');
    await expect(details).not.toHaveAttribute('open');
    await details.locator('summary').click();
    await expect(details.getByText(/Reviewer/)).toBeVisible();
    await details.locator('summary').click();
    await page.getByRole('button', { name: /Add filter|添加条件/, exact: true }).click();
    await expect(page.getByRole('textbox', { name: /Filter 1 value|条件 1 值/ })).toBeVisible();
    await expect(page.getByRole('combobox', { name: /Filter combination|条件组合方式/ })).toHaveCount(0);
    await page.getByRole('button', { name: /Add filter|添加条件/, exact: true }).click();
    await page.getByRole('combobox', { name: /Filter combination|条件组合方式/ }).selectOption('or');
    await page.getByRole('button', { name: /Clear filters|清空筛选/, exact: true }).click();
    const caseTitle = page.locator('.execution-case h2');
    await caseTitle.scrollIntoViewIfNeeded();
    await expect(caseTitle).toContainText('Life Logger');
    await page.screenshot({ path: info.outputPath('execution.png'), fullPage: true });
  });
}
