/* eslint-disable @typescript-eslint/no-explicit-any -- Preserve real service evidence. */
import { expect, test, type Page } from '@playwright/test';
import { writeFileSync } from 'node:fs';

test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1', 'Requires local API, worker and real model');
test.use({ viewport: { width: 1600, height: 1000 }, trace: 'on' });
test.setTimeout(900_000);
const api = `${process.env.CASEPILOT_E2E_API_URL ?? 'http://localhost:8000'}/api/v1`;

async function get(page: Page, path: string) {
  const r = await page.request.get(api + path, { maxRetries: 1 });
  expect(r.ok(), await r.text()).toBeTruthy();
  return r.json();
}
async function send(page: Page, text: string) {
  const input = page.locator('.principle-composer textarea');
  await expect(input).toBeEnabled({ timeout: 90_000 });
  await input.fill(text);
  const pending = page.waitForResponse(r => r.request().method() === 'POST' && /\/(messages|resume)$/.test(r.url()), { timeout: 180_000 });
  await page.locator('.principle-composer button[type=submit]').click();
  const r = await pending;
  expect(r.ok(), await r.text()).toBeTruthy();
  let turn = await r.json();
  if (turn.assistant_message?.metadata.modification_confirmation) {
    const confirmation = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/resume'), { timeout: 180_000 });
    await page.getByRole('button', { name: '确认修改并生成建议', exact: true }).last().click();
    const response = await confirmation;
    expect(response.ok(), await response.text()).toBeTruthy();
    turn = await response.json();
  }
  return turn;
}
async function settle(page: Page, id: string) {
  let state: any;
  await expect.poll(async () => {
    state = await get(page, `/conversations/${id}`);
    const failed = state.workflow_runs.filter((r: any) => r.status === 'failed');
    if (failed.length) throw new Error(JSON.stringify(failed));
    return state.workflow_runs.every((r: any) => !['queued', 'running', 'pending'].includes(r.status));
  }, { timeout: 360_000, intervals: [1000, 2000, 4000] }).toBe(true);
  return state;
}

