import { test, expect, request as requestFactory, type APIRequestContext } from '@playwright/test';
const api = process.env.CASEPILOT_E2E_API_URL ?? 'http://localhost:8015';
test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1', 'Requires isolated migrated API');
test('versioned links reject foreign cases, preserve choice-only revisions, and flag stale case revisions', async ({ request }) => {
  const setup = async (client: APIRequestContext) => {
    const register = await client.post(`${api}/api/v1/auth/register`, { data: { email: `links-${Date.now()}-${Math.random()}@casepilot.test`, password: 'CasePilot123!', display_name: '关联边界验收' } });
    expect(register.status()).toBe(201); const account = await register.json();
    const collection = await (await client.post(`${api}/api/v1/spaces/${account.spaces[0].id}/collections`, { data: { name: '关联校验' } })).json();
    const item = await (await client.post(`${api}/api/v1/collections/${collection.id}/test-cases`, { data: { title: '登录成功', steps: [{ action: '输入正确账号密码并登录', expected: '登录成功' }] } })).json();
    const workspace = await (await client.put(`${api}/api/v1/collections/${collection.id}/workspace`)).json();
    return { workspace, item };
  };
  const { workspace, item } = await setup(request);
  const second = await requestFactory.newContext();
  try {
    const foreign = await setup(second);
    const content = { test_object: '账号登录', planning: {
      feature_points: [{ id: 'F1', name: '登录', module: '账号' }],
      test_points: [{ id: 'P1', title: '正常登录', objective: '账号密码正确可登录', feature_point_ids: ['F1'] }],
      reuse: { strategy: 'fresh', decisions: [{ point_id: 'P1', action: 'new', reason: '无历史用例' }], user_choices: {} as Record<string, string> },
    } };
    const save = async (version: number) => request.post(`${api}/api/v1/workspaces/${workspace.id}/test-briefs`, { data: { content, ...(version ? { base_version: version } : {}) } });
    expect((await save(0)).status()).toBe(201);
    const payload = { brief_version: 1, test_point_id: 'P1', test_case_id: item.id, revision_id: item.current_revision_id };
    const linkUrl = `${api}/api/v1/workspaces/${workspace.id}/test-point-links`;
    expect((await request.put(linkUrl, { data: { ...payload, test_point_id: 'unknown' } })).status()).toBe(422);
    expect((await request.put(linkUrl, { data: { ...payload, test_case_id: foreign.item.id, revision_id: foreign.item.current_revision_id } })).status()).toBe(404);
    expect((await request.put(linkUrl, { data: { ...payload, revision_id: foreign.item.current_revision_id } })).status()).toBe(409);
    expect((await request.put(linkUrl, { data: payload })).status()).toBe(200);
    const duplicate = await request.put(linkUrl, { data: payload });
    expect(await duplicate.json()).toHaveLength(1);
    content.planning.reuse.user_choices = { P1: 'exclude' };
    expect((await save(1)).status()).toBe(201);
    const state = await (await request.get(`${api}/api/v1/conversations/${workspace.id}`)).json();
    expect(state.planning_case_links.map((l: { brief_version: number }) => l.brief_version)).toEqual([1, 2]);
    expect((await request.put(linkUrl, { data: payload })).status()).toBe(409);
    const changed = await request.patch(`${api}/api/v1/test-cases/${item.id}`, { data: { base_revision_id: item.current_revision_id, title: '登录成功（更新）', steps: [{ action: '输入正确账号密码并登录', expected: '进入首页' }] } });
    expect(changed.status()).toBe(200);
    const newCase = await changed.json();
    const stale = await (await request.get(`${api}/api/v1/conversations/${workspace.id}`)).json();
    expect(stale.planning_case_links.every((l: { stale: boolean }) => l.stale)).toBeTruthy();
    expect((await request.put(linkUrl, { data: { ...payload, brief_version: 2, revision_id: newCase.current_revision_id } })).status()).toBe(200);
    content.planning.test_points[0].objective = '需求改变，需重新核实覆盖';
    expect((await save(2)).status()).toBe(201);
    const changedPlan = await (await request.get(`${api}/api/v1/conversations/${workspace.id}`)).json();
    expect(changedPlan.planning_case_links.filter((l: { brief_version: number }) => l.brief_version === 3)).toHaveLength(0);
    expect((await request.put(linkUrl, { data: { ...payload, brief_version: 3, revision_id: newCase.current_revision_id } })).status()).toBe(200);
    expect((await request.put(linkUrl, { data: { ...payload, brief_version: 3, remove: true } })).status()).toBe(200);
    const removed = await (await request.get(`${api}/api/v1/conversations/${workspace.id}`)).json();
    expect(removed.planning_case_links.filter((l: { brief_version: number }) => l.brief_version === 3)).toHaveLength(0);
  } finally { await second.dispose(); }
});
