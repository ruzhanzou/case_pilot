/* eslint-disable @typescript-eslint/no-explicit-any -- Persisted live acceptance journal contains heterogeneous API evidence. */
import { test, expect } from '@playwright/test';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1', 'Requires deployed services and real model');
test.use({ viewport: { width: 1700, height: 1100 }, trace: 'on', video: 'retain-on-failure' });
const api = `${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
const dir = resolve(process.env.CASEPILOT_ACCEPTANCE_OUTPUT ?? '../../output/deep-deployment-20261009');
const requirement = `为账号安全系统生成恰好12条候选用例，每个编号仅1条，标题保留对应的A01等编号，最多4步。严格依据以下规则，不补充其他业务，不直接纳入正式集合：
密码登录：A01 已启用未锁定账号密码正确，HTTP 200且有access_token；A02 密码错误，HTTP 401且无令牌；A03 锁定账号密码正确，HTTP 423且无令牌；A04 禁用账号密码正确，HTTP 403且无令牌；A05 密码为空，HTTP 400且无令牌；A06 退出登录后使用旧令牌访问个人资料，HTTP 401。
短信验证：B01 正确的6位短信验证码在5分钟内可验证成功；B02 错误的短信验证码验证失败；B03 超过5分钟的短信验证码验证失败；B04 已使用的短信验证码不能再次使用。
密码重置：C01 重置链接10分钟内有效，设置12位新密码后可登录；C02 超过10分钟的重置链接禁止重置并提示重新申请。测试账号qa_user_001，使用独立测试环境。先提供测试规划供确认，再生成候选。`;

test('fresh chat generates twelve then partial adoption, iterative edit, query, CRUD and reload', async ({ page }) => {
  test.setTimeout(2400000);
  mkdirSync(dir, { recursive: true });
  const journal: any = process.env.CASEPILOT_CHAIN_RESUME
    ? JSON.parse(readFileSync(process.env.CASEPILOT_CHAIN_RESUME, 'utf8'))
    : { stages: {}, responses: {}, observations: [], startedAt: new Date().toISOString() };
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const save = () => writeFileSync(`${dir}/deep-results.json`, JSON.stringify(journal, null, 2));
  const shot = async (name: string) => { save(); await page.screenshot({ path: `${dir}/${name}.png`, fullPage: true }); };
  const get = async (path: string) => { const r = await page.request.get(`${api}${path}`); expect(r.ok(), await r.text()).toBeTruthy(); return r.json(); };
  const state = () => get(`/conversations/${journal.conversationId}`);
  const formal = () => get(`/collections/${journal.collectionId}/test-cases`);
  const stage = async (name: string, work: () => Promise<void>) => {
    if (journal.stages[name]) return;
    try { await test.step(name, work); journal.stages[name] = { passed: true, at: new Date().toISOString() }; save(); }
    catch (error) { journal.observations.push({ stage: name, error: String(error), at: new Date().toISOString() }); save(); throw error; }
  };
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  const auth = journal.conversationId
    ? await page.request.post(`${api}/auth/login`, { data: { email: 'demo@casepilot.local', password: 'CasePilot123!' } })
    : await page.request.post(`${api}/auth/register`, { data: { email: `chain-${Date.now()}@casepilot.test`, display_name: '完整链路验收', password: 'CasePilot123!' } });
  expect(auth.ok()).toBeTruthy();
  await page.goto('/workbench');
  await expect(page.getByLabel('写给 CasePilot')).toBeVisible();
  if (journal.conversationId) await page.goto(`/workbench/conversations/${journal.conversationId}`);
  const composer = page.locator('.principle-composer textarea');
  const notice = page.getByTestId('active-mutation-task-notice');
  const review = page.locator('.collection-changes__review');
  const candidates = page.locator('.task-result-cases');
  const idle = () => expect(composer).toBeEnabled({ timeout: 360000 });
  async function request(name: string, content: string, intent: string) {
    if (!journal.responses[name]) {
      await idle(); await composer.fill(content);
      const pending = page.waitForResponse(r => r.request().method() === 'POST' && /\/(messages|resume)$/.test(new URL(r.url()).pathname), { timeout: 180000 });
      await page.locator('.principle-composer button[type=submit]').click();
      const response = await pending; expect(response.ok(), await response.text()).toBeTruthy();
      journal.responses[name] = await response.json(); save();
    }
    let turn = journal.responses[name];
    expect(turn.intent, JSON.stringify(turn)).toBe(intent);
    if (turn.assistant_message?.metadata.modification_confirmation === true) {
      expect(turn.action.job_id).toBeFalsy();
      journal.observations.push({ name, preview: turn }); save();
      const pending = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/resume'), { timeout: 180000 });
      await page.getByRole('button', { name: '确认修改并生成建议', exact: true }).last().click();
      const response = await pending; expect(response.ok(), await response.text()).toBeTruthy();
      turn = journal.responses[name] = await response.json(); save();
    }
    return turn;
  }
  async function openReview() {
    await idle();
    if (await notice.isVisible()) await notice.getByRole('button', { name: '前往工作区审阅', exact: true }).click();
  }
  async function ready(turn: any) {
    expect(turn.action.change_set_id, JSON.stringify(turn)).toBeTruthy();
    const path = `/case-change-sets/${turn.action.change_set_id}`;
    await expect.poll(async () => { const change = await get(path); if (change.status === 'failed') throw new Error(JSON.stringify(change)); return change.status; }, { timeout: 360000 }).toBe('ready');
    await openReview(); await expect(review).toBeVisible(); return get(path);
  }
  async function applyAll() {
    const pending = page.waitForResponse(r => r.request().method() === 'POST' && /\/case-change-sets\/[^/]+\/apply$/.test(new URL(r.url()).pathname));
    await review.getByRole('button', { name: /一键采纳全部待审阅用例/ }).click();
    const response = await pending; expect(response.ok(), await response.text()).toBeTruthy(); await idle();
  }
  await stage('01_new_chat_planning_and_twelve_candidates', async () => {
    if (!journal.conversationId) {
      await expect(page.getByLabel('写给 CasePilot')).toBeVisible();
      const close = page.getByRole('button', { name: '关闭历史对话' }).last(); if (await close.isVisible()) await close.click();
      await page.getByLabel('写给 CasePilot').fill(requirement);
      await page.getByRole('button', { name: '发送', exact: true }).click();
      const picker = page.locator('.conversation-collection-picker'); await expect(picker).toBeVisible({ timeout: 180000 });
      journal.collectionName = `12条深度验收-${Date.now()}`; save();
      await picker.getByPlaceholder('或输入新集合名称').fill(journal.collectionName);
      const pending = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/confirm-collection'), { timeout: 180000 });
      await picker.getByRole('button', { name: '确认并进入工作台' }).click();
      const response = await pending; expect(response.ok(), await response.text()).toBeTruthy();
      const bound = await response.json(); journal.binding = bound; journal.conversationId = bound.conversation_id;
      journal.collectionId = (await state()).collection_id; save();
    }
    expect(await formal()).toHaveLength(0);
    if ((await state()).candidates.length !== 12) {
      const failedGeneration = (await state()).workflow_runs.find((r: any) => r.operation === 'generate' && r.status === 'failed');
      if (failedGeneration && journal.planning) {
        const retry = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/retry'), { timeout: 180000 });
        await page.getByRole('button', { name: '重试本次请求', exact: true }).last().click();
        expect((await retry).ok()).toBeTruthy();
        journal.generationRetried = true; save();
      } else {
      await expect(page.getByRole('region', { name: '测试规划脑图' })).toBeVisible({ timeout: 360000 });
      journal.planning = (await state()).test_briefs.at(-1); save();
      expect(journal.planning.content.test_object).toBe('账号安全系统');
      expect(journal.planning.content.planning.test_points.length).toBe(12);
      await shot('01-planning');
      await page.getByRole('button', { name: '确认规划并生成用例', exact: true }).click();
      }
      await expect.poll(async () => { const s = await state(); const failure = s.workflow_runs.find((r: any) => r.operation === 'generate' && r.status === 'failed'); if (failure) throw new Error(JSON.stringify(failure)); return s.candidates.length; }, { timeout: 720000 }).toBe(12);
    }
    await idle(); journal.generated = (await state()).candidates; save();
    expect(new Set(journal.generated.map((c: any) => c.ref)).size).toBe(12);
    for (const code of ['A01','A02','A03','A04','A05','A06','B01','B02','B03','B04','C01','C02']) expect(journal.generated.filter((c: any) => c.snapshot.title.includes(code))).toHaveLength(1);
    expect(journal.generated.every((c: any) => c.snapshot.steps.length > 0)).toBeTruthy();
    expect(await formal()).toHaveLength(0); await shot('02-twelve-candidates');
  });
  await stage('02_partial_adoption_three', async () => {
    await openReview();
    journal.remainingRefs = journal.generated.slice(3).map((c: any) => c.ref); save();
    for (const ref of journal.remainingRefs) { await candidates.getByRole('checkbox', { name: `纳入 ${ref}`, exact: true }).uncheck(); await idle(); }
    await candidates.getByRole('button', { name: '纳入已选候选', exact: true }).click();
    await expect.poll(async () => (await formal()).length).toBe(3);
    journal.firstFormal = await formal(); expect((await state()).candidates).toHaveLength(9); await shot('03-partial-adoption');
  });
  if (process.env.CASEPILOT_RECOVER_SPLIT === '1' && !journal.splitRecovered) {
    // Discard each old proposal through the UI, preserving all generated candidates.
    journal.splitAttempt = journal.responses.candidateBatch; save();
    for (const ref of journal.editRefs) {
      await idle();
      const confirm = page.getByRole('button', { name: '确认修改并生成建议', exact: true }).last();
      if (await confirm.isVisible()) { await confirm.click(); await idle(); }
      await openReview();
      const row = review.locator('.collection-changes__items > details').filter({ has: page.locator('summary').filter({ hasText: new RegExp('^' + ref + ' ·') }) });
      await expect(row).toBeVisible({ timeout: 360000 });
      await row.evaluate(el => el.setAttribute('open', ''));
      await row.getByRole('button', { name: '丢弃此建议', exact: true }).click();
      await idle();
    }
    expect(await formal()).toEqual(journal.firstFormal);
    const unchanged = (await state()).candidates; expect(unchanged).toHaveLength(9);
    for (const candidate of unchanged) expect(candidate.snapshot).toEqual(journal.generated.find((c: any) => c.ref === candidate.ref).snapshot);
    journal.splitRecovered = true; delete journal.responses.candidateBatch; save();
  }
  await stage('03_batch_candidate_body_modification', async () => {
    journal.editRefs = journal.remainingRefs.slice(0, 2); save();
    const turn = await request('candidateBatch', `仅修改候选 ${journal.editRefs.join('、')}：在前置条件中增加「只读审计账号可查询本次操作日志」，优先级统一改为P0。其他候选和已纳入用例不变，各用例其他字段逐字保留。`, 'CASE_MODIFY');
    const change = await ready(turn);
    expect(new Set(change.items.map((i: any) => i.ref))).toEqual(new Set(journal.editRefs));
    for (const item of change.items) {
      expect(item.target_type).toBe('candidate'); expect(item.proposed_snapshot.priority).toBe('P0');
      expect(item.proposed_snapshot.preconditions.join(' ')).toContain('只读审计账号');
      const original = journal.generated.find((c: any) => c.ref === item.ref).snapshot;
      for (const field of Object.keys(original).filter(key => !['preconditions', 'priority'].includes(key))) expect(item.proposed_snapshot[field]).toEqual(original[field]);
    }
    expect(await formal()).toEqual(journal.firstFormal); journal.candidateBatch = change; await shot('04-candidate-batch-diff');
  });
  await stage('04_accept_one_then_continue_remaining', async () => {
    await openReview();
    const row = review.locator('.collection-changes__items > details').filter({ has: page.locator('summary').filter({ hasText: new RegExp('^' + journal.editRefs[0] + ' ·') }) });
    await row.evaluate(el => el.setAttribute('open', '')); await row.getByRole('button', { name: '采纳此用例', exact: true }).click();
    await expect(review).toContainText('待审阅 1 条');
    journal.acceptedCandidate = (await state()).candidates.find((c: any) => c.ref === journal.editRefs[0]); save();
    const turn = await request('candidateContinue', `继续修改未采纳建议的候选 ${journal.editRefs[1]}：标题改为「深度验收：审计可追溯场景」。保留上一版前置条件及优先级，其他候选不变。`, 'CASE_MODIFY');
    const change = await ready(turn);
    expect(change.items.find((i: any) => i.ref === journal.editRefs[0]).status).toBe('applied');
    expect(change.items.filter((i: any) => !['applied','rejected'].includes(i.status))).toHaveLength(1);
    const pending = change.items.find((i: any) => i.ref === journal.editRefs[1]);
    expect(pending.proposed_snapshot.title).toBe('深度验收：审计可追溯场景'); expect(pending.proposed_snapshot.preconditions.join(' ')).toContain('只读审计账号'); expect(pending.proposed_snapshot.priority).toBe('P0');
    await applyAll();
    expect((await state()).candidates.find((c: any) => c.ref === journal.editRefs[0])).toEqual(journal.acceptedCandidate);
    expect(await formal()).toEqual(journal.firstFormal); journal.revisedCandidates = (await state()).candidates; await shot('05-continued-after-partial-acceptance');
  });
  await stage('05_incorporate_all_twelve', async () => {
    await openReview();
    for (const c of (await state()).candidates) { await candidates.getByRole('checkbox', { name: `纳入 ${c.ref}`, exact: true }).check(); await idle(); }
    await candidates.getByRole('button', { name: '纳入已选候选', exact: true }).click();
    await expect.poll(async () => (await formal()).length).toBe(12); await idle();
    const all = await formal();
    expect(all.filter((c: any) => journal.firstFormal.some((x: any) => x.id === c.id))).toEqual(journal.firstFormal);
    for (const candidate of journal.revisedCandidates) {
      const saved = all.find((c: any) => c.title === candidate.snapshot.title); expect(saved).toBeTruthy();
      for (const field of ['title','module','priority','preconditions']) expect(saved[field]).toEqual(candidate.snapshot[field]);
      expect(saved.steps.map(({ action, expected }: any) => ({ action, expected }))).toEqual(candidate.snapshot.steps.map(({ action, expected }: any) => ({ action, expected })));
    }
    expect((await state()).candidates).toHaveLength(0); expect((await state()).context.active_mutation_task_id).toBeNull();
    journal.twelveFormal = all; await shot('06-twelve-formal');
  });
  await stage('06_priority_and_body_query', async () => {
    const priority = await request('priority', '查询当前集合优先级为P0的正式用例，只查询不修改', 'CASE_QUERY');
    expect(priority.action.type).toBe('case_query');
    expect(new Set(priority.assistant_message.target_case_ids)).toEqual(new Set(journal.twelveFormal.filter((c: any) => c.priority === 'P0').map((c: any) => c.id)));
    const query = await request('bodyQuery', '查询当前集合前置条件中包含「只读审计账号」的正式用例', 'CASE_QUERY');
    expect(query.action.type).toBe('case_query');
    journal.bodyTargetIds = journal.twelveFormal.filter((c: any) => c.preconditions.join(' ').includes('只读审计账号')).map((c: any) => c.id);
    expect(journal.bodyTargetIds).toHaveLength(2); expect(new Set(query.assistant_message.target_case_ids)).toEqual(new Set(journal.bodyTargetIds));
    expect(await formal()).toEqual(journal.twelveFormal); await shot('07-query-exact-body-results');
  });
  if (process.env.CASEPILOT_RECOVER_QUERY === '1' && !journal.queryRecovered) {
    journal.queryAttempt = journal.responses.modifyQuery; save();
    await openReview();
    await page.getByRole('button', { name: '放弃当前任务', exact: true }).click(); await idle();
    expect(await formal()).toEqual(journal.twelveFormal);
    journal.queryRecovered = true; delete journal.responses.modifyQuery; save();
  }
  await stage('07_modify_query_result_only', async () => {
    const turn = await request('modifyQuery', '仅把刚才查询到的用例优先级改为P2，其他字段和其他用例保持不变', 'CASE_MODIFY');
    const change = await ready(turn); expect(new Set(change.items.map((i: any) => i.ref))).toEqual(new Set(journal.bodyTargetIds));
    expect(await formal()).toEqual(journal.twelveFormal); await applyAll();
    const after = await formal();
    for (const old of journal.twelveFormal) {
      const current = after.find((c: any) => c.id === old.id);
      if (journal.bodyTargetIds.includes(old.id)) { expect(current.priority).toBe('P2'); expect(current.revision_number).toBe(old.revision_number + 1); for (const field of Object.keys(old).filter(key => !['priority', 'revision_number', 'current_revision_id'].includes(key))) expect(current[field]).toEqual(old[field]); }
      else expect(current).toEqual(old);
    }
    journal.afterQueryModification = after; await shot('08-query-followup-saved');
  });
  await stage('08_discard_modification', async () => {
    const target = journal.afterQueryModification.find((c: any) => !journal.bodyTargetIds.includes(c.id)); journal.deleteTarget = target; save();
    await ready(await request('discardEdit', `仅把用例 ${target.case_key} 的标题改为「不应保存的修改」`, 'CASE_MODIFY'));
    await page.getByRole('button', { name: '放弃当前任务', exact: true }).click(); await idle();
    expect(await formal()).toEqual(journal.afterQueryModification); await shot('09-discard-preserved');
  });
  await stage('09_cancel_then_confirm_delete', async () => {
    await request('deleteCancel', `删除用例 ${journal.deleteTarget.case_key}，保留其他所有用例`, 'CASE_DELETE');
    expect(await formal()).toEqual(journal.afterQueryModification);
    await page.getByRole('button', { name: '取消变更', exact: true }).click(); await idle(); expect(await formal()).toEqual(journal.afterQueryModification);
    await request('deleteConfirm', `删除用例 ${journal.deleteTarget.case_key}，保留其他所有用例`, 'CASE_DELETE');
    expect(await formal()).toEqual(journal.afterQueryModification);
    await page.getByRole('button', { name: '确认删除已选用例', exact: true }).click();
    await expect.poll(async () => (await formal()).length).toBe(11);
    expect(await formal()).toEqual(journal.afterQueryModification.filter((c: any) => c.id !== journal.deleteTarget.id)); await shot('10-confirmed-delete');
  });
  await stage('10_reload_and_final_integrity', async () => {
    const before = await formal(); await page.reload(); await idle();
    expect(await formal()).toEqual(before);
    journal.finalState = await state(); journal.finalCases = before;
    expect(journal.finalState.context.active_mutation_task_id).toBeNull();
    expect(journal.finalState.operation_history.filter((o: any) => ['running','queued','failed'].includes(o.status))).toHaveLength(0);
    expect(journal.finalState.candidates).toHaveLength(0); await shot('11-reloaded-final');
  });
  expect(errors).toEqual([]); journal.errors = errors; journal.passed = true; journal.finishedAt = new Date().toISOString(); save();
});
