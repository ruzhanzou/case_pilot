import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

test.skip(!process.env.CASEPILOT_SAVED_EXCEL_FIXTURE, 'Requires a persisted synthetic Excel acceptance fixture');
test('applied candidate review opens updated candidates after reload', async ({ page }, info) => {
  const fixture = JSON.parse(readFileSync(process.env.CASEPILOT_SAVED_EXCEL_FIXTURE!, 'utf8'));
  expect(fixture.email.endsWith('@casepilot.test')).toBeTruthy();
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  const login = await page.request.post(`${process.env.CASEPILOT_E2E_API_URL}/api/v1/auth/login`, {
    data: { email: fixture.email, password: 'CasePilot123!' },
  });
  expect(login.ok()).toBeTruthy();
  await page.goto(`/workbench/collections/${fixture.collection_id}`);
  await page.getByRole('button', {name: '查看更新后的候选', exact: true}).click();
  const candidates = page.getByTestId('workspace-case-sources');
  await expect(candidates).toBeVisible();
  await expect(candidates).toContainText('旧版用例.xlsx');
  await expect(candidates).toContainText('参考改写');
  // Source identity lives in expandable provenance, not raw internal JSON.
  const source = candidates.getByTestId('case-source-details').filter({hasText: '旧版用例.xlsx'});
  await candidates.locator(':scope > details').filter({hasText: 'OLD-001'}).locator(':scope > summary').click();
  await source.locator('summary').click();
  await expect(source).toContainText('OLD-001');
  await page.screenshot({path: info.outputPath('updated-candidates.png'), fullPage: true});
});
