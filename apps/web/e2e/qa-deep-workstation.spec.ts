import { expect, test, type Page } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1', 'Requires real services and model');
test.use({ viewport: { width: 1600, height: 1000 }, video: { mode: 'on', size: { width: 1600, height: 1000 } }, trace: 'on' });
const dir = resolve(process.env.CASEPILOT_ACCEPTANCE_OUTPUT ?? '../../output/qa-deep-workstation');
const api = `${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
const navigationChecks = new WeakMap<Page, { documents: string[]; intentionalReloads: string[] }>();
test.beforeEach(async ({ page }) => {
  const check = { documents: [] as string[], intentionalReloads: [] as string[] };
  navigationChecks.set(page, check);
  page.on('request', request => {
    if (request.resourceType() === 'document' && request.frame() === page.mainFrame()) check.documents.push(request.url());
  });
});
test.afterEach(async ({ page }, info) => {
  const check = navigationChecks.get(page)!;
  await info.attach('page-load-audit', { body: JSON.stringify(check, null, 2), contentType: 'application/json' });
  if (info.status === 'passed') expect(check.documents, 'Only initial navigation and explicitly requested persistence checks may reload the page').toHaveLength(1 + check.intentionalReloads.length);
});
async function verifyReload(page: Page, reason: string) {
  if (process.env.CASEPILOT_VERIFY_RELOAD === '0') return;
  navigationChecks.get(page)!.intentionalReloads.push(reason);
  await test.step(`主动刷新验收：${reason}`, async () => { await page.reload(); });
}
async function setup(page: Page) {
  mkdirSync(dir,{recursive:true});
  await page.addInitScript(()=>localStorage.setItem('casepilot.locale.v1','zh-CN'));
  const login=await page.request.post(`${api}/auth/login`,{data:{email:'demo@casepilot.local',password:'CasePilot123!'}});
  expect(login.ok()).toBeTruthy(); return login.json();
}
async function seed(page: Page) {
  const account=await setup(page); const stamp=Date.now();
  const res=await page.request.post(`${api}/spaces/${account.spaces[0].id}/collections`,{data:{name:`QA 多轮修改验收-${stamp}`,description:'隔离验收：待确认方案多轮迭代、部分应用与删除'}});
  expect(res.ok()).toBeTruthy();const collection=await res.json();
  for(const [index,module,title] of [[1,'账号登录','正确密码登录成功'],[2,'订单库存','库存不足禁止下单']] as const){
    const r=await page.request.post(`${api}/collections/${collection.id}/test-cases`,{data:{case_key:`QA-${stamp}-${index}`,title,module,priority:'P1',case_type:'功能',tags:['QA验收'],preconditions:['账号已注册且启用'],steps:[{action:'输入账号密码并提交',expected:'登录成功，进入首页'}],source:'QA验收夹具',source_refs:[]}});expect(r.ok()).toBeTruthy();
  }
  return collection;
}
async function readCases(page:Page,id:string){return (await (await page.request.get(`${api}/collections/${id}/test-cases`)).json());}
async function send(page:Page,content:string){
  const composer=page.locator('.principle-composer textarea');await expect(composer).toBeEnabled({timeout:300000});await composer.fill(content);
  const response=page.waitForResponse(r=>r.request().method()==='POST'&&/\/(messages|resume)$/.test(new URL(r.url()).pathname),{timeout:180000});
  await page.locator('.principle-composer button[type=submit]').click();const r=await response;expect(r.ok(),await r.text()).toBeTruthy();return r.json();
}

test('01 QA revises an unconfirmed proposal repeatedly without losing previous changes',async({page})=>{
  test.setTimeout(900000);const collection=await seed(page);const original=await readCases(page,collection.id);const target=original.find((c:{module:string})=>c.module==='账号登录');
  const records:unknown[]=[];const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  writeFileSync(`${dir}/revision-manifest.json`,JSON.stringify({collection,original},null,2));
  await page.goto(`/workbench/collections/${collection.id}`);
  const first=await send(page,`改写用例 ${target.case_key}：仅将标题改为「有效账号登录并进入首页」，其他字段保持不变。`);records.push({round:1,response:first});
  const review=page.locator('.collection-changes__review');await expect(review).toContainText('有效账号登录并进入首页',{timeout:240000});
  await expect(review.locator('.collection-changes__comparison')).toBeVisible();expect(await readCases(page,collection.id)).toEqual(original);
  await page.screenshot({path:`${dir}/01-first-proposal.png`,fullPage:true});
  const second=await send(page,'这一版不满意，保留刚才改好的标题，再把同一条用例的优先级改为P0，其他字段保持不变。');records.push({round:2,response:second});
  writeFileSync(`${dir}/revision-results.json`,JSON.stringify({records,errors},null,2));
  await page.screenshot({path:`${dir}/02-second-response.png`,fullPage:true});
  expect(second.intent).toBe('CASE_MODIFY');
  expect(second.assistant_message.status).not.toBe('awaiting_clarification');
  await expect(review).toContainText('P0',{timeout:240000});
  await expect(review).toContainText('有效账号登录并进入首页');
  expect(await readCases(page,collection.id)).toEqual(original);
  await expect(review).toContainText('修改方案 V2');
  await review.getByRole('button',{name:'相对上一版变化',exact:true}).click();
  await expect(review.locator('.collection-changes__field')).toHaveCount(1);
  await expect(review).toContainText('优先级');
  await expect(review.getByRole('button',{name:'应用已选修改',exact:true})).toHaveCount(0);
  await expect(review.getByRole('button',{name:'返回累计变化并确认',exact:true})).toBeVisible();
  await page.screenshot({path:`${dir}/03-second-round-only-diff.png`,fullPage:true});
  await review.getByRole('button',{name:'累计待应用变化',exact:true}).click();
  await expect(review.locator('.collection-changes__field')).toHaveCount(2);
  await page.screenshot({path:`${dir}/04-cumulative-diff.png`,fullPage:true});
  await review.getByRole('button',{name:'继续调整这版结果',exact:true}).click();
  const third=await send(page,'仅将标题改为「账号登录成功且会话唯一」，保留优先级P0和其他已有修改。');records.push({round:3,response:third});
  await expect(review).toContainText('账号登录成功且会话唯一',{timeout:240000});
  await expect(review).toContainText('修改方案 V3');
  expect(await readCases(page,collection.id)).toEqual(original);
  for(const response of [first,second]){
    const id=response.action.change_set_id;
    expect((await (await page.request.get(`${api}/case-change-sets/${id}`)).json()).status).toBe('superseded');
    expect((await page.request.post(`${api}/case-change-sets/${id}/apply`,{data:{accepted_fields:{}}})).status()).toBe(409);
  }
  await verifyReload(page,'未确认的第三版修改方案可恢复');await expect(review).toContainText('修改方案 V3');
  await review.getByRole('checkbox',{name:'优先级',exact:true}).uncheck();
  await page.screenshot({path:`${dir}/05-third-proposal-partial-approval.png`,fullPage:true});
  await review.getByRole('button',{name:'应用已选修改',exact:true}).click();
  await expect.poll(async()=>(await readCases(page,collection.id)).find((c:{id:string})=>c.id===target.id).revision_number).toBe(2);
  let current=await readCases(page,collection.id);
  expect(current.find((c:{id:string})=>c.id===target.id).title).toBe('账号登录成功且会话唯一');
  expect(current.find((c:{id:string})=>c.id===target.id).priority).toBe('P1');
  expect(current.find((c:{id:string})=>c.id!==target.id)).toEqual(original.find((c:{id:string})=>c.id!==target.id));
  await expect(review).toContainText('未应用的建议');
  await review.getByRole('button',{name:'继续调整这版结果',exact:true}).click();
  const fourth=await send(page,'仅将优先级改为P0，其他字段保持不变。');records.push({round:4,response:fourth});
  await expect(review).toContainText('P0',{timeout:240000});
  await expect(review.locator('.collection-changes__field')).toHaveCount(1);
  await page.screenshot({path:`${dir}/06-rewrite-after-partial-apply.png`,fullPage:true});
  await review.getByRole('button',{name:'应用已选修改',exact:true}).click();
  await expect.poll(async()=>(await readCases(page,collection.id)).find((c:{id:string})=>c.id===target.id).revision_number).toBe(3);
  current=await readCases(page,collection.id);expect(current.find((c:{id:string})=>c.id===target.id).priority).toBe('P0');
  await send(page,`删除用例 ${target.case_key}，保留其他用例。`);
  await expect(review).toContainText('账号登录成功且会话唯一');
  await expect(review).toContainText('账号登录');
  await review.getByRole('button',{name:'取消变更',exact:true}).click();
  await expect(page.locator('.collection-changes__badge')).toHaveText('未应用');
  expect(await readCases(page,collection.id)).toEqual(current);
  await send(page,`删除用例 ${target.case_key}，保留其他用例。`);
  await page.screenshot({path:`${dir}/07-delete-review.png`,fullPage:true});
  await review.getByRole('button',{name:'确认删除已选用例',exact:true}).click();
  await expect.poll(async()=>(await readCases(page,collection.id)).length).toBe(1);
  await verifyReload(page,'确认删除后结果持久化');await expect(page.locator('.principle-composer textarea')).toBeEnabled();
  expect((await readCases(page,collection.id))[0]).toEqual(original.find((c:{id:string})=>c.id!==target.id));
  await page.screenshot({path:`${dir}/08-deletion-persisted.png`,fullPage:true});
  records.push({passed:true,rounds:4,finalCases:await readCases(page,collection.id)});
  writeFileSync(`${dir}/revision-results.json`,JSON.stringify({records,errors},null,2));
  expect(errors).toEqual([]);
});

test('02 QA generates cases, revises candidates twice and only then adds the reviewed result',async({page})=>{
  test.setTimeout(1200000);const account=await setup(page);const stamp=Date.now();
  const r=await page.request.post(`${api}/spaces/${account.spaces[0].id}/collections`,{data:{name:`QA 生成候选深度验收-${stamp}`,description:'候选结果完整性及多轮改写后纳入'}});expect(r.ok()).toBeTruthy();const collection=await r.json();
  await page.goto(`/workbench/collections/${collection.id}`);
  const records:unknown[]=[];const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  const save=()=>writeFileSync(`${dir}/generation-results.json`,JSON.stringify({collection,records,errors},null,2));
  const generated=await send(page,'为「密码重置」模块生成恰好2条新的候选测试用例。测试对象为账号系统：1. 已注册邮箱收到有效期10分钟的重置链接，使用有效链接设置12位新密码后可登录；2. 超过10分钟的链接禁止重置并提示重新申请。前置条件为账号已注册且邮箱可接收邮件。只覆盖这两个场景，先供我审阅，不直接纳入正式集合。');records.push({stage:'generation-request',response:generated});save();
  const confirm=page.getByRole('button',{name:'确认范围并生成用例',exact:true});await expect(confirm).toBeEnabled({timeout:300000});
  expect(await readCases(page,collection.id)).toHaveLength(0);
  await page.screenshot({path:`${dir}/09-generation-scope.png`,fullPage:true});await confirm.click();
  const candidateResults=page.locator('.task-result-cases');await expect(candidateResults.getByRole('button',{name:'纳入已选候选',exact:true})).toBeEnabled({timeout:600000});
  await expect(candidateResults.locator(':scope > details')).toHaveCount(2);
  await candidateResults.locator(':scope > details').evaluateAll(items=>items.forEach(item=>item.setAttribute('open','')));
  await expect(candidateResults).toContainText('前置条件');await expect(candidateResults).toContainText('优先级');await expect(candidateResults).toContainText('预期');
  const cid=generated.conversation_id;
  const getState=async()=>(await (await page.request.get(`${api}/conversations/${cid}`)).json());
  const before=await getState();expect(before.candidates).toHaveLength(2);
  for(const c of before.candidates){expect(c.snapshot.steps.length).toBeGreaterThan(0);expect(c.snapshot.preconditions.length).toBeGreaterThan(0);expect(c.snapshot.module).toBe('密码重置');}
  expect(await readCases(page,collection.id)).toHaveLength(0);
  await page.screenshot({path:`${dir}/10-complete-candidate-results.png`,fullPage:true});
  await candidateResults.getByRole('button',{name:'继续调整候选',exact:true}).click();
  const first=await send(page,'把全部候选的优先级统一改为P2，其他字段保持不变。');records.push({stage:'candidate-round1',response:first});save();
  const review=page.locator('.collection-changes__review');await expect(review).toContainText('P2',{timeout:300000});
  expect((await getState()).candidates.map((c:{snapshot:unknown})=>c.snapshot)).toEqual(before.candidates.map((c:{snapshot:unknown})=>c.snapshot));
  await review.getByRole('button',{name:'继续调整这版结果',exact:true}).click();
  const second=await send(page,'在全部候选的前置条件中增加「QA环境已隔离」，保留刚才的优先级P2、标题和步骤。');records.push({stage:'candidate-round2',response:second});save();
  await expect(review).toContainText('QA环境已隔离',{timeout:300000});
  await expect(review).toContainText('修改方案 V3');
  await expect(review).toContainText('只有另行确认纳入，才会创建正式用例');
  await review.locator('.collection-changes__items > details').evaluateAll(items=>items.forEach(item=>item.setAttribute('open','')));
  await page.screenshot({path:`${dir}/11-candidate-second-round-diff.png`,fullPage:true});
  expect(await readCases(page,collection.id)).toHaveLength(0);
  await review.getByRole('button',{name:'应用已选修改',exact:true}).click();
  await expect(review.getByRole('button',{name:'查看更新后的候选',exact:true})).toBeVisible();
  const updated=await getState();
  for(const c of updated.candidates){expect(c.version).toBe(2);expect(c.snapshot.priority).toBe('P2');expect(c.snapshot.preconditions.join(' ')).toContain('QA环境已隔离');expect(c.snapshot.title).toBe(before.candidates.find((old:{id:string})=>old.id===c.id).snapshot.title);expect(c.snapshot.steps).toEqual(before.candidates.find((old:{id:string})=>old.id===c.id).snapshot.steps);}
  expect(await readCases(page,collection.id)).toHaveLength(0);
  await review.getByRole('button',{name:'查看更新后的候选',exact:true}).click();
  await expect(candidateResults.getByRole('button',{name:'纳入已选候选',exact:true})).toBeEnabled();
  await verifyReload(page,'候选修改后仍可审阅和纳入');await expect(candidateResults.getByRole('button',{name:'纳入已选候选',exact:true})).toBeEnabled();
  await page.screenshot({path:`${dir}/12-revised-candidates-ready-to-add.png`,fullPage:true});
  await candidateResults.getByRole('button',{name:'纳入已选候选',exact:true}).click();
  await expect.poll(async()=>(await readCases(page,collection.id)).length).toBe(2);
  await verifyReload(page,'纳入后的正式用例持久化');const formal=await readCases(page,collection.id);
  for(const c of formal){expect(c.priority).toBe('P2');expect(c.preconditions.join(' ')).toContain('QA环境已隔离');expect(c.revision_number).toBe(1);}
  const final=await getState();expect(final.operation_history.find((op:{id:string})=>op.id===generated.operation_plan.operations[0].id).status).toBe('completed');
  await page.screenshot({path:`${dir}/13-final-reviewed-cases.png`,fullPage:true});
  records.push({passed:true,finalCases:formal,conversationId:cid});save();expect(errors).toEqual([]);
});

test('03 QA handles unchanged requests, stale proposals and safe retries',async({page})=>{
  test.setTimeout(600000);const collection=await seed(page);const original=await readCases(page,collection.id);const target=original[0];
  const records:unknown[]=[];await page.goto(`/workbench/collections/${collection.id}`);
  const unchanged=await send(page,`修改用例 ${target.case_key}，仅将标题改为「${target.title}」，其他字段保持不变。`);records.push({stage:'unchanged',response:unchanged});
  const review=page.locator('.collection-changes__review');await expect(page.locator('.collection-changes__badge')).toHaveText('无需修改',{timeout:240000});
  expect(await readCases(page,collection.id)).toEqual(original);await page.screenshot({path:`${dir}/14-no-change-result.png`,fullPage:true});
  const proposal=await send(page,`修改用例 ${target.case_key}，仅将标题改为「待确认的新标题」，其他字段保持不变。`);records.push({stage:'stale-proposal',response:proposal});
  await expect(review).toContainText('待确认的新标题',{timeout:240000});
  await review.getByRole('checkbox',{name:'标题',exact:true}).uncheck();await expect(review.getByRole('button',{name:'应用已选修改',exact:true})).toBeDisabled();
  await review.getByRole('checkbox',{name:'标题',exact:true}).check();
  // Simulate a second editor saving after the proposal was prepared.
  const concurrent=await page.request.patch(`${api}/test-cases/${target.id}`,{data:{...target,base_revision_id:target.current_revision_id,title:'其他编辑者已更新的标题'}});expect(concurrent.ok()).toBeTruthy();
  const newer=await concurrent.json();const apply=page.waitForResponse(r=>r.url().endsWith(`/case-change-sets/${proposal.action.change_set_id}/apply`));
  await review.getByRole('button',{name:'应用已选修改',exact:true}).click();expect((await apply).status()).toBe(409);
  await expect(page.locator('.collection-changes__badge')).toHaveText('版本冲突');
  await expect(page.locator('.principle-rewrite-status')).toHaveCount(0);
  await expect(page.locator('.case-task-detail > header .case-task-status')).toHaveText('版本冲突');
  expect((await readCases(page,collection.id)).find((c:{id:string})=>c.id===target.id).title).toBe(newer.title);
  await page.screenshot({path:`${dir}/15-stale-proposal-blocked.png`,fullPage:true});
  const fresh=await send(page,`修改用例 ${target.case_key}，仅将标题改为「基于最新版本的最终标题」，其他字段保持不变。`);records.push({stage:'fresh-proposal',response:fresh});
  await expect(review).toContainText('基于最新版本的最终标题',{timeout:240000});await expect(review).toContainText(newer.title);
  await review.getByRole('button',{name:'应用已选修改',exact:true}).click();
  await expect.poll(async()=>(await readCases(page,collection.id)).find((c:{id:string})=>c.id===target.id).revision_number).toBe(3);
  const after=await readCases(page,collection.id);
  const repeat=await page.request.post(`${api}/case-change-sets/${fresh.action.change_set_id}/apply`,{data:{accepted_fields:{[target.id]:['title']}}});expect(repeat.ok()).toBeTruthy();expect(await readCases(page,collection.id)).toEqual(after);
  await verifyReload(page,'冲突恢复后保存结果持久化');await expect(page.locator('.principle-composer textarea')).toBeEnabled();
  await page.screenshot({path:`${dir}/16-fresh-version-applied-once.png`,fullPage:true});
  records.push({passed:true,finalCases:after});writeFileSync(`${dir}/conflict-results.json`,JSON.stringify({collection,records},null,2));
});

test('04 explicit case identity and missing module never broaden modification scope',async({page})=>{
  test.setTimeout(300000);
  const collection=await seed(page);const original=await readCases(page,collection.id);
  const target=original[0], other=original[1];
  await page.goto(`/workbench/collections/${collection.id}`);
  const turn=await send(page,`修改用例 ${target.case_key}：仅将标题改为「${other.title}」，其他字段保持不变。`);
  expect(turn.intent).toBe('CASE_MODIFY');
  const review=page.locator('.collection-changes__review');
  await expect(review).toContainText(other.title,{timeout:180000});
  const change=await (await page.request.get(`${api}/case-change-sets/${turn.action.change_set_id}`)).json();
  expect(change.items.map((item:{ref:string})=>item.ref)).toEqual([target.id]);
  expect(await readCases(page,collection.id)).toEqual(original);
  await review.getByRole('button',{name:'应用已选修改',exact:true}).click();
  await expect.poll(async()=>(await readCases(page,collection.id)).find((c:{id:string})=>c.id===target.id).title).toBe(other.title);
  const after=await readCases(page,collection.id);expect(after.find((c:{id:string})=>c.id===other.id)).toEqual(other);
  await page.screenshot({path:`${dir}/17-title-does-not-expand-target.png`,fullPage:true});
  const missing=await send(page,'修改「不存在账号登录」模块，优先级统一改为P0。');
  expect(missing.action.type).toBe('clarification');
  expect(missing.assistant_message.target_case_ids).toEqual([]);
  expect(await readCases(page,collection.id)).toEqual(after);
  await page.screenshot({path:`${dir}/18-missing-module-no-fallback.png`,fullPage:true});
  writeFileSync(`${dir}/scope-results.json`,JSON.stringify({passed:true,collection,turn,missing,original,after},null,2));
});

test('05 withdraw one draft change while preserving other changes and protected module',async({page})=>{
  test.setTimeout(360000);const collection=await seed(page);const original=await readCases(page,collection.id);
  const target=original.find((c:{module:string})=>c.module==='账号登录');
  await page.goto(`/workbench/collections/${collection.id}`);
  const first=await send(page,'仅修改「账号登录」模块：标题改为「新版登录验证」，优先级改为P0，其他字段保持不变。不要修改「订单库存」模块。');
  const review=page.locator('.collection-changes__review');
  await expect(review).toContainText('新版登录验证',{timeout:180000});
  const readChange=async(id:string)=>(await page.request.get(`${api}/case-change-sets/${id}`)).json();
  const v1=await readChange(first.action.change_set_id);
  expect(v1.items.map((i:{ref:string})=>i.ref)).toEqual([target.id]);
  expect(v1.items[0].proposed_snapshot.priority).toBe('P0');
  expect(await readCases(page,collection.id)).toEqual(original);
  await review.getByRole('button',{name:'继续调整这版结果',exact:true}).click();
  const second=await send(page,'上一轮优先级不改了，恢复为原来的P1；保留刚才改好的标题「新版登录验证」，其他字段不变。');
  await expect(review).toContainText('修改方案 V2',{timeout:180000});
  const v2=await readChange(second.action.change_set_id);
  expect(v2.items.map((i:{ref:string})=>i.ref)).toEqual([target.id]);
  expect(v2.items[0].proposed_snapshot.priority).toBe('P1');
  expect(v2.items[0].proposed_snapshot.title).toBe('新版登录验证');
  expect(v2.items[0].field_diff.map((d:{field:string})=>d.field)).toEqual(['title']);
  await expect(review.getByRole('checkbox',{name:'优先级',exact:true})).toHaveCount(0);
  await page.screenshot({path:`${dir}/19-withdraw-priority-cumulative.png`,fullPage:true});
  await review.getByRole('button',{name:'相对上一版变化',exact:true}).click();
  await expect(review).toContainText('P0');await expect(review).toContainText('P1');
  await page.screenshot({path:`${dir}/20-withdraw-priority-previous.png`,fullPage:true});
  await review.getByRole('button',{name:'返回累计变化并确认',exact:true}).click();
  await review.getByRole('button',{name:'应用已选修改',exact:true}).click();
  await expect.poll(async()=>(await readCases(page,collection.id)).find((c:{id:string})=>c.id===target.id).revision_number).toBe(2);
  const after=await readCases(page,collection.id);
  expect(after.find((c:{id:string})=>c.id===target.id).priority).toBe('P1');
  expect(after.filter((c:{id:string})=>c.id!==target.id)).toEqual(original.filter((c:{id:string})=>c.id!==target.id));
  writeFileSync(`${dir}/withdraw-results.json`,JSON.stringify({passed:true,collection,first,second,v1,v2,original,after},null,2));
});

test('06 lost apply response reconciles saved result without duplicate application',async({page})=>{
  test.setTimeout(240000);const collection=await seed(page);const original=await readCases(page,collection.id);const target=original[0];
  await page.goto(`/workbench/collections/${collection.id}`);
  const turn=await send(page,`修改用例 ${target.case_key}：仅将标题改为「响应丢失仍已保存」，其他字段保持不变。`);
  const review=page.locator('.collection-changes__review');
  await expect(review).toContainText('响应丢失仍已保存',{timeout:180000});
  let appliedRequests=0;
  await page.route(`**/case-change-sets/${turn.action.change_set_id}/apply`,async route=>{
    const response=await route.fetch();expect(response.ok()).toBeTruthy();appliedRequests++;
    await route.abort('failed');
  });
  await review.getByRole('button',{name:'应用已选修改',exact:true}).click();
  await expect(page.locator('.collection-changes__badge')).toHaveText('已应用');
  await expect(page.locator('.case-task-detail > header .case-task-status')).toHaveText('已完成');
  const after=await readCases(page,collection.id);expect(after.find((c:{id:string})=>c.id===target.id).revision_number).toBe(2);
  expect(after.filter((c:{id:string})=>c.id!==target.id)).toEqual(original.filter((c:{id:string})=>c.id!==target.id));
  expect(appliedRequests).toBe(1);
  await page.screenshot({path:`${dir}/21-lost-response-reconciled.png`,fullPage:true});
  writeFileSync(`${dir}/lost-response-results.json`,JSON.stringify({passed:true,collection,turn,after,appliedRequests},null,2));
});

test('07 review cases individually then accept all remaining suggestions',async({page})=>{
  test.setTimeout(360000);const collection=await seed(page);
  const existing=await readCases(page,collection.id);
  const create=await page.request.post(`${api}/collections/${collection.id}/test-cases`,{data:{...existing[0],case_key:`ROW-${Date.now()}`,title:'第三条待审阅用例',module:'第三模块'}});expect(create.ok()).toBeTruthy();
  const original=await readCases(page,collection.id);
  await page.goto(`/workbench/collections/${collection.id}`);
  const turn=await send(page,'将当前集合全部用例的优先级改为P0，其他字段保持不变。');
  const review=page.locator('.collection-changes__review');await expect(review).toContainText('P0',{timeout:180000});
  const rows=review.locator('.collection-changes__items > details');
  await expect(rows).toHaveCount(3);
  const first=rows.filter({hasText:original[0].case_key});await first.locator('summary').click();
  await first.getByRole('button',{name:'采纳此用例',exact:true}).click();
  await expect(review).toContainText('已采纳 1 条 · 已丢弃 0 条 · 待审阅 2 条');
  await expect(page.locator('.task-version-notice')).toHaveCount(0);
  await expect(page.getByText('2 条用例待审阅变更',{exact:true})).toBeVisible();
  let after=await readCases(page,collection.id);
  expect(after.find((c:{id:string})=>c.id===original[0].id).priority).toBe('P0');
  expect(after.filter((c:{id:string})=>c.id!==original[0].id)).toEqual(original.filter((c:{id:string})=>c.id!==original[0].id));
  await page.screenshot({path:`${dir}/22-single-case-accepted.png`,fullPage:true});
  const repeat=await page.request.post(`${api}/case-change-sets/${turn.action.change_set_id}/apply`,{data:{review_refs:[original[0].id],accepted_fields:{[original[0].id]:['priority']}}});expect(repeat.ok()).toBeTruthy();
  expect(await readCases(page,collection.id)).toEqual(after);
  const second=rows.filter({hasText:original[1].case_key});await second.locator('summary').click();
  await second.getByRole('button',{name:'丢弃此建议',exact:true}).click();
  await expect(review).toContainText('已采纳 1 条 · 已丢弃 1 条 · 待审阅 1 条');
  expect(await readCases(page,collection.id)).toEqual(after);
  await page.screenshot({path:`${dir}/23-single-case-discarded.png`,fullPage:true});
  await review.getByRole('button',{name:'一键采纳全部待审阅用例（1 条）',exact:true}).click();
  await expect(review).toContainText('已采纳 2 条 · 已丢弃 1 条 · 待审阅 0 条');
  await expect(page.locator('.case-task-detail > header .case-task-status')).toHaveText('已完成');
  after=await readCases(page,collection.id);
  expect(after.find((c:{id:string})=>c.id===original[1].id)).toEqual(original[1]);
  for(const c of after.filter((c:{id:string})=>c.id!==original[1].id)){expect(c.priority).toBe('P0');expect(c.revision_number).toBe(2);}
  await expect(page.locator('.principle-messages')).toContainText('已采纳 2 条用例变更，已丢弃 1 条建议，剩余 0 条待审阅。');
  await page.screenshot({path:`${dir}/24-all-remaining-accepted.png`,fullPage:true});
  writeFileSync(`${dir}/item-review-results.json`,JSON.stringify({passed:true,collection,turn,original,after},null,2));
});

test('08 multi intent query modify delete pauses at each mutation review',async({page})=>{
  test.setTimeout(360000);const collection=await seed(page);const original=await readCases(page,collection.id);
  const login=original.find((c:{module:string})=>c.module==='账号登录'), order=original.find((c:{module:string})=>c.module==='订单库存');
  await page.goto(`/workbench/collections/${collection.id}`);
  const turn=await send(page,'先查询当前集合全部用例，然后将账号登录模块用例的标题改为「登录多意图验收」，其他字段不变；最后删除订单库存模块的用例，每个变更都由我审阅确认。');
  writeFileSync(`${dir}/multi-intent-request.json`,JSON.stringify({collection,original,turn},null,2));
  const state=async()=>(await page.request.get(`${api}/conversations/${turn.conversation_id}`)).json();
  const operations=async()=> (await state()).operation_history.filter((op:{source_message_id:string})=>op.source_message_id===turn.user_message.id).sort((a:{sequence:number},b:{sequence:number})=>a.sequence-b.sequence);
  await expect.poll(async()=>(await operations()).map((op:{status:string})=>op.status),{timeout:180000}).toEqual(['completed','awaiting_confirmation','queued']);
  expect((await operations()).map((op:{intent:string})=>op.intent)).toEqual(['CASE_QUERY','CASE_MODIFY','CASE_DELETE']);
  expect(await readCases(page,collection.id)).toEqual(original);
  const review=page.locator('.collection-changes__review');await expect(review).toContainText('登录多意图验收');
  await page.screenshot({path:`${dir}/25-multi-intent-first-confirmation.png`,fullPage:true});
  await review.getByRole('button',{name:'一键采纳全部待审阅用例（1 条）',exact:true}).click();
  await expect.poll(async()=>(await operations()).map((op:{status:string})=>op.status),{timeout:180000}).toEqual(['completed','completed','awaiting_confirmation']);
  await expect(review).toContainText('删除审阅');
  await expect(review).toContainText(order.case_key);await expect(review).not.toContainText(login.case_key);
  const modified=await readCases(page,collection.id);
  expect(modified.find((c:{id:string})=>c.id===login.id).title).toBe('登录多意图验收');
  expect(modified.find((c:{id:string})=>c.id===order.id)).toEqual(order);
  await page.screenshot({path:`${dir}/26-multi-intent-delete-confirmation.png`,fullPage:true});
  await review.getByRole('button',{name:'取消变更',exact:true}).click();
  await expect(page.locator('.collection-changes__badge')).toHaveText('未应用');
  expect(await readCases(page,collection.id)).toEqual(modified);
  await expect(page.locator('.principle-composer textarea')).toBeEnabled();
  writeFileSync(`${dir}/multi-intent-results.json`,JSON.stringify({passed:true,collection,turn,operations:await operations(),original,modified},null,2));
});

test('09 cancelling middle modification stops queued followups and preserves cases',async({page})=>{
  test.setTimeout(360000);const collection=await seed(page);const original=await readCases(page,collection.id);
  await page.goto(`/workbench/collections/${collection.id}`);
  const turn=await send(page,'先查询当前集合全部用例，然后将账号登录模块用例的标题改为「中途取消验收」，其他字段不变；最后删除订单库存模块的用例，每个变更都由我审阅确认。');
  const operations=async()=> (await (await page.request.get(`${api}/conversations/${turn.conversation_id}`)).json()).operation_history.filter((op:{source_message_id:string})=>op.source_message_id===turn.user_message.id).sort((a:{sequence:number},b:{sequence:number})=>a.sequence-b.sequence);
  await expect.poll(async()=>(await operations()).map((op:{status:string})=>op.status),{timeout:180000}).toEqual(['completed','awaiting_confirmation','queued']);
  const review=page.locator('.collection-changes__review');await expect(review).toContainText('中途取消验收');
  await review.getByRole('button',{name:'取消变更',exact:true}).click();
  await expect.poll(async()=>(await operations()).map((op:{status:string})=>op.status)).toEqual(['completed','cancelled','cancelled']);
  expect(await readCases(page,collection.id)).toEqual(original);
  await expect(page.locator('.principle-messages')).toContainText('后续任务已停止');
  await expect(page.getByText('等待前置任务',{exact:true})).toHaveCount(0);
  await expect(page.locator('.principle-composer textarea')).toBeEnabled();
  await page.screenshot({path:`${dir}/27-middle-cancel-followups-stopped.png`,fullPage:true});
  writeFileSync(`${dir}/middle-cancel-results.json`,JSON.stringify({passed:true,collection,turn,operations:await operations(),original,after:await readCases(page,collection.id)},null,2));
});

test('10 one modification task keeps three rounds and the entire pending case set',async({page})=>{
  test.setTimeout(900000);const collection=await seed(page);const original=await readCases(page,collection.id);const target=original[0];
  await page.goto(`/workbench/collections/${collection.id}`);
  const first=await send(page,'将当前集合全部用例的优先级改为P0，其他字段不变。');
  const review=page.locator('.collection-changes__review');await expect(review).toContainText('P0',{timeout:240000});
  await expect(review.locator('.collection-changes__items > details')).toHaveCount(2);
  const second=await send(page,`修改用例 ${target.case_key}：仅将标题改为「持续修改第二版」，保留已有修改。`);
  await expect(review).toContainText('持续修改第二版',{timeout:240000});
  await expect(page.locator('.conversation-task-flow > ol > li')).toHaveCount(1);
  await expect(review.locator('.collection-changes__items > details')).toHaveCount(2);
  const v2=await (await page.request.get(`${api}/case-change-sets/${second.action.change_set_id}`)).json();
  expect(v2.items.every((item:{proposed_snapshot:{priority:string}})=>item.proposed_snapshot.priority==='P0')).toBeTruthy();
  expect(await readCases(page,collection.id)).toEqual(original);
  await review.getByRole('button',{name:'继续调整这版结果',exact:true}).click();
  const third=await send(page,`仍不满意，仅将用例 ${target.case_key} 的标题改为「持续修改最终版」，保留已有优先级修改，其他用例保持上一版方案。`);
  await expect(review).toContainText('持续修改最终版',{timeout:240000});
  await expect(review).toContainText('修改方案 V3');
  await expect(page.locator('.conversation-task-flow > ol > li')).toHaveCount(1);
  await expect(page.getByRole('button',{name:'历史结果 · 1',exact:true})).toBeVisible();
  const v3=await (await page.request.get(`${api}/case-change-sets/${third.action.change_set_id}`)).json();
  expect(v3.items).toHaveLength(2);
  const other=v3.items.find((item:{ref:string})=>item.ref!==target.id);
  expect(other.proposed_snapshot.title).toBe(original.find((c:{id:string})=>c.id!==target.id).title);
  expect(v3.items.every((item:{proposed_snapshot:{priority:string}})=>item.proposed_snapshot.priority==='P0')).toBeTruthy();
  const version=page.getByRole('combobox',{name:'查看修改版本',exact:true});
  await expect(version.locator('option')).toHaveCount(3);
  await version.selectOption(first.operation_plan.operations[0].id);
  await expect(review).not.toContainText('持续修改最终版');
  await expect(review.getByRole('button',{name:/一键采纳/})).toHaveCount(0);
  await page.getByRole('button',{name:'返回最新版本',exact:true}).click();
  await expect(review).toContainText('持续修改最终版');
  await page.screenshot({path:`${dir}/28-one-task-three-revisions.png`,fullPage:true});
  await verifyReload(page,'持续修改任务与全部版本恢复');
  await expect(page.locator('.conversation-task-flow > ol > li')).toHaveCount(1);
  await expect(version.locator('option')).toHaveCount(3);
  await expect(review).toContainText('持续修改最终版');
  await review.getByRole('button',{name:'一键采纳全部待审阅用例（2 条）',exact:true}).click();
  await expect(page.locator('.collection-changes__badge')).toHaveText('已应用');
  const after=await readCases(page,collection.id);
  expect(after.every((c:{priority:string,revision_number:number})=>c.priority==='P0'&&c.revision_number===2)).toBeTruthy();
  expect(after.find((c:{id:string})=>c.id===target.id).title).toBe('持续修改最终版');
  await page.screenshot({path:`${dir}/29-one-task-final-accepted.png`,fullPage:true});
  const conversation=await (await page.request.get(`${api}/conversations/${first.conversation_id}`)).json();
  const rounds=conversation.operation_history.filter((op:{intent:string})=>op.intent==='CASE_MODIFY');
  expect(new Set(rounds.map((op:{payload:{task_id:string}})=>op.payload.task_id)).size).toBe(1);
  writeFileSync(`${dir}/single-task-results.json`,JSON.stringify({passed:true,collection,original,first,second,third,v2,v3,after,rounds},null,2));
});

test('11 acceptance closes the task even when the next request says continue',async({page})=>{
  test.setTimeout(600000);const collection=await seed(page);const original=await readCases(page,collection.id);const target=original[0];
  await page.goto(`/workbench/collections/${collection.id}`);
  const first=await send(page,`修改用例 ${target.case_key}：仅将标题改为「采纳后续改第一版」，其他字段不变。`);
  const review=page.locator('.collection-changes__review');await expect(review).toContainText('采纳后续改第一版',{timeout:240000});
  await review.getByRole('button',{name:'一键采纳全部待审阅用例（1 条）',exact:true}).click();
  await expect(page.locator('.collection-changes__badge')).toHaveText('已应用');
  const second=await send(page,`还是不满意，继续将用例 ${target.case_key} 的标题改为「采纳后续改第二版」，其他字段不变。`);
  await expect(review).toContainText('采纳后续改第二版',{timeout:240000});
  await expect(review).toContainText('修改方案 V1');
  await expect(review).toContainText('基准版本 V2');
  await expect(page.locator('.conversation-task-flow > ol > li')).toHaveCount(2);
  const pending=await readCases(page,collection.id);expect(pending.find((c:{id:string})=>c.id===target.id).title).toBe('采纳后续改第一版');
  await review.getByRole('button',{name:'一键采纳全部待审阅用例（1 条）',exact:true}).click();
  await expect(page.locator('.collection-changes__badge')).toHaveText('已应用');
  const after=await readCases(page,collection.id);expect(after.find((c:{id:string})=>c.id===target.id).revision_number).toBe(3);
  await page.screenshot({path:`${dir}/30-accepted-then-refined-new-task.png`,fullPage:true});
  const third=await send(page,`新建一个独立任务：将用例 ${target.case_key} 的优先级改为P0，其他字段不变。`);
  await expect(review).toContainText('P0',{timeout:240000});
  await expect(page.locator('.conversation-task-flow > ol > li')).toHaveCount(3);
  await expect(page.getByRole('button',{name:'历史结果 · 3',exact:true})).toBeVisible();
  await review.getByRole('button',{name:'取消变更',exact:true}).click();
  expect(await readCases(page,collection.id)).toEqual(after);
  writeFileSync(`${dir}/accepted-refinement-results.json`,JSON.stringify({passed:true,collection,first,second,third,original,after},null,2));
});

test('12 real model rewrites login content through three substantive review rounds',async({page})=>{
  test.setTimeout(1200000);const collection=await seed(page);const original=await readCases(page,collection.id);
  const target=original.find((c:{module:string})=>c.module==='账号登录');
  await page.goto(`/workbench/collections/${collection.id}`);
  const review=page.locator('.collection-changes__review');const rounds:unknown[]=[];
  const prompts=[
    `重写用例 ${target.case_key} 的前置条件、操作步骤和预期结果，标题、模块和优先级保持不变。该用例验证有效账号登录成功后获取当前用户资料。补齐可执行的测试账号准备、清理浏览器登录态、登录请求和登录后访问用户资料的步骤。登录响应须包含非空 access_token，用户资料接口的 user_id 必须等于测试账号的 user_id。每步都要有能直接判断通过或失败的预期结果，不能只写“正常”“成功”。步骤总数不超过4步。订单库存模块不得修改。`,
    `这一版还不满意，继续修改同一条用例。保留上一版登录和 user_id 一致性检查，在前置条件中明确测试账号 user_id=qa_user_001。补充接口级断言：登录返回 HTTP 200，expires_in=1800；使用刚获得的 access_token 请求用户资料也返回 HTTP 200，user_id=qa_user_001。响应和日志不得出现明文密码。将这些验证写入可执行步骤及对应预期，仍不超过4步，标题、模块、优先级不变。`,
    `继续调整这版结果：需求变更，令牌有效期改为15分钟，expires_in=900，替换之前的1800秒要求，最终方案不要保留旧有效期。保留 user_id=qa_user_001、登录及资料接口 HTTP 200、禁止明文密码的检查。增加退出登录后使用原 access_token 再访问用户资料，必须返回 HTTP 401，并且不得返回该用户资料。合理组织成不超过4步，每步给出明确预期。只修改同一条用例的前置条件、步骤和预期结果，其他用例、标题、模块、优先级均不变。`,
  ];
  for(let index=0;index<prompts.length;index++){
    if(index===2)await review.getByRole('button',{name:'继续调整这版结果',exact:true}).click();
    const turn=await send(page,prompts[index]);
    expect(turn.intent).toBe('CASE_MODIFY');expect(turn.action.change_set_id).toBeTruthy();
    const get=async()=> (await page.request.get(`${api}/case-change-sets/${turn.action.change_set_id}`)).json();
    await expect.poll(async()=>(await get()).status,{timeout:240000}).toBe('ready');
    const change=await get();rounds.push({round:index+1,prompt:prompts[index],turn,change});
    writeFileSync(`${dir}/content-rewrite-progress.json`,JSON.stringify({collection,original,rounds},null,2));
    expect(change.items).toHaveLength(1);const item=change.items[0];expect(item.ref).toBe(target.id);
    expect(item.field_diff.some((d:{field:string})=>d.field==='steps')).toBeTruthy();
    expect(item.field_diff.map((d:{field:string})=>d.field)).not.toContain('priority');
    expect(item.proposed_snapshot.title).toBe(target.title);expect(item.proposed_snapshot.module).toBe(target.module);expect(item.proposed_snapshot.priority).toBe(target.priority);
    expect(item.proposed_snapshot.steps.length).toBeLessThanOrEqual(4);
    const text=JSON.stringify(item.proposed_snapshot);expect(text).toContain('access_token');expect(text).toContain('user_id');
    if(index>=1){expect(text).toContain('qa_user_001');expect(text).toContain('200');expect(text).toMatch(/明文密码/);}
    if(index===1)expect(text).toContain('1800');
    if(index===2){expect(text).toContain('900');expect(text).toContain('401');expect(text).not.toContain('1800');expect(text).toMatch(/退出|登出/);}
    expect(await readCases(page,collection.id)).toEqual(original);
    await expect(review).toContainText(`修改方案 V${index+1}`);
    await expect(page.locator('.conversation-task-flow > ol > li')).toHaveCount(1);
    await page.screenshot({path:`${dir}/content-round-${index+1}.png`,fullPage:true});
  }
  await review.getByRole('button',{name:'相对上一版变化',exact:true}).click();
  await expect(review).toContainText('1800');await expect(review).toContainText('900');
  await page.screenshot({path:`${dir}/content-previous-comparison.png`,fullPage:true});
  await review.getByRole('button',{name:'返回累计变化并确认',exact:true}).click();
  await review.getByRole('button',{name:'一键采纳全部待审阅用例（1 条）',exact:true}).click();
  await expect(page.locator('.collection-changes__badge')).toHaveText('已应用');
  const after=await readCases(page,collection.id);const saved=after.find((c:{id:string})=>c.id===target.id);
  expect(saved.revision_number).toBe(2);expect(JSON.stringify(saved.steps)).toContain('401');expect(JSON.stringify(saved.steps)).toContain('900');
  expect(after.filter((c:{id:string})=>c.id!==target.id)).toEqual(original.filter((c:{id:string})=>c.id!==target.id));
  writeFileSync(`${dir}/content-rewrite-results.json`,JSON.stringify({passed:true,collection,original,rounds,after,conversation_url:`http://localhost:3105/workbench/conversations/${(rounds[0] as {turn:{conversation_id:string}}).turn.conversation_id}`},null,2));
});

