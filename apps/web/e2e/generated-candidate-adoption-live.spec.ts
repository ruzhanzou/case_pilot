/* eslint-disable @typescript-eslint/no-explicit-any -- Live acceptance records candidate snapshots. */
import { expect, test } from '@playwright/test';
import { readFileSync, writeFileSync } from 'node:fs';

test.skip(!process.env.CASEPILOT_GENERATION_EVIDENCE || !process.env.CASEPILOT_TEST_EMAIL,
  'Requires a completed isolated generation fixture and its test account');
test.setTimeout(120000);

test('generated candidates persist through browser adoption and reject duplicate commit', async ({ page }, info) => {
  const evidence = JSON.parse(readFileSync(process.env.CASEPILOT_GENERATION_EVIDENCE!, 'utf8'));
  const api = `${process.env.CASEPILOT_E2E_API_URL ?? 'http://localhost:8000'}/api/v1`;
  const cid = evidence.conversationId;
  const collectionId = evidence.collection.id;
  const login = await page.request.post(`${api}/auth/login`, { data: {
    email: process.env.CASEPILOT_TEST_EMAIL, password: 'CasePilot123!',
  }});
  expect(login.ok()).toBeTruthy();
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  const read = async () => {
    const response = await page.request.get(`${api}/collections/${collectionId}/test-cases`);
    expect(response.ok()).toBeTruthy(); return response.json();
  };
  const state = await (await page.request.get(`${api}/conversations/${cid}`)).json();
  const alreadyAdopted = process.env.CASEPILOT_VERIFY_ADOPTED === '1';
  const candidates = alreadyAdopted ? evidence.generated.candidates : state.candidates;
  expect(candidates).toHaveLength(6);
  expect(await read()).toHaveLength(alreadyAdopted ? 6 : 0);
  await page.goto(`/workbench/collections/${collectionId}`);
  if (!alreadyAdopted) {
    const commit = page.getByRole('button', { name: '纳入正式集合（6）', exact: true });
    await expect(commit).toBeEnabled();
    const accepted = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/candidates/commit'));
    await commit.click();
    expect((await accepted).ok()).toBeTruthy();
    await expect.poll(async () => (await read()).length).toBe(6);
  }
  await page.reload();
  await expect(page.locator('.principle-composer textarea')).toBeEnabled();
  const formal = await read();
  for (const c of candidates) {
    const saved = formal.find((item:any) => item.title === c.snapshot.title);
    expect(saved).toBeTruthy();
    for (const field of ['title', 'module', 'priority', 'case_type', 'preconditions']) {
      expect(saved[field], field).toEqual(c.snapshot[field]);
    }
    expect(saved.steps.map(({ action, expected }:any) => ({ action, expected }))).toEqual(
      c.snapshot.steps.map(({ action, expected }:any) => ({ action, expected })));
  }
  const replay = await page.request.post(`${api}/workspaces/${cid}/candidates/commit`, {
    data: { candidate_ids: candidates.map((c:any) => c.id) },
  });
  expect(replay.status()).toBe(409);
  expect(await read()).toEqual(formal);
  writeFileSync(info.outputPath('evidence.json'), JSON.stringify({ cid, collectionId, alreadyAdopted, candidates, formal, replayStatus: replay.status() }, null, 2));
  await page.screenshot({ path: info.outputPath('final.png'), fullPage: true });
});
