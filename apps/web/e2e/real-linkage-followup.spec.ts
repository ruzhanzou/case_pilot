import { expect, test } from '@playwright/test';
import type { TestCaseDto, ConversationDto } from '../lib/casepilot-api';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const cid = process.env.CASEPILOT_LINKAGE_CONVERSATION;
const api = `${process.env.CASEPILOT_E2E_API_URL ?? 'http://localhost:8101'}/api/v1`;
test.skip(!cid, 'Requires a dedicated acceptance conversation with three seeded cases and a duplicate review');
test.use({ viewport: { width: 1440, height: 1000 }, actionTimeout: 20_000 });
test('real review selection survives navigation; map target drives chat; QA and quality review stay read-only', async ({ page }) => {
  test.setTimeout(600_000);
  await page.request.post(`${api}/auth/login`, { data: { email: 'demo@casepilot.local', password: 'CasePilot123!' } });
  const workspace = await (await page.request.get(`${api}/conversations/${cid}`)).json();
  const readCases = async () => (await page.request.get(`${api}/collections/${workspace.collection_id}/test-cases`)).json();
  const cases: TestCaseDto[] = await readCases();
  expect(cases.length).toBe(3);
  const evidence = resolve('../../artifacts/real-workspace-acceptance');
  mkdirSync(evidence, { recursive: true });
  const records: unknown[] = [];
  const save = () => writeFileSync(`${evidence}/linkage-followup.json`, JSON.stringify({ conversation_id: cid, records }, null, 2));
  await page.goto(`/workbench/conversations/${cid}`);
  await page.getByRole('button', { name: /View plan in workspace|在工作区查看计划/ }).first().click();
  const plan = page.locator('.case-review-plan');
  const first = cases.find((c: TestCaseDto) => c.case_key.endsWith('-1'))!;
  const third = cases.find((c: TestCaseDto) => c.case_key.endsWith('-3'))!;
  await plan.getByRole('radio', { name: first.case_key, exact: true }).check();
  await plan.getByRole('button', { name: first.case_key, exact: true }).first().click();
  await expect(page.locator(`[data-id="case-${first.id}"]`)).toHaveClass(/selected/);
  await page.getByRole('button', { name: /Review plan|检查计划/, exact: true }).click();
  await expect(plan.getByRole('radio', { name: first.case_key, exact: true })).toBeChecked();
  records.push({ check: 'review-choice-preserved-after-map-navigation', passed: true }); save();
  await page.getByRole('button', { name: /Mind map|用例脑图/, exact: true }).click();
  await page.getByRole('textbox', { name: /Search test cases|搜索用例资产/ }).fill(third.title);
  await page.locator(`[data-id="case-${third.id}"] .case-map-node__meta > span`).click();
  await expect(page.locator('.principle-composer')).toContainText(third.title);
  async function send(content: string, expected: string) {
    await page.locator('.principle-composer textarea').fill(content);
    const pending = page.waitForResponse(r => r.url().endsWith(`/conversations/${cid}/messages`) && r.request().method() === 'POST');
    await page.locator('.principle-composer button[type="submit"]').click();
    const res = await pending; expect(res.ok()).toBeTruthy(); const turn = await res.json();
    let state!: ConversationDto;
    await expect.poll(async () => {
      state = await (await page.request.get(`${api}/conversations/${cid}`)).json();
      return state.messages.find((m) => m.id === turn.assistant_message.id)?.status;
    }, { timeout: 240_000, intervals: [2000, 4000] }).not.toMatch(/^(running|pending|queued|streaming)$/);
    const message = state.messages.find((m) => m.id === turn.assistant_message.id)!;
    records.push({ content, expected, message, workflows: state.workflow_runs }); save();
    console.log('REAL FOLLOWUP', expected, message.intent, message.status);
    expect(message.intent).toBe(expected); expect(message.status).not.toMatch(/failed|cancelled/);
    return state;
  }
  await send('修改这条用例，仅将标题改为「选中库存用例的明确拒绝结果」，保留其他字段。', 'CASE_MODIFY');
  const review = page.locator('.collection-changes__review');
  await expect(review).toContainText(third.case_key);
  expect(await readCases()).toEqual(cases);
  const saved = await (await page.request.get(`${api}/conversations/${cid}`)).json();
  expect(saved.context.selected_case_id).toBe(third.id);
  await review.getByRole('button', { name: /Apply selected changes|应用已选修改/ }).click();
  await expect(review).toHaveCount(0);
  await expect(page.locator(`[data-id="case-${third.id}"]`)).toContainText('选中库存用例的明确拒绝结果');
  const modified = await readCases();
  expect(modified.filter((c: TestCaseDto) => c.id !== third.id)).toEqual(cases.filter((c: TestCaseDto) => c.id !== third.id));
  await page.reload();
  await expect(page.locator(`[data-id="case-${third.id}"]`)).toHaveClass(/selected/);
  const removers = page.getByRole('button', { name: /Remove rewrite target|移除修改目标/ });
  while (await removers.count()) await removers.first().click();
  await send('审查当前整个集合的用例质量，检查步骤和预期是否清晰、可执行，只输出检查建议。', 'CASE_REVIEW');
  expect(await readCases()).toEqual(modified);
  await page.getByRole('button', { name: /View plan in workspace|在工作区查看计划/ }).last().click();
  await expect(plan).toBeVisible();
  await page.screenshot({ path: `${evidence}/05-quality-review.png`, fullPage: true });
  await send('什么是边界值测试？请简短解释，不要创建或修改用例。', 'KNOWLEDGE_QA');
  expect(await readCases()).toEqual(modified);
  records.push({ check: 'map-modification-and-readonly-intents', passed: true }); save();
});

