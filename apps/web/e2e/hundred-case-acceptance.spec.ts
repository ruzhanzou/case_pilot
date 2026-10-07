import { expect, test } from '@playwright/test';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1', 'Live model opt-in');
test.use({ viewport: { width: 1600, height: 1000 }, video: 'on', trace: 'on', actionTimeout: 30000 });
const dir = resolve('../../artifacts/hundred-case-acceptance');
const api = `${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
test('new conversation generates and incorporates exactly 100 cases', async ({ page }, info) => {
  test.setTimeout(1800000); mkdirSync(dir, { recursive: true });
  const records: unknown[] = process.env.CASEPILOT_RESUME_CONVERSATION ? JSON.parse(readFileSync(`${dir}/result.json`, 'utf8')).records : []; const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  const save = () => writeFileSync(`${dir}/result.json`, JSON.stringify({ records, errors, url: page.url() }, null, 2));
  const shot = async (name: string) => { await page.screenshot({ path: `${dir}/${name}.png`, fullPage: true }); save(); };
  page.on('response', async response => { if (response.url().includes('/api/v1/') && !response.url().includes('/auth/') && response.request().method() === 'POST') { try { records.push({ url: response.url(), status: response.status(), body: await response.json() }); save(); } catch {} } });
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  let collectionId: string;
  if (process.env.CASEPILOT_RESUME_CONVERSATION) {
    await page.request.post(`${api}/auth/login`, { data: { email: 'demo@casepilot.local', password: 'CasePilot123!' } });
    const resumed = await (await page.request.get(`${api}/conversations/${process.env.CASEPILOT_RESUME_CONVERSATION}`)).json();
    collectionId = resumed.collection_id;
    await page.goto(`/workbench/conversations/${resumed.id}`);
    await expect(page.locator('.principle-workbench')).toBeVisible();
    if (process.env.CASEPILOT_RETRY_GENERATION === '1') {
      await shot('04c-rate-limit-retry');
      await page.getByRole('button', { name: '重试任务', exact: true }).click();
    }
    if (process.env.CASEPILOT_RESTART_GENERATION === '1') {
      const stop = page.getByRole('button', { name: '结束任务', exact: true });
      if (await stop.isVisible()) await stop.click();
      const restart = page.getByRole('button', { name: '确认范围并生成用例', exact: true });
      await expect(restart).toBeEnabled();
      await shot('04a-cancel-and-reconfirm');
      await restart.click();
    }
  } else {
  await page.goto('/');
  await page.getByLabel('邮箱', { exact: true }).fill('demo@casepilot.local');
  await page.getByLabel('密码', { exact: true }).fill('CasePilot123!');
  await page.getByRole('button', { name: '登录并进入工作台' }).click();
  await expect(page.getByRole('heading', { name: '今天想测试什么？' })).toBeVisible();
  const close = page.getByRole('button', { name: '关闭历史对话' }).last(); if (await close.isVisible()) await close.click();
  await shot('01-new-conversation');
  await page.getByRole('combobox', { name: '生成模型' }).selectOption('doubao-seed-2.0-lite');
  await page.getByLabel('写给 CasePilot').fill('创建一份独立的「电商订单深度验收100条」用例集，一次生成恰好100条测试用例。测试对象为电商购物网站，10个模块每个10条：账号登录、商品搜索、商品详情、购物车、优惠券、订单提交、在线支付、订单取消、退款售后、订单查询。规则：密码8到20位，连续5次错误锁定30分钟；搜索词1到100字；购买数量1到99且不得超过库存；价格保留2位小数；优惠券满100减10且不可叠加；订单金额=商品总价-优惠+运费，满99包邮否则10元；未付款30分钟自动取消释放库存；支付回调幂等，重复请求不重复扣款；仅未发货订单可取消；收货后7天内可申请退款，金额不得超过实付；用户只能查看本人订单，列表每页20条。每个模块包含正常、异常、边界值及权限场景，100条标题和测试目标不重复，每条提供前置条件、操作步骤、明确可验证预期和优先级。仅生成候选，等待我确认后纳入正式集合。');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  const clarify = page.getByRole('button', { name: '生成用例', exact: true });
  const picker = page.locator('.conversation-collection-picker');
  await expect(page.locator('.principle-workbench').or(clarify).or(picker)).toBeVisible({ timeout: 180000 });
  if (await clarify.isVisible()) { await clarify.click(); await expect(picker).toBeVisible(); }
  if (await picker.isVisible()) {
    await picker.locator('input').fill(`电商订单深度验收100条-${Date.now()}`);
    await shot('02-confirm-new-collection');
    await picker.locator('button[type=submit]').click();
  }
  await expect(page.locator('.principle-workbench')).toBeVisible({ timeout: 180000 });
  await shot('02-request-started');
  const confirm = page.getByRole('button', { name: /确认范围并生成用例|确认并生成用例/ }).first();
  await expect(confirm).toBeEnabled({ timeout: 600000 });
  const conversationId = page.url().split('/conversations/')[1]?.split(/[/?]/)[0];
  const conversation = conversationId ? await (await page.request.get(`${api}/conversations/${conversationId}`)).json() : null;
  collectionId = conversation?.collection_id ?? page.url().split('/collections/')[1]?.split(/[/?]/)[0];
  expect(collectionId).toBeTruthy();
  expect(await (await page.request.get(`${api}/collections/${collectionId}/test-cases`)).json()).toHaveLength(0);
  await shot('03-scope-awaiting-confirmation');
  await confirm.click(); await shot('04-generating');
  }
  const readCases = async () => (await page.request.get(`${api}/collections/${collectionId}/test-cases`)).json();
  const commit = page.locator('.task-result-cases').getByRole('button', { name: '纳入已选候选', exact: true });
  await expect(page.locator('.task-result-cases').getByRole('button', { name: '纳入已选候选', exact: true })).toBeVisible({ timeout: 1200000 });
  await expect(commit).toBeEnabled();
  const state = await (await page.request.get(`${api}/collections/${collectionId}/workspace`)).json();
  writeFileSync(`${dir}/generated-state.json`, JSON.stringify(state, null, 2));
  expect(state.candidates.filter((c: {status:string}) => c.status === 'candidate')).toHaveLength(100);
  expect(await readCases()).toHaveLength(0); await shot('05-hundred-candidates');
  await commit.click();
  await expect.poll(async () => (await readCases()).length, { timeout: 60000 }).toBe(100);
  await page.reload(); await expect(page.locator('.principle-workbench')).toBeVisible();
  const cases = await readCases(); expect(cases).toHaveLength(100);
  expect(new Set(cases.map((c: {title:string}) => c.title)).size).toBe(100);
  writeFileSync(`${dir}/cases.json`, JSON.stringify(cases, null, 2));
  await shot('06-persisted-hundred'); expect(errors).toEqual([]);
  info.attachments.push({ name: 'evidence', path: `${dir}/result.json`, contentType: 'application/json' });
});
