/* eslint-disable @typescript-eslint/no-explicit-any -- Persisted acceptance evidence. */
import { expect, test } from '@playwright/test';
import { readFileSync, writeFileSync } from 'node:fs';

test.skip(!process.env.CASEPILOT_EXCEL_RESUME, 'Requires completed Excel rewrite evidence');
test.use({ video: 'off' });
test('Excel rewrite survives reload, shows provenance and commits original point bindings', async ({ page }, info) => {
  const evidence = JSON.parse(readFileSync(process.env.CASEPILOT_EXCEL_RESUME!, 'utf8'));
  const api = `${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
  const login = await page.request.post(`${api}/auth/login`, { data: { email: evidence.email, password: 'CasePilot123!' } });
  expect(login.ok()).toBe(true);
  const state = await (await page.request.get(`${api}/conversations/${evidence.conversationId}`)).json();
  expect(state.candidates).toEqual(evidence.after);
  for (const item of state.candidates) {
    expect(item.snapshot.test_point_ids).toEqual(evidence.before.find((original: any) => original.id === item.id).snapshot.test_point_ids);
    expect(item.snapshot.test_point_ids.length).toBeGreaterThan(0);
  }
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  await page.goto(`/workbench/collections/${evidence.collectionId}`);
  await page.getByRole('button', { name: '查看更新后的候选', exact: true }).click();
  const sources = page.getByTestId('workspace-case-sources');
  await expect(sources).toContainText('旧版用例.xlsx');
  await expect(sources).toContainText('参考改写');
  await expect(sources).toContainText('OLD-001');
  await page.screenshot({ path: info.outputPath('excel-rewrite-provenance.png'), fullPage: true });
  const committed = await page.request.post(`${api}/workspaces/${evidence.conversationId}/candidates/commit`, { data: { candidate_ids: state.candidates.map((item: any) => item.id) } });
  expect(committed.ok(), await committed.text()).toBe(true);
  const final = await (await page.request.get(`${api}/conversations/${evidence.conversationId}`)).json();
  const cases = await (await page.request.get(`${api}/collections/${evidence.collectionId}/test-cases`)).json();
  expect(cases).toHaveLength(2);
  const originalPoints = evidence.before.flatMap((item: any) => item.snapshot.test_point_ids);
  for (const item of cases) {
    const links = final.planning_case_links.filter((link: any) => link.test_case_id === item.id);
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) {
      expect(originalPoints).toContain(link.test_point_id);
      expect(link.revision_id).toBe(item.current_revision_id);
      expect(link.stale).toBe(false);
    }
  }
  writeFileSync(info.outputPath('excel-verified.json'), JSON.stringify({ status: 'passed', originalEvidence: process.env.CASEPILOT_EXCEL_RESUME, cases, links: final.planning_case_links }, null, 2));
});
