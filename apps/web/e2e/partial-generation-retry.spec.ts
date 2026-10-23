import { test, expect } from '@playwright/test';
import { readFileSync, writeFileSync } from 'node:fs';

test.skip(!process.env.CASEPILOT_PARTIAL_GENERATION_FIXTURE, 'Requires a real partial-generation acceptance fixture');
test.setTimeout(600000);
test('natural retry fills missing points and retains successful candidates after reload', async ({page}, info) => {
  const fixture = JSON.parse(readFileSync(process.env.CASEPILOT_PARTIAL_GENERATION_FIXTURE!, 'utf8'));
  expect(fixture.email.endsWith('@casepilot.test')).toBeTruthy();
  const api = `${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  const login = await page.request.post(`${api}/auth/login`, {data: {email: fixture.email, password: 'CasePilot123!'}});
  expect(login.ok()).toBeTruthy();
  const state = async () => { const response = await page.request.get(`${api}/conversations/${fixture.conversation_id}`); expect(response.ok()).toBeTruthy(); return response.json(); };
  const before = await state(); expect(before.candidates).toHaveLength(1);
  await page.goto(`/workbench/collections/${fixture.collection_id}`);
  const composer = page.locator('.principle-composer textarea');
  await composer.fill('重试未完成的生成');
  const response = page.waitForResponse(r => r.url().endsWith('/messages') && r.request().method() === 'POST');
  await page.locator('.principle-composer button[type=submit]').click();
  const received = await response; expect(received.ok(), await received.text()).toBeTruthy();
  const turn = await received.json();
  writeFileSync(info.outputPath('turn.json'), JSON.stringify(turn, null, 2));
  expect(turn.intent).toBe('CASE_GENERATE');
  let after = await state();
  await expect.poll(async () => {
    after = await state();
    const job = after.workflow_runs.find((run: {job_id:string}) => run.job_id === turn.action.job_id);
    if (job?.status === 'failed') throw new Error(JSON.stringify(job));
    return job?.status;
  }, {timeout: 480000}).toBe('completed');
  expect(after.candidates).toHaveLength(2);
  expect(after.candidates.find((item: {id:string}) => item.id === before.candidates[0].id)).toEqual(before.candidates[0]);
  expect(new Set(after.candidates.flatMap((item: {snapshot:{test_point_ids:string[]}}) => item.snapshot.test_point_ids)).size).toBe(2);
  await page.reload();
  await expect(page.getByTestId('workspace-case-sources').locator(':scope > details').filter({has: page.locator('.task-candidate-title')})).toHaveCount(2);
  expect((await state()).candidates).toEqual(after.candidates);
  writeFileSync(info.outputPath('evidence.json'), JSON.stringify({before, after}, null, 2));
  await page.screenshot({path:info.outputPath('recovered.png'),fullPage:true});
});

test('repaired coverage notes no longer report missing candidates', async ({page}, info) => {
  const fixture = JSON.parse(readFileSync(process.env.CASEPILOT_PARTIAL_GENERATION_FIXTURE!, 'utf8'));
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  const login = await page.request.post(`${process.env.CASEPILOT_E2E_API_URL}/api/v1/auth/login`, {
    data: {email: fixture.email, password: 'CasePilot123!'},
  });
  expect(login.ok()).toBeTruthy();
  await page.goto(`/workbench/collections/${fixture.collection_id}`);
  const results = page.getByTestId('workspace-case-sources');
  await expect(results).toBeVisible();
  await expect(results.locator('.task-candidate-title')).toHaveCount(2);
  await expect(results.locator('.task-generation-notes')).not.toContainText('尚无可采纳用例');
  await expect(results.locator('.task-generation-notes')).not.toContainText('未出现在覆盖矩阵');
  await page.screenshot({path:info.outputPath('coverage-restored.png'),fullPage:true});
});