test('resume completed real generation: review candidates, commit, map, reload', async ({ page }) => {
  test.setTimeout(90_000);
  const evidence = resolve('../../artifacts/real-workspace-acceptance');
  const result = JSON.parse(readFileSync(`${evidence}/result.json`, 'utf8'));
  await page.request.post(`${api}/auth/login`, { data: { email: 'demo@casepilot.local', password: 'CasePilot123!' } });
  const readCases = async (): Promise<TestCaseDto[]> => (await page.request.get(`${api}/collections/${result.collection.id}/test-cases`)).json();
  const before = await readCases();
  const state: ConversationDto = await (await page.request.get(`${api}/conversations/${result.conversation_id}`)).json();
  expect(state.context.phase).toBe('candidate_review');
  expect(state.candidates.length).toBe(2);
  expect(before.length).toBe(2);
  await page.goto(`/workbench/conversations/${result.conversation_id}`);
  await expect(page.getByRole('button', { name: 'Add selected', exact: true })).toBeVisible();
  await page.screenshot({ path: `${evidence}/03-candidate-review.png`, fullPage: true });
  await page.getByRole('button', { name: 'Add selected', exact: true }).click();
  await expect.poll(async () => (await readCases()).length).toBe(4);
  await expect(page).toHaveURL(new RegExp(result.conversation_id));
  const after = await readCases();
  expect(after.filter(c => before.some(b => b.id === c.id))).toEqual(before);
  await page.getByRole('button', { name: 'Mind map', exact: true }).click();
  for (const c of after) await expect(page.locator(`[data-id="case-${c.id}"]`)).toBeAttached();
  await page.reload();
  for (const c of after) await expect(page.locator(`[data-id="case-${c.id}"]`)).toBeAttached();
  await page.screenshot({ path: `${evidence}/04-final-workspace.png`, fullPage: true });
  result.records.push({ check: 'real-generation-2-candidates-confirmed-4-official-cases-map-reload', passed: true, workflows: state.workflow_runs, final_cases: after });
  writeFileSync(`${evidence}/result.json`, JSON.stringify(result, null, 2));
});

