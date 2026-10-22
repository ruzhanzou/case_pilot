/* eslint-disable @typescript-eslint/no-explicit-any -- Live regression keeps API snapshots as evidence. */
import { expect, test } from '@playwright/test';
import { writeFileSync } from 'node:fs';

test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1', 'Requires real API, worker and model');
test.use({ viewport: { width: 1600, height: 1000 }, trace: 'on' });
test.use({ video: 'off' });
test.setTimeout(900_000);
const api = `${process.env.CASEPILOT_E2E_API_URL}/api/v1`;

test('new dialogue generates cases, regenerates one point, then modifies adopted cases', async ({ page }, info) => {
  const journal: any = { stages: [], errors: [] };
  page.on('pageerror', error => journal.errors.push(error.message));
  const save = () => writeFileSync(info.outputPath('evidence.json'), JSON.stringify(journal, null, 2));
  const get = async (path: string) => {
    const response = await page.request.get(api + path);
    expect(response.ok(), await response.text()).toBeTruthy();
    return response.json();
  };
  const postClick = async (suffix: string, click: () => Promise<void>) => {
    const [response] = await Promise.all([
      page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith(suffix), { timeout: 180_000 }),
      click(),
    ]);
    expect(response.ok(), await response.text()).toBeTruthy();
    return response.json();
  };
  try {
    await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
    const email = `dialogue-chain-${Date.now()}@casepilot.test`;
    const registration = await page.request.post(`${api}/auth/register`, { data: { email, display_name: '生成修改全链路验收', password: 'CasePilot123!' } });
    expect(registration.status()).toBe(201);
    journal.email = email;
    await page.goto('/workbench');
    await page.getByLabel('写给 CasePilot').fill('为青禾借阅系统全新生成测试用例，不复用历史。严格只有2个测试点，每个生成1条用例：R1 可借图书且账号有效，提交借阅成功，记录借阅单；R2 图书库存为0，提交借阅失败，提示库存不足。先提供测试规划，确认后生成候选，不直接保存正式用例。');
    await page.getByRole('button', { name: '发送', exact: true }).click();
    const picker = page.locator('.conversation-collection-picker');
    await expect(picker).toBeVisible({ timeout: 180_000 });
    await picker.getByPlaceholder('或输入新集合名称').fill(`生成修改全链路-${Date.now()}`);
    const bound = await postClick('/confirm-collection', () => picker.getByRole('button', { name: '确认并进入工作台' }).click());
    journal.conversationId = bound.conversation_id;
    const state = () => get(`/conversations/${journal.conversationId}`);
    journal.collectionId = (await state()).collection_id;
    const formal = () => get(`/collections/${journal.collectionId}/test-cases`);
    await expect.poll(async () => {
      const current = await state();
      if (current.workflow_runs.some((r: any) => r.status === 'failed')) throw new Error(JSON.stringify(current.workflow_runs));
      return current.test_briefs.at(-1)?.content.planning?.test_points?.length;
    }, { timeout: 360_000 }).toBe(2);
    expect(await formal()).toHaveLength(0);
    const plan = (await state()).test_briefs.at(-1).content.planning;
    const waitJob = async (jobId: string) => {
      await expect.poll(async () => {
        const run = (await state()).workflow_runs.find((r: any) => r.job_id === jobId);
        if (run?.status === 'failed') throw new Error(JSON.stringify(run));
        return run?.status;
      }, { timeout: 300_000, intervals: [1000, 2000] }).toBe('completed');
    };
    const generated = await postClick('/test-briefs/confirm', () => page.getByRole('button', { name: '确认选择并生成候选', exact: true }).click());
    await page.reload();
    await waitJob(generated.action.job_id);
    const before = (await state()).candidates;
    expect(before).toHaveLength(2);
    expect(await formal()).toHaveLength(0);
    journal.stages.push('generation_survives_reload'); journal.before = before; save();

    await page.getByRole('button', { name: '结构化测试说明', exact: true }).click();
    const map = page.getByRole('region', { name: '测试规划脑图' });
    await map.getByLabel('规划展开层级').selectOption('20');
    const point = plan.test_points[0];
    await map.getByRole('button', { name: point.title, exact: true }).click();
    const regenerated = await postClick('/test-briefs/confirm', () => map.getByRole('button', { name: '生成选中范围（1）', exact: true }).click());
    await waitJob(regenerated.action.job_id);
    const current = (await state()).candidates;
    const unchanged = before.find((c: any) => !c.snapshot.test_point_ids.includes(point.id));
    expect(current).toHaveLength(2);
    expect(current.find((c: any) => c.id === unchanged.id)?.snapshot).toEqual(unchanged.snapshot);
    expect(new Set(current.flatMap((c: any) => c.snapshot.test_point_ids))).toEqual(new Set(plan.test_points.map((p: any) => p.id)));
    journal.stages.push('partial_regeneration_preserves_other_point'); save();
    const adoptCurrent = page.getByRole('button', { name: '采纳已选（1）', exact: true });
    await expect(adoptCurrent).toBeVisible();
    const adopted = await postClick('/candidates/commit', () => adoptCurrent.click());
    expect(adopted).toHaveLength(1);
    expect(await formal()).toHaveLength(1);
    expect((await state()).candidates.map((c: any) => c.id)).toEqual([unchanged.id]);
    journal.stages.push('task_adoption_does_not_commit_hidden_candidates'); save();
    await page.reload();
    await page.getByRole('button', { name: '用例列表', exact: true }).click();
    await expect(page.getByRole('button', { name: '采纳所选', exact: true })).toBeVisible();
    const remaining = await postClick('/candidates/commit', () => page.getByRole('button', { name: '采纳所选', exact: true }).click());
    expect(remaining).toHaveLength(1);
    const original = await formal();
    expect(original).toHaveLength(2);
    await page.reload();
    const composer = page.locator('.principle-composer');
    const target = original[0];
    await expect(composer.locator('textarea')).toBeEnabled();
    await composer.locator('textarea').fill(`把用例 ${target.case_key} 的标题改为“青禾借阅验收已确认”，其他字段保持不变。`);
    const proposal = await postClick('/messages', () => composer.locator('button[type=submit]').click());
    expect(proposal.assistant_message.metadata.modification_confirmation).toBe(true);
    expect(proposal.action.job_id).toBeFalsy();
    expect(await formal()).toEqual(original);
    const confirmed = await postClick('/resume', () => page.getByRole('button', { name: '确认修改并生成建议', exact: true }).last().click());
    await expect.poll(async () => (await get(`/case-change-sets/${confirmed.action.change_set_id}`)).status, { timeout: 240_000 }).toBe('ready');
    expect(await formal()).toEqual(original);
    const notice = page.getByTestId('active-mutation-task-notice');
    if (await notice.isVisible()) await notice.getByRole('button', { name: '前往工作区审阅', exact: true }).click();
    const review = page.locator('.collection-changes__review');
    await expect(review).toBeVisible();
    await postClick('/apply', () => review.getByRole('button', { name: /一键采纳全部待审阅用例/ }).click());
    await page.reload();
    const after = await formal();
    expect(after.find((c: any) => c.id === target.id)).toMatchObject({ title: '青禾借阅验收已确认', revision_number: target.revision_number + 1 });
    expect(after.find((c: any) => c.id !== target.id)).toEqual(original.find((c: any) => c.id !== target.id));
    expect((await state()).id).toBe(journal.conversationId);
    journal.stages.push('same_dialogue_modifies_only_adopted_target');
    journal.after = after;
    expect(journal.errors).toEqual([]);
    await page.screenshot({ path: info.outputPath('completed.png'), fullPage: true });
  } finally { save(); }
});
