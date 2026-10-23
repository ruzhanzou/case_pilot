import {expect, test} from '@playwright/test';
import {writeFileSync} from 'node:fs';

test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1', 'Requires real services');
test.setTimeout(240_000);

test('first landing message restores its original conversation after both responses are lost', async ({page}, info) => {
  const api = `${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
  const email = `landing-replay-${Date.now()}@casepilot.test`;
  const registered = await page.request.post(`${api}/auth/register`, {data: {
    email, display_name: '首页提交恢复验收', password: 'CasePilot123!',
  }});
  expect(registered.ok()).toBeTruthy();
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  await page.goto('/');
  const closeHistory = page.getByRole('button', {name: '关闭历史对话'}).last();
  if (await closeHistory.isVisible()) await closeHistory.click();

  const prompt = '查询当前集合的P0正式用例，只查询不修改。';
  const attempts: Array<{conversationId: string; requestId: string; userMessageId: string}> = [];
  await page.route('**/api/v1/conversations/*/messages', async (route) => {
    const request = route.request();
    const body = request.postDataJSON() as {client_request_id: string};
    const conversationId = new URL(request.url()).pathname.split('/').at(-2)!;
    const response = await route.fetch({timeout: 120_000});
    expect(response.status()).toBe(202);
    const turn = await response.json();
    attempts.push({conversationId, requestId: body.client_request_id,
      userMessageId: turn.user_message.id});
    await route.abort('failed');
  });

  const composer = page.getByLabel('写给 CasePilot');
  await composer.fill(prompt);
  await page.getByRole('button', {name: '发送', exact: true}).click();
  await expect.poll(() => attempts.length, {timeout: 120_000}).toBe(2);
  expect(attempts[0]).toEqual(attempts[1]);
  await expect(composer).toHaveValue(prompt, {timeout: 60_000});
  await expect(page).toHaveURL(new RegExp(`/workbench/conversations/${attempts[0].conversationId}$`));
  const storageKey = `casepilot.submission.v1:${attempts[0].conversationId}`;
  await expect.poll(() => page.evaluate((key) => sessionStorage.getItem(key), storageKey))
    .toContain(attempts[0].requestId);

  await page.reload();
  await expect(page.locator('.new-conversation__message--user')).toContainText(prompt, {timeout: 60_000});
  await expect(page.locator('.conversation-collection-picker')).toBeVisible({timeout: 60_000});
  await expect.poll(() => page.evaluate((key) => sessionStorage.getItem(key), storageKey)).toBeNull();
  const state = await (await page.request.get(
    `${api}/conversations/${attempts[0].conversationId}`,
  )).json();
  expect(state.messages.filter((message: {role: string; content: string}) =>
    message.role === 'user' && message.content === prompt)).toHaveLength(1);

  writeFileSync(info.outputPath('evidence.json'), JSON.stringify({email, attempts, state}, null, 2));
  await page.screenshot({path: info.outputPath('restored-first-conversation.png'), fullPage: true});
});