test('14 mutation lifecycle survives query scope changes and partial decisions with chat link',async({page})=>{
  test.setTimeout(1200000);const collection=await seed(page);const original=await readCases(page,collection.id);
  const login=original.find((c:{module:string})=>c.module==='账号登录'),stock=original.find((c:{module:string})=>c.module==='订单库存');
  await page.goto(`/workbench/collections/${collection.id}`);
  const first=await send(page,`重写用例 ${login.case_key} 的步骤和预期：补齐清理登录态、提交正确凭据、校验登录响应HTTP 200及非空access_token、访问用户资料校验user_id一致性。最多4步，标题模块优先级不变。`);
  const review=page.locator('.collection-changes__review');await expect(review).toContainText('access_token',{timeout:240000});
  const notice=page.getByTestId('active-mutation-task-notice');await expect(notice).toContainText('当前任务尚未结束');
  const query=await send(page,'查询当前集合全部用例，只查询不修改。');expect(query.intent).toBe('CASE_QUERY');
  await expect(page.locator('.task-query-results')).toBeVisible();await expect(page.locator('.conversation-task-flow > ol > li')).toHaveCount(2);
  await expect(notice).toBeVisible();await notice.getByRole('button',{name:'前往工作区审阅',exact:true}).click();await expect(review).toContainText('access_token');
  await page.screenshot({path:`${dir}/lifecycle-query-return.png`,fullPage:true});
  const second=await send(page,`修改用例 ${stock.case_key} 的前置条件，增加独立库存测试数据及可查询订单和库存记录的权限，其他字段不变。`);
  await expect(review).toContainText('库存',{timeout:240000});
  await expect.poll(async()=>(await (await page.request.get(`${api}/case-change-sets/${second.action.change_set_id}`)).json()).status,{timeout:240000}).toBe('ready');
  await expect(review.locator('.collection-changes__items > details')).toHaveCount(2);await expect(page.locator('.conversation-task-flow > ol > li')).toHaveCount(2);
  const loginRow=review.locator('.collection-changes__items > details').filter({hasText:login.case_key});await loginRow.locator('summary').click();
  await loginRow.getByRole('button',{name:'采纳此用例',exact:true}).click();await expect(review).toContainText('待审阅 1 条');await expect(notice).toBeVisible();
  await expect(review.getByRole('button',{name:'继续调整这版结果',exact:true})).toBeEnabled();
  const third=await send(page,`新建一个独立任务：重写用例 ${stock.case_key} 的操作步骤和预期，准备库存1件并提交数量2件的订单，验证下单被拒绝、库存仍为1件且没有创建订单记录。最多4步，保留前置条件，标题模块优先级不变。`);
  await expect.poll(async()=>(await (await page.request.get(`${api}/case-change-sets/${third.action.change_set_id}`)).json()).status,{timeout:240000}).toBe('ready');
  await expect(review).toContainText('订单');await expect(page.locator('.conversation-task-flow > ol > li')).toHaveCount(2);
  await expect(review).toContainText('已采纳 1 条');await expect(notice).toBeVisible();
  await page.screenshot({path:`${dir}/lifecycle-partial-continued.png`,fullPage:true});
  await review.getByRole('button',{name:'一键采纳全部待审阅用例（1 条）',exact:true}).click();await expect(notice).toHaveCount(0);
  const accepted=await readCases(page,collection.id);expect(accepted.every((c:{revision_number:number})=>c.revision_number===2)).toBeTruthy();
  const fourth=await send(page,`修改用例 ${login.case_key} 的前置条件，补充账号没有被锁定且已准备用户资料查询权限，其他字段保持不变。`);
  await expect.poll(async()=>(await (await page.request.get(`${api}/case-change-sets/${fourth.action.change_set_id}`)).json()).status,{timeout:240000}).toBe('ready');
  await expect(page.locator('.conversation-task-flow > ol > li')).toHaveCount(3);await expect(notice).toBeVisible();
  await page.getByRole('button',{name:'放弃当前任务',exact:true}).click();await expect(notice).toHaveCount(0);expect(await readCases(page,collection.id)).toEqual(accepted);
  const state=await (await page.request.get(`${api}/conversations/${first.conversation_id}`)).json();
  const rounds=state.operation_history.filter((op:{intent:string})=>op.intent==='CASE_MODIFY');expect(rounds).toHaveLength(4);
  expect(new Set(rounds.slice(0,3).map((op:{payload:{task_id:string}})=>op.payload.task_id)).size).toBe(1);
  expect(rounds[3].payload.task_id).not.toBe(rounds[0].payload.task_id);expect(state.context.active_mutation_task_id).toBeNull();
  writeFileSync(`${dir}/lifecycle-modify-results.json`,JSON.stringify({passed:true,collection,first,second,third,fourth,original,accepted,state},null,2));
});

