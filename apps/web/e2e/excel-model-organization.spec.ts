/* eslint-disable @typescript-eslint/no-explicit-any -- Real-service acceptance snapshots. */
import { expect, test } from '@playwright/test';
import * as XLSX from 'xlsx';
import { writeFileSync } from 'node:fs';

test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1', 'Requires isolated real model services');
test.use({ video: 'off', viewport: { width: 1440, height: 1000 }, actionTimeout: 30_000 });
test.setTimeout(720_000);

test('custom Excel layouts are organized from source cells and reviewed before reuse', async ({ page }, info) => {
  const api = `${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
  const evidence: any = { errors: [] };
  page.on('pageerror', error => evidence.errors.push(error.message));
  const post = async (route: string, data: unknown) => {
    const response = await page.request.post(api + route, { data });
    expect(response.ok(), await response.text()).toBe(true);
    return response.json();
  };
  const get = async (route: string) => {
    const response = await page.request.get(api + route);
    expect(response.ok()).toBe(true);
    return response.json();
  };
  try {
    await post('/auth/register', { email: `excel-organize-${Date.now()}@casepilot.test`, password: 'CasePilot123!', display_name: 'Excel整理验收' });
    await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
    await page.goto('/workbench');
    const composer = page.locator('.new-conversation__composer');
    await expect(composer.locator('textarea')).toBeEnabled({ timeout: 60_000 });
    const book = XLSX.utils.book_new();
    const sheet = XLSX.utils.aoa_to_sheet([
      ['资产号', '检查场景', '准备事项', '操作记录', '判断依据', '归属产品', '重要程度'],
      ['0001', '星桥验证码登录系统：300秒过期', '手机号已启用，测试时钟可控', '签发验证码并记录时间', '', '星桥验证码登录系统', '高'],
      ['', '', '', '推进服务端时钟至签发后300秒，提交验证码登录', '拒绝登录，返回E731', '', ''],
      ['0002', '星桥验证码登录系统：正确验证码登录', '账号已启用', '提交未使用且未过期的正确验证码', '登录成功，建立会话', '星桥验证码登录系统', 'P1'],
      ['0003', '星桥验证码登录系统：缺少预期的历史用例', '账号已启用', '执行登录', '', '星桥验证码登录系统', 'P1'],
    ]);
    sheet['!merges'] = ['A2:A3', 'B2:B3', 'C2:C3', 'F2:F3', 'G2:G3'].map(XLSX.utils.decode_range);
    XLSX.utils.book_append_sheet(book, sheet, '跨行旧用例');
    XLSX.utils.book_append_sheet(book, XLSX.utils.aoa_to_sheet([
      ['信息项', '填写内容'], ['场景名称', '星桥验证码登录系统：退出后会话失效'],
      ['编号', '0004'], ['归属系统', '星桥验证码登录系统'],
      ['操作记录', '用户已登录，执行退出，然后访问受保护页面'],
      ['判断依据', '返回登录页，原会话失效'],
    ]), '纵向卡片');
    const buffer = XLSX.write(book, { type: 'buffer', bookType: 'xlsx' });
    writeFileSync(info.outputPath('非标准用例.xlsx'), buffer);
    const uploading = page.waitForResponse(response => response.url().endsWith('/attachments') && response.request().method() === 'POST');
    await composer.locator('input[type=file]').setInputFiles({ name: '非标准用例.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer });
    const uploaded = await uploading;
    expect(uploaded.ok(), await uploaded.text()).toBe(true);
    const conversation = { id: uploaded.url().match(/conversations\/([^/]+)\/attachments$/)![1] };
    evidence.conversationId = conversation.id;
    await expect(page.locator('.principle-attachment[data-status=ready]')).toContainText('非标准用例.xlsx', { timeout: 300_000 });
    const text = '测试对象：星桥验证码登录系统。参考刚上传Excel整理已有用例，复用适用的、改写变化的、缺少的补齐。只覆盖验证码达到300秒返回E731、正确验证码登录成功、退出后访问受保护页面返回登录页这三个场景。先让我确认参考用例，不要自动纳入正式集合。';
    await composer.locator('textarea').fill(text);
    const pending = page.waitForResponse(response => response.url().endsWith('/messages') && response.request().method() === 'POST');
    await composer.locator('button[type=submit]').click();
    const sent = await pending;
    expect(sent.ok(), await sent.text()).toBe(true);
    const turn = await sent.json();
    await post(`/conversation-operations/${turn.operation_plan.operations[0].id}/confirm-collection`, { create_collection_name: '自由格式Excel验收' });
    const collection = { id: (await get(`/conversations/${conversation.id}`)).collection_id };
    await page.goto(`/workbench/collections/${collection.id}`);
    let state: any;
    await expect.poll(async () => {
      state = await get(`/conversations/${conversation.id}`);
      return state.test_briefs.at(-1)?.content.asset_selection?.status;
    }, { timeout: 300_000, intervals: [1000, 2000] }).toBe('awaiting_confirmation');
    evidence.selection = state.test_briefs.at(-1);
    const selection = evidence.selection.content.asset_selection;
    expect(selection.sources).toHaveLength(3);
    const ids = selection.sources.map((source: any) => source.snapshot.original_id).sort();
    expect(ids).toEqual(['0001', '0002', '0004']);
    expect(selection.sources.every((source: any) => source.snapshot.extraction_method === 'model')).toBe(true);
    const expiry = selection.sources.find((source: any) => source.snapshot.original_id === '0001');
    expect(expiry.locator).toContain('行 2-3');
    expect(expiry.snapshot.steps).toEqual([{ action: '签发验证码并记录时间\n推进服务端时钟至签发后300秒，提交验证码登录', expected: '拒绝登录，返回E731' }]);
    expect(expiry.snapshot.priority).toBe('P0');
    expect(selection.import_report.some((row: any) => row.sheet === '跨行旧用例' && row.row === 5 && !row.valid)).toBe(true);
    expect(await get(`/collections/${collection.id}/test-cases`)).toEqual([]);
    await page.reload();
    const card = page.getByRole('region', { name: '现有用例资产选择' });
    await expect(card).toContainText('上传用例识别结果');
    await expect(card).toContainText('待核对');
    await expect(card).toContainText('纵向卡片');
    await card.getByText('查看用例', { exact: true }).first().click();
    await expect(card).toContainText('300秒');
    await page.screenshot({ path: info.outputPath('organized-preview.png'), fullPage: true });
    const confirmed = page.waitForResponse(response => response.url().endsWith('/generation-assets/confirm') && response.request().method() === 'POST');
    await card.getByRole('button', { name: '确认复用并开始规划', exact: true }).click();
    const response = await confirmed;
    expect(response.ok(), await response.text()).toBe(true);
    evidence.confirmation = await response.json();
    await expect.poll(async () => {
      state = await get(`/conversations/${conversation.id}`);
      const run = state.workflow_runs.find((run: any) => run.job_id === evidence.confirmation.action.job_id);
      if (run?.status === 'failed') throw new Error(JSON.stringify(run));
      return run?.status;
    }, { timeout: 300_000, intervals: [1000, 2000] }).toBe('completed');
    evidence.planning = state.test_briefs.at(-1);
    expect(evidence.planning.content.planning.reuse.decisions.some((decision: any) => decision.source?.kind === 'excel')).toBe(true);
    expect(await get(`/collections/${collection.id}/test-cases`)).toEqual([]);
    expect(evidence.errors).toEqual([]);
    evidence.status = 'passed';
  } finally {
    writeFileSync(info.outputPath('evidence.json'), JSON.stringify(evidence, null, 2));
  }
});