test('two accounts independently chat and generate, then safely contend on a shared case', async ({ browser }, info) => {
  const contexts = await Promise.all([browser.newContext({ viewport: { width: 1600, height: 1000 } }), browser.newContext({ viewport: { width: 1600, height: 1000 } })]);
  const pages = await Promise.all(contexts.map(c => c.newPage()));
  const [a, b] = pages;
  const evidence: any = { accounts: [], stages: [], errors: [], startedAt: new Date().toISOString() };
  const stage = (name: string) => { evidence.stages.push(name); console.log(name); };
  for (const page of pages) {
    page.on('pageerror', error => evidence.errors.push(error.message));
    await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  }
  try {
    for (const [index, page] of pages.entries()) {
      const response = await page.request.post(`${api}/auth/register`, { data: {
        email: `multi-${Date.now()}-${index}@casepilot.test`, display_name: `并发验收${index + 1}`, password: 'CasePilot123!',
      } });
      expect(response.status()).toBe(201);
      evidence.accounts.push(await response.json());
    }
    const owner = evidence.accounts[0];
    const added = await a.request.post(`${api}/spaces/${owner.spaces[0].id}/members`, { data: { email: evidence.accounts[1].email } });
    expect(added.ok()).toBeTruthy();
    const created = await a.request.post(`${api}/spaces/${owner.spaces[0].id}/collections`, { data: { name: `多人并发验收-${Date.now()}` } });
    expect(created.status()).toBe(201);
    evidence.collection = await created.json();
    const collectionId = evidence.collection.id;
    await Promise.all(pages.map(p => p.goto(`/workbench/collections/${collectionId}`)));
    await Promise.all(pages.map(p => expect(p.locator('.principle-composer textarea')).toBeEnabled({ timeout: 60_000 })));
    const workspaces = await Promise.all(pages.map(p => get(p, `/collections/${collectionId}/conversations/latest`)));
    expect(workspaces[0].id).not.toBe(workspaces[1].id);
    evidence.workspaceIds = workspaces.map(w => w.id);
    await Promise.all(pages.map((p, i) => p.locator('.principle-composer textarea').fill(`仅账号${i}的草稿`)));
    await Promise.all(pages.map((p, i) => expect.poll(async () => (await get(p, `/conversations/${workspaces[i].id}`)).context.draft_text).toBe(`仅账号${i}的草稿`)));
    await Promise.all(pages.map(p => p.reload()));
    await Promise.all(pages.map((p, i) => expect(p.locator('.principle-composer textarea')).toHaveValue(`仅账号${i}的草稿`)));
    expect((await b.request.get(`${api}/conversations/${workspaces[0].id}`)).status()).toBe(404);
    stage('PASS: account-scoped workspaces, drafts and direct access');

    const chat = await Promise.all(pages.map((p, i) => send(p, `你好，我是并发验收用户${i}`)));
    expect(chat[0].conversation_id).not.toBe(chat[1].conversation_id);
    const histories = await Promise.all(pages.map((p, i) => get(p, `/conversations/${workspaces[i].id}`)));
    for (const [i, state] of histories.entries()) {
      expect(state.messages.some((m: any) => m.content === `你好，我是并发验收用户${i}`)).toBe(true);
      expect(state.messages.some((m: any) => m.content === `你好，我是并发验收用户${1 - i}`)).toBe(false);
    }
    stage('PASS: simultaneous dialogue does not mix messages');
    const requests = [
      '请为当前集合的账号登录功能生成且仅生成1条正常用例。需求：已注册且启用的账号输入正确密码后登录成功，返回唯一会话标识。模块是账号登录。先给测试规划，不增加其他场景。',
      '请为当前集合的账号退出功能生成且仅生成1条正常用例。需求：已登录用户点击退出后，当前会话失效，返回登录页。模块是账号退出。先给测试规划，不增加其他场景。',
    ];
    evidence.planningTurns = await Promise.all(pages.map((p, i) => send(p, requests[i])));
    const confirmation = /^确认(?:规划|范围)并生成用例$/;
    await Promise.all(pages.map(p => expect(p.getByRole('button', { name: confirmation })).toBeEnabled({ timeout: 360_000 })));
    await Promise.all(pages.map(p => p.getByRole('button', { name: confirmation }).click()));
    evidence.generated = await Promise.all(pages.map((p, i) => settle(p, workspaces[i].id)));
    for (const state of evidence.generated) {
      expect(state.candidates).toHaveLength(1);
      expect(state.candidates[0].snapshot.steps.length).toBeGreaterThan(0);
    }
    expect(evidence.generated[0].candidates[0].generation_job_id).not.toBe(evidence.generated[1].candidates[0].generation_job_id);
    const jobA = evidence.generated[0].candidates[0].generation_job_id;
    expect((await b.request.get(`${api}/generation-jobs/${jobA}`)).status()).toBe(404);
    expect((await b.request.post(`${api}/generation-jobs/${jobA}/cancel`)).status()).toBe(404);
    expect(await get(a, `/collections/${collectionId}/test-cases`)).toHaveLength(0);
    stage('PASS: simultaneous real-model generation returns independent candidates');
    await Promise.all(pages.map(p => expect(p.getByRole('button', { name: /^采纳已选/ }).first()).toBeEnabled({ timeout: 60_000 })));
    await Promise.all(pages.map(p => p.getByRole('button', { name: /^采纳已选/ }).first().click()));
    await expect.poll(async () => (await get(a, `/collections/${collectionId}/test-cases`)).length).toBe(2);
    evidence.originalCases = await get(a, `/collections/${collectionId}/test-cases`);
    const target = evidence.originalCases[0];
    stage('PASS: both users adopt candidates into the shared collection');

    await Promise.all(pages.map(p => p.reload()));
    evidence.rewriteTurns = await Promise.all(pages.map((p, i) => send(p,
      `只修改正式用例 ${target.case_key} 的标题为“并发${i === 0 ? '甲' : '乙'}版标题”，其他字段保持原样，请生成修改建议供我审阅。`)));
    evidence.proposals = await Promise.all(pages.map((p, i) => settle(p, workspaces[i].id)));
    await Promise.all(pages.map(p => expect(p.getByRole('button', { name: '应用已选修改', exact: true }).last()).toBeEnabled({ timeout: 60_000 })));
    expect((await get(a, `/test-cases/${target.id}`)).current_revision_id).toBe(target.current_revision_id);
    const pendingA = a.waitForResponse(r => r.request().method() === 'POST' && /\/case-change-sets\/.*\/apply$/.test(r.url()));
    await a.getByRole('button', { name: '应用已选修改', exact: true }).last().click();
    const applied = await pendingA;
    expect(applied.ok(), await applied.text()).toBeTruthy();
    const pendingB = b.waitForResponse(r => r.request().method() === 'POST' && /\/case-change-sets\/.*\/apply$/.test(r.url()));
    await b.getByRole('button', { name: '应用已选修改', exact: true }).last().click();
    const conflict = await pendingB;
    expect(conflict.status()).toBe(409);
    expect((await conflict.json()).detail).toBe('revision_conflict');
    evidence.finalCases = await get(a, `/collections/${collectionId}/test-cases`);
    const final = evidence.finalCases.find((c: any) => c.id === target.id);
    expect(final.title).toBe('并发甲版标题');
    expect(final.revision_number).toBe(target.revision_number + 1);
    expect(evidence.finalCases.find((c: any) => c.id !== target.id)).toEqual(evidence.originalCases.find((c: any) => c.id !== target.id));
    await expect(a.getByText('并发甲版标题', { exact: false }).first()).toBeVisible();
    stage('PASS: stale modification receives 409 and cannot overwrite accepted revision');
    expect(evidence.errors).toEqual([]);
    evidence.passed = true;
  } finally {
    for (const [i, page] of pages.entries()) {
      await page.screenshot({ path: info.outputPath(`user-${i + 1}.png`), fullPage: true }).catch(() => {});
    }
    writeFileSync(info.outputPath('evidence.json'), JSON.stringify(evidence, null, 2));
    await Promise.all(contexts.map(c => c.close()));
  }
});