test('15 generation remains open through candidate revision and partial adoption',async({page})=>{
  test.setTimeout(1200000);const account=await setup(page);
  const response=await page.request.post(`${api}/spaces/${account.spaces[0].id}/collections`,{data:{name:`QA 生成任务生命周期-${Date.now()}`,description:'候选修改、部分采纳、放弃及对话跳转'}});expect(response.ok()).toBeTruthy();const collection=await response.json();
  await page.goto(`/workbench/collections/${collection.id}`);
  const first=await send(page,'为「密码重置」模块生成恰好2条新的候选测试用例。测试对象为账号系统：1. 已注册邮箱收到有效期10分钟的重置链接，使用有效链接设置12位新密码后可登录；2. 超过10分钟的链接禁止重置并提示重新申请。前置条件为账号已注册且邮箱可接收邮件。只覆盖这两个场景，先供我审阅，不直接纳入正式集合。');
  const notice=page.getByTestId('active-mutation-task-notice');await expect(notice).toBeVisible();
  const confirm=page.getByRole('button',{name:'确认范围并生成用例',exact:true});await expect(confirm).toBeEnabled({timeout:300000});await confirm.click();
  const candidates=page.locator('.task-result-cases');await expect(candidates.getByRole('button',{name:'纳入已选候选',exact:true})).toBeEnabled({timeout:600000});await expect(candidates.locator(':scope > details')).toHaveCount(2);
  await candidates.getByRole('button',{name:'继续调整候选',exact:true}).click();
  const query=await send(page,'查询当前集合全部正式用例，只查询不修改。');expect(query.intent).toBe('CASE_QUERY');expect(query.operation_plan.operations.find((op:{intent:string})=>op.intent==='CASE_QUERY').result.query_cases).toHaveLength(0);await expect(page.locator('.conversation-task-flow > ol > li')).toHaveCount(2);
  await notice.getByRole('button',{name:'前往工作区审阅',exact:true}).click();await expect(candidates).toBeVisible();
  await candidates.getByRole('button',{name:'继续调整候选',exact:true}).click();
  const modified=await send(page,'修改全部候选用例的前置条件，增加专用测试邮箱、可控制测试时钟和可查询重置链接有效期的权限，保留标题、模块和步骤。');
  const review=page.locator('.collection-changes__review');await expect.poll(async()=>(await (await page.request.get(`${api}/case-change-sets/${modified.action.change_set_id}`)).json()).status,{timeout:300000}).toBe('ready');
  await expect(review).toContainText('时钟');await expect(page.locator('.conversation-task-flow > ol > li')).toHaveCount(2);
  await review.getByRole('button',{name:'一键采纳全部待审阅用例（2 条）',exact:true}).click();await expect(notice).toBeVisible();expect(await readCases(page,collection.id)).toHaveLength(0);
  const view=review.getByRole('button',{name:'查看更新后的候选',exact:true});await expect(view).toBeVisible();await view.click();
  await expect(candidates.getByRole('button',{name:'纳入已选候选',exact:true})).toBeEnabled();
  await candidates.getByRole('checkbox').last().uncheck();await candidates.getByRole('button',{name:'纳入已选候选',exact:true}).click();
  await expect.poll(async()=>(await readCases(page,collection.id)).length).toBe(1);await expect(notice).toBeVisible();
  await expect(candidates).toContainText('待审阅');await page.screenshot({path:`${dir}/lifecycle-generation-partial.png`,fullPage:true});
  await page.getByRole('button',{name:'放弃当前任务',exact:true}).click();await expect(notice).toHaveCount(0);expect(await readCases(page,collection.id)).toHaveLength(1);
  const state=await (await page.request.get(`${api}/conversations/${first.conversation_id}`)).json();expect(state.context.active_mutation_task_id).toBeNull();
  expect(state.candidates.filter((c:{status:string})=>c.status==='candidate')).toHaveLength(0);expect(state.candidate_history.filter((c:{status:string})=>c.status==='excluded')).toHaveLength(1);
  const mutations=state.operation_history.filter((o:{intent:string})=>['CASE_GENERATE','CASE_MODIFY'].includes(o.intent));expect(new Set(mutations.map((o:{payload:{task_id:string}})=>o.payload.task_id)).size).toBe(1);
  await page.screenshot({path:`${dir}/lifecycle-generation-closed.png`,fullPage:true});writeFileSync(`${dir}/lifecycle-generation-results.json`,JSON.stringify({passed:true,collection,first,query,modified,state},null,2));
});

