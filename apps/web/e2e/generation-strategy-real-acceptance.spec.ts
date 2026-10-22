/* eslint-disable @typescript-eslint/no-explicit-any -- Persist real service contracts as acceptance evidence. */
import { expect, test } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const api = process.env.CASEPILOT_E2E_API_URL ?? 'http://localhost:8018';
const defaultOutput = path.resolve(process.cwd(), process.cwd().endsWith('/apps/web') ? '../../output/generation-strategy-acceptance-20261021' : 'output/generation-strategy-acceptance-20261021');
test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1', 'Requires isolated API, database, Redis and real-model worker');
test.use({ viewport: { width: 1600, height: 1100 }, trace: 'on' });
test.use({ video: 'off' });
test.setTimeout(900_000);

test('real services: default isolation, multi-collection select, confirmed gap generation and visible provenance', async ({ page }, info) => {
  const output = process.env.CASEPILOT_ACCEPTANCE_OUTPUT ? path.resolve(process.env.CASEPILOT_ACCEPTANCE_OUTPUT, `run-${info.repeatEachIndex}`) : defaultOutput;
  await mkdir(output, { recursive: true });
  const evidence: any = { provider: 'real configured provider', cases: [], browserErrors: [] };
  page.on('pageerror', error => evidence.browserErrors.push(error.message));
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  const post = async (route: string, data: any, statuses = [200, 201, 202]) => {
    const response = await page.request.post(`${api}/api/v1${route}`, { data });
    expect(statuses, `${route}: ${await response.text()}`).toContain(response.status());
    return response.json();
  };
  const get = async (route: string) => {
    const response = await page.request.get(`${api}/api/v1${route}`);
    expect(response.status(), route).toBe(200); return response.json();
  };
  const account = await post('/auth/register', { email: `strategy-real-${Date.now()}@casepilot.test`, password: 'CasePilot123!', display_name: '策略端到端验收' });
  const space = account.spaces[0].id;
  evidence.account_id = account.id;
  const origins = [];
  const assets = [];
  for (const [index, name] of ['验收账号系统·登录资产', '验收账号系统·异常资产', '供应商账号系统·相似资产', '未标明对象的旧用例'].entries()) {
    const collection = await post(`/spaces/${space}/collections`, { name }); origins.push(collection);
    const object = index === 2 ? '供应商账号系统' : index === 3 ? '' : '验收账号系统';
    assets.push(await post(`/collections/${collection.id}/test-cases`, {
      title: `${object ? `${object}：` : ''}${index === 1 ? '错误密码登录失败' : '正确密码登录成功'}`,
      module: object || '登录', priority: 'P1', case_type: 'functional',
      preconditions: [object ? `测试对象明确为${object}，已存在启用账号user01，正确密码Good123!` : '已有启用账号与正确密码'],
      steps: [{ action: index === 1 ? '输入user01和错误密码Wrong123!，提交登录' : '输入有效账号及正确密码，提交登录', expected: index === 1 ? '登录失败，提示密码错误，不建立会话' : '登录成功，建立用户会话' }],
    }));
  }
  evidence.origins = origins; evidence.assets = assets;
  const request = '测试对象：验收账号系统。只覆盖三个规则并生成3个测试点和3条用例：1.启用账号user01使用正确密码Good123!登录成功并建立会话；2.user01使用错误密码Wrong123!登录失败，新要求提示凭据无效且不建立会话；3.已登录用户退出后会话失效，访问受保护页面返回登录页。不增加其他范围。';
  const waitJob = async (cid: string, jobId: string) => {
    let state: any;
    await expect.poll(async () => {
      state = await get(`/conversations/${cid}`);
      const run = state.workflow_runs.find((item: any) => item.job_id === jobId);
      if (run?.status === 'failed') throw new Error(JSON.stringify(run));
      return run?.status;
    }, { timeout: 300_000, intervals: [1000, 2000] }).toBe('completed');
    return state;
  };
  try {
    for (const mode of ['generate', 'select', 'select_and_generate']) {
      const conversation = await post('/conversations', { space_id: space, title: `验收-${mode}` });
      // A hidden reuse flag must not enable reuse when the user did not say select.
      const text = mode === 'generate' ? request : (mode === "select" ? `选择现有用例组成新集合。${request}` : `找已有用例参考，复用已有的，规则变化的改写，缺少的补齐。${request}`);
      const turn = await post(`/conversations/${conversation.id}/messages`, { content: text, generation_strategy: 'select', source_collection_ids: origins.map(item => item.id), model_id: 'auto' });
      expect(turn.intent).toBe('CASE_GENERATE');
      const operation = turn.operation_plan.operations[0];
      const bound = await post(`/conversation-operations/${operation.id}/confirm-collection`, { create_collection_name: `验收结果-${mode}` });
      const current = await get(`/conversations/${conversation.id}`);
      await page.goto(`/workbench/collections/${current.collection_id}`);
      let state = await waitJob(conversation.id, bound.action.job_id);
      let brief = state.test_briefs.at(-1);
      const entry: any = { mode, conversation_id: conversation.id, collection_id: current.collection_id, preflight: state };
      evidence.cases.push(entry);
      if (mode === 'generate') {
        expect(brief.content.generation_strategy).toBe('generate');
        expect(brief.content.asset_selection?.status).toBeUndefined();
        expect(brief.content.planning.reuse.strategy).toBe('fresh');
        expect(state.workflow_runs.flatMap((run: any) => run.stages).some((stage: any) => stage.stage === 'cases.searching')).toBe(false);
      } else {
        expect(brief.content.planning).toEqual({});
        expect(brief.content.asset_selection.sources.map((source: any) => source.case_id).sort()).toEqual([assets[0].id, assets[1].id].sort());
        expect(state.workflow_runs.flatMap((run: any) => run.stages).some((stage: any) => stage.stage === 'test_point.generated')).toBe(false);
        expect(state.workflow_runs.flatMap((run: any) => run.stages).some((stage: any) => stage.stage === 'cases.searching')).toBe(true);
        // The generation endpoint cannot skip confirmation.
        await post(`/workspaces/${conversation.id}/test-briefs/confirm`, { version: brief.version }, [409]);
        await page.reload();
        const card = page.getByRole('region', { name: '现有用例资产选择' }).first();
        await expect(card).toBeVisible({ timeout: 30_000 });
        await expect(card).toContainText(origins[0].name);
        await page.locator('.principle-workflow').first().locator('summary').click();
        await expect(page.getByText('正在搜索用例资产…', { exact: true }).first()).toBeVisible();
        await page.screenshot({ path: path.join(output, `${mode}-preflight.png`), fullPage: true });
        if (mode === 'select') await card.getByRole('checkbox', { name: assets[1].title, exact: true }).uncheck();
        const response = page.waitForResponse(r => r.url().endsWith('/generation-assets/confirm') && r.request().method() === 'POST');
        await card.getByRole('button', { name: mode === 'select' ? '确认选用并组成集合' : '确认复用并开始规划', exact: true }).click();
        const confirmation = await response;
        expect(confirmation.status()).toBe(200);
        const action = (await confirmation.json()).action;
        if (mode === 'select') {
          expect(action.job_id).toBeUndefined();
          expect((await get(`/collections/${current.collection_id}/test-cases`)).map((item: any) => item.id)).toEqual([assets[0].id]);
          await page.reload();
          await expect(page.getByTestId('workspace-case-sources')).toContainText(origins[0].name);
          await expect(page.getByTestId('workspace-case-sources')).toContainText(assets[0].case_key);
          await page.screenshot({ path: path.join(output, `${mode}-sources.png`), fullPage: true });
          entry.final = await get(`/conversations/${conversation.id}`);
          continue;
        }
        state = await waitJob(conversation.id, action.job_id);
        brief = state.test_briefs.at(-1);
        expect(brief.content.planning.reuse.asset_confirmation).toBe('reuse');
        expect(brief.content.planning.reuse.decisions.map((item: any) => item.action)).toEqual(expect.arrayContaining(['reuse', 'modify', 'new']));
        expect(await get(`/collections/${current.collection_id}/test-cases`)).toEqual([]);
        entry.planned = state;
      }
      await page.reload();
      const response = page.waitForResponse(r => r.url().endsWith('/test-briefs/confirm') && r.request().method() === 'POST');
      await page.getByRole('button', { name: '确认选择并生成候选', exact: true }).click();
      const generated = await response;
      expect(generated.status()).toBe(202);
      state = await waitJob(conversation.id, (await generated.json()).action.job_id);
      expect(state.candidates.length).toBeGreaterThanOrEqual(3);
      entry.generated = state;
      await page.reload();
      await expect(page.getByTestId('workspace-case-sources')).toBeVisible();
      if (mode === 'select_and_generate') await expect(page.getByTestId('workspace-case-sources')).toContainText(origins[0].name);
      await page.screenshot({ path: path.join(output, `${mode}-candidates.png`), fullPage: true });
      await post(`/workspaces/${conversation.id}/candidates/commit`, { candidate_ids: state.candidates.filter((item: any) => item.status === 'candidate').map((item: any) => item.id) });
      const finalCases = await get(`/collections/${current.collection_id}/test-cases`);
      expect(finalCases.some((item: any) => JSON.stringify(item).includes('退出'))).toBe(true);
      if (mode === 'select_and_generate') {
        expect(finalCases.map((item: any) => item.id)).toContain(assets[0].id);
        expect(finalCases.map((item: any) => item.id)).not.toContain(assets[1].id);
        expect(finalCases).toHaveLength(3);
      }
      entry.finalCases = finalCases;
      await page.reload();
      await expect(page.getByTestId('workspace-case-sources')).toBeVisible();
      await expect(page.getByText('正在恢复工作区', { exact: true })).toBeHidden();
      if (mode === 'select_and_generate') await expect(page.getByTestId('workspace-case-sources')).toContainText(origins[0].name);
      await page.screenshot({ path: path.join(output, `${mode}-final.png`), fullPage: true });
    }
    const qaConversation = await post('/conversations', { space_id: space, title: '策略问答意图验收' });
    const qa = await post(`/conversations/${qaConversation.id}/messages`, { content: 'select和select_and_generate有什么区别？', generation_strategy: 'select' });
    expect(qa.intent).toBe('KNOWLEDGE_QA');
    expect(qa.action.type).toBe('knowledge_qa');
    evidence.strategyQuestion = qa;
    if (qa.action.job_id) await waitJob(qaConversation.id, qa.action.job_id);
    expect(evidence.browserErrors).toEqual([]);
    evidence.status = 'passed';
  } finally {
    await writeFile(path.join(output, 'real-e2e-results.json'), JSON.stringify(evidence, null, 2));
  }
});