// Run with --grep 'five accounts' to exercise the current deployment without
// changing its worker capacity. Each browser owns an independent login/session.
test('five accounts simultaneously use their own conversations, generation and modifications', async ({ browser }, info) => {
  test.setTimeout(1_800_000);
  const count = 5;
  const contexts = await Promise.all(Array.from({ length: count }, () => browser.newContext({ viewport: { width: 1600, height: 1000 } })));
  const pages = await Promise.all(contexts.map(c => c.newPage()));
  const evidence: any = {
    userCount: count, accounts: [], stages: [], errors: [], httpErrors: [],
    timings: [], queueSamples: [], accessChecks: [], startedAt: new Date().toISOString(),
  };
  const save = () => writeFileSync(info.outputPath('evidence.json'), JSON.stringify(evidence, null, 2));
  const stage = (name: string) => { evidence.stages.push({ name, at: new Date().toISOString() }); save(); console.log(name); };
  const timed = async <T,>(label: string, user: number, action: () => Promise<T>): Promise<T> => {
    const timing: any = { label, user: user + 1, startedAt: Date.now() };
    evidence.timings.push(timing);
    try { return await action(); } finally { timing.finishedAt = Date.now(); timing.ms = timing.finishedAt - timing.startedAt; }
  };
  async function waitJobs(label: string, jobIds: string[]) {
    expect(new Set(jobIds).size).toBe(count);
    const start = Date.now();
    const finished: Record<string, number> = {};
    while (Date.now() - start < 720_000) {
      const jobs = await Promise.all(pages.map((p, i) => get(p, `/generation-jobs/${jobIds[i]}`)));
      evidence.queueSamples.push({ label, elapsedMs: Date.now() - start, at: Date.now(), jobs: jobs.map((j: any, i: number) => ({ user: i + 1, id: j.id, status: j.status, stage: j.stage, progress: j.progress })) });
      for (const [i, job] of jobs.entries()) {
        if (['failed', 'cancelled', 'awaiting_input'].includes(job.status)) throw new Error(`${label} user ${i + 1}: ${JSON.stringify(job)}`);
        if (job.status === 'completed' && !finished[job.id]) finished[job.id] = Date.now() - start;
      }
      save();
      if (jobs.every((j: any) => j.status === 'completed')) {
        evidence[`${label}CompletionMs`] = jobIds.map(id => finished[id]);
        return jobs;
      }
      await new Promise(resolve => setTimeout(resolve, 2000));
    }
    throw new Error(`${label}: five-user jobs exceeded 12 minutes`);
  }
  async function checkPrivateHistories() {
    const states = await Promise.all(pages.map((p, i) => get(p, `/conversations/${evidence.workspaceIds[i]}`)));
    for (const [i, state] of states.entries()) {
      const ownMessages = state.messages.filter((m: any) => m.role === 'user').map((m: any) => m.content);
      for (const [j, requests] of evidence.userRequests.entries()) {
        for (const request of requests) expect(ownMessages.includes(request), `user ${i + 1} / request owner ${j + 1}`).toBe(i === j);
      }
      const history = await get(pages[i], `/conversations/history?space_id=${evidence.collection.space_id}`);
      expect(history.items.map((item: any) => item.id)).toEqual([evidence.workspaceIds[i]]);
    }
    return states;
  }
  try {
    for (const [i, page] of pages.entries()) {
      page.on('pageerror', error => evidence.errors.push({ user: i + 1, message: error.message }));
      page.on('response', response => {
        if (response.url().includes('/api/v1/') && response.status() >= 400) evidence.httpErrors.push({ user: i + 1, status: response.status(), url: response.url() });
      });
      await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
    }
    evidence.accounts = await Promise.all(pages.map(async (p, i) => {
      const r = await p.request.post(`${api}/auth/register`, { data: { email: `five-${Date.now()}-${i}@casepilot.test`, display_name: `五人验收${i + 1}`, password: 'CasePilot123!' } });
      expect(r.status()).toBe(201); return r.json();
    }));
    save();
    await Promise.all(evidence.accounts.slice(1).map(async (account: any) => {
      const r = await pages[0].request.post(`${api}/spaces/${evidence.accounts[0].spaces[0].id}/members`, { data: { email: account.email } });
      expect(r.status()).toBe(201);
    }));
    const created = await pages[0].request.post(`${api}/spaces/${evidence.accounts[0].spaces[0].id}/collections`, { data: { name: `五人各自会话并发验收-${Date.now()}` } });
    expect(created.status()).toBe(201); evidence.collection = await created.json();
    const path = `/workbench/collections/${evidence.collection.id}`;
    const opened = pages.map(p => p.waitForResponse(r => r.request().method() === 'PUT' && r.url().endsWith(`/collections/${evidence.collection.id}/workspace`), { timeout: 60_000 }));
    await Promise.all(pages.map(p => p.goto(path)));
    for (const response of await Promise.all(opened)) expect(response.ok(), await response.text()).toBeTruthy();
    await Promise.all(pages.map(p => expect(p.locator('.principle-composer textarea')).toBeEnabled({ timeout: 60_000 })));
    const workspaces = await Promise.all(pages.map(p => get(p, `/collections/${evidence.collection.id}/conversations/latest`)));
    evidence.workspaceIds = workspaces.map(w => w.id);
    expect(new Set(evidence.workspaceIds).size).toBe(count);
    await Promise.all(pages.map((p, i) => p.locator('.principle-composer textarea').fill(`五人专属草稿-${i + 1}`)));
    await Promise.all(pages.map((p, i) => expect.poll(async () => (await get(p, `/conversations/${workspaces[i].id}`)).context.draft_text).toBe(`五人专属草稿-${i + 1}`)));
    await Promise.all(pages.map(p => p.reload()));
    await Promise.all(pages.map((p, i) => expect(p.locator('.principle-composer textarea')).toHaveValue(`五人专属草稿-${i + 1}`)));
    await Promise.all(pages.map(async (p, i) => {
      for (const [j, w] of workspaces.entries()) {
        if (i === j) continue;
        const response = await p.request.get(`${api}/conversations/${w.id}`, { maxRetries: 1 });
        expect(response.status()).toBe(404);
        evidence.accessChecks.push({ kind: 'conversation', requester: i + 1, owner: j + 1, status: response.status() });
      }
    }));
    stage('PASS: 5 independent workspaces and drafts; all 20 cross-account conversation reads denied');

    evidence.userRequests = Array.from({ length: count }, () => []);
    for (let round = 1; round <= 2; round++) {
      await Promise.all(pages.map(async (p, i) => {
        const content = round === 1 ? `你好，我是五人验收用户${i + 1}` : `谢谢，这是用户${i + 1}的第${round}轮交流`;
        evidence.userRequests[i].push(content);
        const turn = await timed(`chat-round-${round}`, i, () => send(p, content));
        expect(turn.conversation_id).toBe(workspaces[i].id);
      }));
      await checkPrivateHistories();
    }
    stage('PASS: 5 users send two simultaneous chat rounds; messages and histories remain private');

    const modules = ['账号登录', '账号退出', '个人昵称', '收藏文章', '移除收藏'];
    const rules = [
      '已注册且启用的账号输入正确密码后登录成功，返回唯一会话标识。',
      '已登录用户点击退出后，当前会话失效，返回登录页。',
      '已登录用户在个人资料页将昵称改为测试昵称并保存，页面显示测试昵称。',
      '已登录用户在未收藏的文章详情页点击收藏，文章进入该用户的收藏列表。',
      '已登录用户在收藏列表中对一篇已收藏文章点击移除，该文章不再出现在收藏列表中。',
    ];
    const planning = await Promise.all(pages.map(async (p, i) => {
      const content = `测试对象是${modules[i]}。需求：${rules[i]} 请为当前集合生成且仅生成1条正常用例，模块是${modules[i]}。先给测试规划，不增加其他场景。`;
      evidence.userRequests[i].push(content);
      return timed('planning-submit', i, () => send(p, content));
    }));
    evidence.planningTurns = planning;
    const planIds = planning.map(t => t.action.job_id);
    expect(planIds.every(Boolean)).toBe(true);
    stage('START: 5 planning requests submitted; observing actual queue and execution');
    await waitJobs('planning', planIds);
    await checkPrivateHistories();
    const confirmation = /^确认(?:规划|范围)并生成用例$/;
    await Promise.all(pages.map(p => expect(p.getByRole('button', { name: confirmation })).toBeEnabled({ timeout: 60_000 })));
    evidence.generationTurns = await Promise.all(pages.map((p, i) => timed('generation-submit', i, async () => {
      const pending = p.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/test-briefs/confirm'), { timeout: 60_000 });
      await p.getByRole('button', { name: confirmation }).click();
      const r = await pending; expect(r.ok(), await r.text()).toBeTruthy(); return r.json();
    })));
    const generationIds = evidence.generationTurns.map((t: any) => t.action.job_id);
    expect(generationIds.every(Boolean)).toBe(true);
    await Promise.all(pages.map(async (p, i) => {
      for (const [j, id] of generationIds.entries()) {
        if (i === j) continue;
        for (const method of ['read', 'cancel']) {
          const r = method === 'read' ? await p.request.get(`${api}/generation-jobs/${id}`, { maxRetries: 1 }) : await p.request.post(`${api}/generation-jobs/${id}/cancel`);
          expect(r.status()).toBe(404);
          evidence.accessChecks.push({ kind: `job-${method}`, requester: i + 1, owner: j + 1, status: r.status() });
        }
      }
    }));
    stage('START: 5 generation requests submitted; all 40 foreign job read/cancel attempts denied');
    await waitJobs('generation', generationIds);
    evidence.generated = await checkPrivateHistories();
    for (const [i, state] of evidence.generated.entries()) {
      expect(state.candidates).toHaveLength(1);
      expect(state.candidates[0].generation_job_id).toBe(generationIds[i]);
      expect(state.candidates[0].snapshot.module).toContain(modules[i]);
      expect(state.candidates[0].snapshot.steps.length).toBeGreaterThan(0);
      expect(state.workflow_runs.map((r: any) => r.job_id).sort()).toEqual([planIds[i], generationIds[i]].sort());
    }
    expect(await get(pages[0], `/collections/${evidence.collection.id}/test-cases`)).toHaveLength(0);
    stage('PASS: 5 real-model generations completed with isolated candidates and progress');
    evidence.adopted = await Promise.all(pages.map((p, i) => timed('adopt', i, async () => {
      const button = p.getByRole('button', { name: /^采纳已选/ }).first();
      await expect(button).toBeEnabled({ timeout: 60_000 });
      const pending = p.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/candidates/commit'));
      await button.click(); const r = await pending; expect(r.ok(), await r.text()).toBeTruthy();
      const cases = await r.json(); expect(cases).toHaveLength(1); return cases[0];
    })));
    expect(new Set(evidence.adopted.map((c: any) => c.id)).size).toBe(count);
    evidence.originalCases = await get(pages[0], `/collections/${evidence.collection.id}/test-cases`);
    expect(evidence.originalCases).toHaveLength(count);
    stage('PASS: 5 users concurrently adopt their own generated case; exactly 5 formal cases saved');

    await Promise.all(pages.map(p => p.reload()));
    evidence.rewriteTurns = await Promise.all(pages.map((p, i) => timed('rewrite-submit', i, () => send(p,
      `只修改正式用例 ${evidence.adopted[i].case_key} 的标题为“五人用户${i + 1}独立修订”，其他字段保持原样，请生成修改建议供我审阅。`))));
    const rewriteIds = evidence.rewriteTurns.map((t: any) => t.action.job_id);
    expect(rewriteIds.every(Boolean)).toBe(true);
    await waitJobs('rewrite', rewriteIds);
    for (const [i, page] of pages.entries()) {
      const changeSet = await get(page, `/case-change-sets/${evidence.rewriteTurns[i].action.change_set_id}`);
      expect(changeSet.items).toHaveLength(1);
      expect(changeSet.items[0].test_case_id).toBe(evidence.adopted[i].id);
    }
    expect(await get(pages[0], `/collections/${evidence.collection.id}/test-cases`)).toEqual(evidence.originalCases);
    evidence.applied = await Promise.all(pages.map((p, i) => timed('apply', i, async () => {
      const button = p.getByRole('button', { name: '应用已选修改', exact: true }).last();
      await expect(button).toBeEnabled({ timeout: 60_000 });
      const pending = p.waitForResponse(r => r.request().method() === 'POST' && /\/case-change-sets\/.*\/apply$/.test(r.url()));
      await button.click(); const r = await pending; expect(r.ok(), await r.text()).toBeTruthy(); return r.json();
    })));
    evidence.finalCases = await get(pages[0], `/collections/${evidence.collection.id}/test-cases`);
    expect(evidence.finalCases).toHaveLength(count);
    for (const [i, original] of evidence.adopted.entries()) {
      const final = evidence.finalCases.find((c: any) => c.id === original.id);
      expect(final.title).toBe(`五人用户${i + 1}独立修订`);
      expect(final.revision_number).toBe(original.revision_number + 1);
      for (const field of ['description', 'module', 'priority', 'preconditions', 'steps', 'tags']) expect(final[field]).toEqual(original[field]);
    }
    await Promise.all(pages.map(p => p.reload()));
    await Promise.all(pages.map((p, i) => expect(p.getByText(`五人用户${i + 1}独立修订`, { exact: false }).first()).toBeVisible({ timeout: 60_000 })));
    evidence.finalConversations = await checkPrivateHistories();
    for (const [i, state] of evidence.finalConversations.entries()) {
      expect(state.workflow_runs.map((r: any) => r.job_id).sort()).toEqual([planIds[i], generationIds[i], rewriteIds[i]].sort());
      expect(state.workflow_runs.every((r: any) => r.status === 'completed')).toBe(true);
    }
    expect(evidence.errors).toEqual([]);
    expect(evidence.httpErrors).toEqual([]);
    evidence.passed = true;
    stage('PASS: 5 independent concurrent modifications saved once each; all other fields preserved; no browser/API errors');
  } catch (error) {
    evidence.failure = String(error);
    throw error;
  } finally {
    evidence.finishedAt = new Date().toISOString();
    evidence.durationMs = Date.parse(evidence.finishedAt) - Date.parse(evidence.startedAt);
    await Promise.all(pages.map((p, i) => p.screenshot({ path: info.outputPath(`user-${i + 1}.png`), fullPage: true }).catch(() => {})));
    save();
    await Promise.all(contexts.map(c => c.close()));
  }
});