test('16 incompatible new task is explained in chat with a working workstation jump',async({page})=>{
  test.setTimeout(600000);const collection=await seed(page);const target=(await readCases(page,collection.id))[0];
  await page.goto(`/workbench/collections/${collection.id}`);
  const first=await send(page,`修改用例 ${target.case_key} 的前置条件，补充隔离测试环境和可查询用户资料的权限，其他字段不变。`);
  const review=page.locator('.collection-changes__review');await expect(review).toContainText('权限',{timeout:240000});
  const blocked=await send(page,'新增「发票管理」模块并生成2条发票申请测试用例。');expect(blocked.action.type).toBe('task_review_required');
  const message=page.locator(`#case-message-${blocked.assistant_message.id}`);await expect(message).toContainText('当前任务尚未采纳或放弃');
  await message.getByRole('button',{name:'前往工作区审阅',exact:true}).click();await expect(review).toContainText('权限');
  await expect(page.locator('.conversation-task-flow > ol > li')).toHaveCount(1);await expect(page.getByTestId('active-mutation-task-notice')).toBeVisible();
  await page.screenshot({path:`${dir}/lifecycle-chat-gate-jump.png`,fullPage:true});
  writeFileSync(`${dir}/lifecycle-gate-results.json`,JSON.stringify({passed:true,collection,first,blocked},null,2));
});

