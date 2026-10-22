/* eslint-disable @typescript-eslint/no-explicit-any -- Isolated search acceptance evidence. */
import { expect, test } from '@playwright/test';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1', 'Requires isolated real services');
test.use({ video: 'off' });
test.setTimeout(600000);
const api = `${process.env.CASEPILOT_E2E_API_URL}/api/v1`;

test('100 assets: natural search, complete confirmation scope and reload', async ({ page }, info) => {
  const output = path.resolve(process.env.CASEPILOT_SEARCH_OUTPUT ?? 'output/search-acceptance-round2-20261021', `search-run-${info.repeatEachIndex}`);
  await mkdir(output, { recursive: true });
  const fixture = JSON.parse(await readFile('output/journey-acceptance-20261021/perf-fixture.json', 'utf8'));
  const evidence: any = { events: [], browserErrors: [] };
  page.on('pageerror', error => evidence.browserErrors.push(error.message));
  const post = async (route: string, data: any) => {
    const response = await page.request.post(api + route, { data });
    expect(response.ok(), await response.text()).toBeTruthy(); return response.json();
  };
  try {
    await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
    await post('/auth/login', { email: fixture.users[0].email, password: 'CasePilot123!' });
    const conversation = await post('/conversations', { space_id: fixture.space, title: '搜索确认验收' });
    evidence.conversation = conversation.id;
    const started = performance.now();
    const search = await post(`/conversations/${conversation.id}/messages`, {
      content: '测试对象：性能账号系统0。找已有用例参考一下，先让我确认可参考资产。',
      source_collection_ids: [fixture.collections[0].id],
    });
    evidence.submissionMs = performance.now() - started;
    const bound = await post(`/conversation-operations/${search.operation_plan.operations[0].id}/confirm-collection`, {
      create_collection_name: `二轮百条资产搜索 ${Date.now()}`,
    });
    const jobId = bound.action.job_id;
    expect(jobId).toBeTruthy();
    let state: any;
    await expect.poll(async () => {
      const response = await page.request.get(`${api}/conversations/${conversation.id}`);
      expect(response.ok()).toBeTruthy(); state = await response.json();
      const run = state.workflow_runs.find((item: any) => item.job_id === jobId);
      if (evidence.events.at(-1)?.stage !== run?.current_stage) evidence.events.push({ stage: run?.current_stage, status: run?.status, elapsedMs: performance.now() - started });
      if (run?.status === 'failed') throw Error(JSON.stringify(run));
      return run?.status;
    }, { timeout: 480000, intervals: [1000] }).toBe('completed');
    evidence.totalMs = performance.now() - started;
    evidence.stages = state.workflow_runs.find((item: any) => item.job_id === jobId)?.stages;
    evidence.jobId = jobId;
    evidence.selection = state.test_briefs.at(-1).content.asset_selection;
    expect(evidence.selection.sources).toHaveLength(100);
    expect(new Set(evidence.selection.sources.map((item: any) => item.key)).size).toBe(100);
    expect(state.candidates).toHaveLength(0);
    await page.setViewportSize({ width: 1024, height: 1000 });
    await page.goto(`/workbench/collections/${state.collection_id}`);
    await expect(page.getByRole('textbox', { name: '对话消息', exact: true })).toBeEnabled();
    await expect(page.getByText('正在恢复工作区', { exact: true })).toBeHidden();
    await page.reload();
    await expect(page.getByRole('textbox', { name: '对话消息', exact: true })).toBeEnabled();
    await expect(page.getByText('正在恢复工作区', { exact: true })).toBeHidden();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const card = page.getByRole('region', { name: '现有用例资产选择' }).first();
    await expect(card).toBeVisible();
    await expect(card).toContainText('已选：100 / 100');
    await expect(card.getByRole('group', { name: '可选资产' }).getByRole('checkbox')).toHaveCount(100);
    await page.screenshot({ path: path.join(output, 'confirmation-1024.png'), fullPage: true });
    expect(evidence.browserErrors).toEqual([]);
    evidence.passed = true;
  } finally {
    await writeFile(path.join(output, 'evidence.json'), JSON.stringify(evidence, null, 2));
  }
});