test('applied changes update the older review context', async ({ page }) => {
  const evidence = resolve('../../artifacts/real-workspace-acceptance');
  const result = JSON.parse(readFileSync(`${evidence}/result.json`, 'utf8'));
  await page.request.post(`${api}/auth/login`, { data: { email: 'demo@casepilot.local', password: 'CasePilot123!' } });
  await page.goto(`/workbench/conversations/${result.conversation_id}`);
  await page.getByRole('button', { name: 'View plan in workspace' }).first().click();
  const plan = page.locator('.case-review-plan');
  await expect(plan.getByRole('status')).toContainText('The collection has changed since this review');
  await expect(plan).toContainText('Case reference unavailable · Review again');
  await expect(plan).toContainText('Collection updated');
  await page.screenshot({ path: `${evidence}/06-review-after-changes.png`, fullPage: true });
});

test('dependent review targets committed formal revisions and links back to the map', async ({ page }) => {
  test.setTimeout(300_000);
  const evidence = resolve('../../artifacts/real-workspace-acceptance');
  const result = JSON.parse(readFileSync(`${evidence}/result.json`, 'utf8'));
  await page.request.post(`${api}/auth/login`, { data: { email: 'demo@casepilot.local', password: 'CasePilot123!' } });
  const state: ConversationDto = await (await page.request.get(`${api}/conversations/${result.conversation_id}`)).json();
  const generation = state.operation_plan?.operations.find(op => op.intent === 'CASE_GENERATE' && op.result.test_case_ids);
  expect(generation).toBeTruthy();
  const before: TestCaseDto[] = await (await page.request.get(`${api}/collections/${result.collection.id}/test-cases`)).json();
  // This is the same previous_result selector used when the UI resumes the next operation after commit.
  const started = await page.request.post(`${api}/conversations/${result.conversation_id}/messages`, { data: {
    content: '审查刚才生成的用例质量，给出具体问题和建议。',
    targets: [{ kind: 'previous_result', source_operation_id: generation!.id }],
  } });
  expect(started.ok()).toBeTruthy(); const turn = await started.json();
  let completed!: ConversationDto;
  await expect.poll(async () => {
    completed = await (await page.request.get(`${api}/conversations/${result.conversation_id}`)).json();
    return completed.messages.find(m => m.id === turn.assistant_message.id)?.status;
  }, { timeout: 240_000, intervals: [2000, 4000] }).toBe('completed');
  const message = completed.messages.find(m => m.id === turn.assistant_message.id)!;
  expect(message.intent).toBe('CASE_REVIEW');
  const report = message.metadata.analysis_report as { findings: { case_refs: string[] }[] };
  const refs = report.findings.flatMap(f => f.case_refs);
  expect(refs.length).toBeGreaterThan(0);
  for (const ref of refs) expect(generation!.result.test_case_ids).toContain(ref);
  await page.goto(`/workbench/conversations/${result.conversation_id}`);
  await expect(page.getByText('Candidate cases are ready for review in the workspace.', { exact: true })).toHaveCount(1);
  await page.getByRole('button', { name: 'View plan in workspace' }).last().click();
  const formal = before.find(c => c.id === refs[0])!;
  await page.locator('.case-review-plan').getByRole('button', { name: formal.case_key, exact: true }).first().click();
  await expect(page.locator(`[data-id="case-${formal.id}"]`)).toHaveClass(/selected/);
  expect(await (await page.request.get(`${api}/collections/${result.collection.id}/test-cases`)).json()).toEqual(before);
  result.records.push({ check: 'generation-dependent-review-uses-formal-ids-and-map-links', passed: true, message });
  writeFileSync(`${evidence}/result.json`, JSON.stringify(result, null, 2));
  await page.screenshot({ path: `${evidence}/07-generated-review-map.png`, fullPage: true });
});