test('17 persisted generation lifecycle audit',async({page})=>{
  test.skip(!process.env.CASEPILOT_LIFECYCLE_AUDIT_ID,'Requires the completed real generation conversation');
  await setup(page);const cid=process.env.CASEPILOT_LIFECYCLE_AUDIT_ID!;
  const response=await page.request.get(`${api}/conversations/${cid}`);expect(response.ok()).toBeTruthy();const state=await response.json();
  expect(state.context.active_mutation_task_id).toBeNull();expect(state.candidates).toHaveLength(0);
  expect(state.candidate_history.filter((c:{status:string})=>c.status==='incorporated')).toHaveLength(1);
  expect(state.candidate_history.filter((c:{status:string})=>c.status==='excluded')).toHaveLength(1);
  const formal=await readCases(page,state.collection_id);expect(formal).toHaveLength(1);expect(formal[0].preconditions.join(' ')).toContain('时钟');
  const mutations=state.operation_history.filter((o:{intent:string})=>['CASE_GENERATE','CASE_MODIFY'].includes(o.intent));expect(mutations).toHaveLength(2);expect(new Set(mutations.map((o:{payload:{task_id:string}})=>o.payload.task_id)).size).toBe(1);
  expect(mutations.every((o:{status:string})=>!o.status.startsWith('awaiting_'))).toBeTruthy();
  expect(state.operation_history.find((o:{intent:string})=>o.intent==='CASE_QUERY').result.query_cases).toHaveLength(0);
  await page.goto(`/workbench/conversations/${cid}`);await expect(page.locator('.conversation-task-flow > ol > li')).toHaveCount(2);await expect(page.getByTestId('active-mutation-task-notice')).toHaveCount(0);
  await page.screenshot({path:`${dir}/lifecycle-generation-closed.png`,fullPage:true});
  writeFileSync(`${dir}/lifecycle-generation-results.json`,JSON.stringify({passed:true,verification:'Persisted audit after real UI generation, candidate modification, partial adoption and abandonment',first:{conversation_id:cid},state,formal},null,2));
});
