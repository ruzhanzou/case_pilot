import {expect, test} from '@playwright/test';
import {writeFileSync} from 'node:fs';

test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1', 'Requires real services');
test.setTimeout(300_000);

test('message submission survives lost responses, reload, and an intentional repeat', async ({page}, info) => {
  const api = `${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
  const email = `submission-replay-${Date.now()}@casepilot.test`;
  const registered = await page.request.post(`${api}/auth/register`, {data: {
    email, display_name: '提交恢复验收', password: 'CasePilot123!',
  }});
  expect(registered.ok()).toBeTruthy();
  const account = await registered.json();
  const createdCollection = await page.request.post(
    `${api}/spaces/${account.spaces[0].id}/collections`,
    {data: {name: `提交恢复-${Date.now()}`}},
  );
  expect(createdCollection.ok()).toBeTruthy();
  const collection = await createdCollection.json();
  const createdConversation = await page.request.post(`${api}/conversations`, {
    data: {collection_id: collection.id},
  });
  expect(createdConversation.ok()).toBeTruthy();
  const conversation = await createdConversation.json();

  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  await page.goto(`/workbench/conversations/${conversation.id}`);
  const composer = page.locator('.principle-composer textarea');
  await expect(composer).toBeEnabled({timeout: 60_000});

  const automaticPrompt = '查询当前集合的所有正式用例，只查询不修改。';
  const reloadPrompt = '查询当前集合优先级为P0的正式用例，只查询不修改。';
  const attempts: Array<{content: string; requestId: string; responseUserId?: string}> = [];
  await page.route(`**/api/v1/conversations/${conversation.id}/messages`, async (route) => {
    const body = route.request().postDataJSON() as {content: string; client_request_id: string};
    const samePromptAttempts = attempts.filter((item) => item.content === body.content).length;
    if ((body.content === automaticPrompt && samePromptAttempts === 0)
      || (body.content === reloadPrompt && samePromptAttempts < 2)) {
      const response = await route.fetch({timeout: 120_000});
      expect(response.status()).toBe(202);
      const turn = await response.json();
      attempts.push({content: body.content, requestId: body.client_request_id,
        responseUserId: turn.user_message.id});
      await route.abort('failed');
      return;
    }
    attempts.push({content: body.content, requestId: body.client_request_id});
    await route.continue();
  });

  await composer.fill(automaticPrompt);
  await page.locator('.principle-composer button[type=submit]').click();
  await expect.poll(() => attempts.filter((item) => item.content === automaticPrompt).length,
    {timeout: 120_000}).toBe(2);
  await expect(composer).toBeEnabled({timeout: 60_000});
  const automaticAttempts = attempts.filter((item) => item.content === automaticPrompt);
  expect(automaticAttempts[0].requestId).toBe(automaticAttempts[1].requestId);
  let state = await (await page.request.get(`${api}/conversations/${conversation.id}`)).json();
  expect(state.messages.filter((message: {role: string; content: string}) =>
    message.role === 'user' && message.content === automaticPrompt)).toHaveLength(1);

  await composer.fill(reloadPrompt);
  await page.locator('.principle-composer button[type=submit]').click();
  await expect.poll(() => attempts.filter((item) => item.content === reloadPrompt).length,
    {timeout: 120_000}).toBe(2);
  await expect(composer).toHaveValue(reloadPrompt, {timeout: 60_000});
  const lostAttempts = attempts.filter((item) => item.content === reloadPrompt);
  expect(lostAttempts[0].requestId).toBe(lostAttempts[1].requestId);
  expect(lostAttempts[0].responseUserId).toBe(lostAttempts[1].responseUserId);
  const pendingBeforeReload = await page.evaluate((id) =>
    sessionStorage.getItem(`casepilot.submission.v1:${id}`), conversation.id);
  expect(pendingBeforeReload).toContain(lostAttempts[0].requestId);

  state = await (await page.request.get(`${api}/conversations/${conversation.id}`)).json();
  expect(state.messages.filter((message: {role: string; content: string}) =>
    message.role === 'user' && message.content === reloadPrompt)).toHaveLength(1);
  await page.reload();
  await expect(composer).toBeEnabled({timeout: 60_000});
  await expect.poll(() => page.evaluate((id) =>
    sessionStorage.getItem(`casepilot.submission.v1:${id}`), conversation.id)).toBeNull();

  await composer.fill(reloadPrompt);
  await page.locator('.principle-composer button[type=submit]').click();
  await expect.poll(() => attempts.filter((item) => item.content === reloadPrompt).length,
    {timeout: 120_000}).toBe(3);
  const intentional = attempts.filter((item) => item.content === reloadPrompt)[2];
  expect(intentional.requestId).not.toBe(lostAttempts[0].requestId);
  await expect(composer).toBeEnabled({timeout: 60_000});
  state = await (await page.request.get(`${api}/conversations/${conversation.id}`)).json();
  expect(state.messages.filter((message: {role: string; content: string}) =>
    message.role === 'user' && message.content === reloadPrompt)).toHaveLength(2);

  writeFileSync(info.outputPath('evidence.json'), JSON.stringify({
    email, collection_id: collection.id, conversation_id: conversation.id, attempts, state,
  }, null, 2));
  await page.screenshot({path: info.outputPath('recovered-and-repeated.png'), fullPage: true});
});
