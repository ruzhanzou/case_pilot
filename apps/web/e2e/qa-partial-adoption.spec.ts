/* eslint-disable @typescript-eslint/no-explicit-any -- Resumable live-QA journals retain heterogeneous API responses; assertions below validate each stage. */
import { test, expect, type Page } from '@playwright/test';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1', 'Requires real services and model');
test.use({ actionTimeout: 30000, viewport: { width: 1600, height: 1000 }, video: { mode: 'on', size: { width: 1600, height: 1000 } }, trace: 'on' });
const api = `${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
const dir = resolve(process.env.CASEPILOT_ACCEPTANCE_OUTPUT ?? '../../output/qa-usability/partial-adoption-deep');
async function send(page: Page, content: string) {
  const input=page.locator('.principle-composer textarea');await expect(input).toBeEnabled({timeout:300000});await input.fill(content);
  const pending=page.waitForResponse(r=>r.request().method()==='POST'&&/\/(messages|resume)$/.test(new URL(r.url()).pathname),{timeout:180000});
  await page.locator('.principle-composer button[type=submit]').click();const response=await pending;expect(response.ok(),await response.text()).toBeTruthy();return response.json();
}

test('generation partial adoption followed by substantive repeated natural language editing and final adoption', async ({page}) => {
  test.setTimeout(1800000);mkdirSync(dir,{recursive:true});
  const journal: any = process.env.CASEPILOT_CHAIN_RESUME ? JSON.parse(readFileSync(process.env.CASEPILOT_CHAIN_RESUME,'utf8')) : { stages:{}, responses:{}, observations:[] };
  const save=()=>writeFileSync(`${dir}/partial-adoption-results.json`,JSON.stringify(journal,null,2));
  const errors:string[]=[];const documents:string[]=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.resourceType()==='document'&&r.frame()===page.mainFrame())documents.push(r.url());});
  await page.addInitScript(()=>localStorage.setItem('casepilot.locale.v1','zh-CN'));
  expect((await page.request.post(`${api}/auth/login`,{data:{email:'demo@casepilot.local',password:'CasePilot123!'}})).ok()).toBeTruthy();
  if(!journal.collection){
    const me=await (await page.request.get(`${api}/auth/me`)).json();
    const response=await page.request.post(`${api}/spaces/${me.spaces[0].id}/collections`,{data:{name:`QA 部分采纳后持续修改-${Date.now()}`,description:'生成→部分采纳→多轮正文改写→逐条采纳→继续修改→全部纳入'}});expect(response.ok()).toBeTruthy();journal.collection=await response.json();save();
  }
  await page.goto(journal.conversationId?`/workbench/conversations/${journal.conversationId}`:`/workbench/collections/${journal.collection.id}`);
  const state=async()=>await (await page.request.get(`${api}/conversations/${journal.conversationId}`)).json();
  const formal=async()=>await (await page.request.get(`${api}/collections/${journal.collection.id}/test-cases`)).json();
  const notice=page.getByTestId('active-mutation-task-notice');const candidates=page.locator('.task-result-cases');const review=page.locator('.collection-changes__review');
  const stage=async(name:string,work:()=>Promise<void>)=>{if(journal.stages[name])return;await test.step(name,work);journal.stages[name]=true;save();};
  const request=async(name:string,content:string)=>{if(journal.responses[name]?.action.type==='clarification'){journal.observations.push({name,clarification:journal.responses[name]});delete journal.responses[name];save();}if(!journal.responses[name]){journal.responses[name]=await send(page,content);save();}if(journal.responses[name].requires_intent_confirmation){journal.intentFallback=journal.responses[name];save();const confirmation=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/confirm-intent'),{timeout:180000});await page.locator('.conversation-intent-confirmation').getByRole('button',{name:'修改用例',exact:true}).click();const r=await confirmation;expect(r.ok()).toBeTruthy();journal.responses[name]=await r.json();save();}return journal.responses[name];};
  const openReview=async()=>{await expect(page.locator('.principle-composer textarea')).toBeEnabled({timeout:300000});await notice.getByRole('button',{name:'前往工作区审阅',exact:true}).click();const latest=(await state()).operation_history.filter((o:any)=>o.intent==='CASE_MODIFY').at(-1);if(latest?.related_change_set_id){const c=await(await page.request.get(`${api}/case-change-sets/${latest.related_change_set_id}`)).json();if(c.items.length)await expect(review).toContainText(`修改方案 V${Math.max(...c.items.map((i:any)=>i.proposal_version??1))}`);}};
  const ready=async(turn:any)=>{
    expect(turn.action.change_set_id,JSON.stringify(turn.action)).toBeTruthy();
    await expect.poll(async()=>{const c=await (await page.request.get(`${api}/case-change-sets/${turn.action.change_set_id}`)).json();if(c.status==='failed')throw new Error(JSON.stringify(c));return c.status;},{timeout:300000}).toBe('ready');
    await openReview();await expect(review).toBeVisible();
    return await (await page.request.get(`${api}/case-change-sets/${turn.action.change_set_id}`)).json();
  };
  await stage('01_generate_three',async()=>{
    const turn=await request('generate','为「账号登录」模块生成恰好3条候选测试用例，每个场景1条：已启用且未锁定账号输入正确密码，返回HTTP 200和非空access_token；同一账号输入错误密码，返回HTTP 401且不签发令牌；已锁定账号输入正确密码，返回HTTP 423且不签发令牌。测试账号user_id为qa_user_001。只覆盖这三个场景，不增加其他功能，不直接纳入正式集合。');
    journal.conversationId=turn.conversation_id;save();
    if ((await state()).candidates.length !== 3 && (await state()).context.phase !== 'generating') { await expect(page.getByRole('button',{name:'确认范围并生成用例',exact:true})).toBeEnabled({timeout:300000});await page.getByRole('button',{name:'确认范围并生成用例',exact:true}).click(); }
    await expect.poll(async()=>{const s=await state();const failed=s.workflow_runs.find((r:any)=>r.operation==='generate'&&r.status==='failed');if(failed){journal.generationFailure=failed;save();throw new Error(`Generation failed: ${failed.error_code}`);}return s.candidates.length;},{timeout:600000}).toBe(3);
    await expect(candidates.locator(':scope > details')).toHaveCount(3);journal.generated=await state();expect(await formal()).toHaveLength(0);await page.screenshot({path:`${dir}/01-generated-three.png`,fullPage:true});
  });
  await stage('02_adopt_one_before_modifying',async()=>{
    await openReview();if (!journal.firstFormal) { const remaining=(await state()).candidates;
    journal.firstRef=remaining[0].ref;journal.remainingRefs=remaining.slice(1).map((c:any)=>c.ref);save();
    for(const c of remaining.slice(1)){await candidates.getByRole('checkbox',{name:`纳入 ${c.ref}`,exact:true}).uncheck();await expect(page.locator('.principle-composer textarea')).toBeEnabled();}
    await candidates.getByRole('button',{name:'纳入已选候选',exact:true}).click();await expect.poll(async()=>(await formal()).length).toBe(1);journal.firstFormal=await formal();save(); }
    await expect(notice).toBeVisible();await expect(candidates).toContainText('已纳入');await expect(candidates).toContainText('待审阅');
    await page.screenshot({path:`${dir}/02-partial-before-modification.png`,fullPage:true});
    await expect(candidates.getByRole('button',{name:'继续调整候选',exact:true})).toBeEnabled();
  });
  await stage('03_query_formal_and_return',async()=>{
    const query=await request('query','查询当前集合全部正式用例，只查询，不修改候选。');expect(query.intent).toBe('CASE_QUERY');
    const queryOp=(await state()).operation_history.filter((o:any)=>o.intent==='CASE_QUERY').at(-1);expect(queryOp.result.query_cases).toHaveLength(1);expect(queryOp.result.query_cases[0].id).toBe(journal.firstFormal[0].id);
    await openReview();await expect(candidates).toContainText('待审阅');expect(await formal()).toEqual(journal.firstFormal);
  });
  if(process.env.CASEPILOT_REPAIR_NUMERIC_SCOPE==='1'&&!journal.scopeMismatch){
    const previous=journal.responses.round1;const change=await ready(previous);expect(change.items).toHaveLength(1);
    const row=review.locator('.collection-changes__items > details');await row.evaluate(el=>el.setAttribute('open',''));await row.getByRole('button',{name:'丢弃此建议',exact:true}).click();
    await expect(review).toContainText('待审阅 0 条');journal.scopeMismatch={response:previous,change};delete journal.responses.round1;save();
  }
  await stage('04_first_substantive_rewrite',async()=>{
    const turn=await request('round1','重写剩余未纳入的2条候选用例，已纳入正式集合的用例不得改动。在前置条件增加独立测试环境、可清理浏览器Cookie和localStorage、可查询本次请求对应的登录审计日志。步骤补齐：清理现有登录态，按各自原场景提交凭据，验证原场景对应的HTTP状态码且响应不含access_token，检查Cookie和localStorage均未写入登录令牌，审计日志不得记录明文密码。最多4步，标题、模块、优先级不变。');
    const change=await ready(turn);expect(change.items).toHaveLength(2);expect(change.items.every((i:any)=>i.target_type==='candidate')).toBeTruthy();expect(new Set(change.items.map((i:any)=>i.ref))).toEqual(new Set(journal.remainingRefs));
    for(const i of change.items){expect(i.field_diff.some((d:any)=>d.field==='steps')).toBeTruthy();expect(i.proposed_snapshot.steps.map((s:any)=>s.action+' '+s.expected).join(' ')).toMatch(/Cookie/i);}
    journal.round1=change;expect(await formal()).toEqual(journal.firstFormal);
    const versionBefore=(await state()).candidates.find((c:any)=>c.ref===journal.remainingRefs[0]).version;
    await candidates.getByRole('checkbox',{name:`纳入 ${journal.remainingRefs[0]}`,exact:true}).check();await expect(page.locator('.principle-composer textarea')).toBeEnabled();
    await expect(candidates.getByRole('button',{name:'纳入已选候选',exact:true})).toBeDisabled();await expect(candidates).toContainText('先采纳或丢弃建议');
    const blocked=await page.request.post(`${api}/workspaces/${journal.conversationId}/candidates/commit`,{data:{candidate_ids:[]}});expect(blocked.status()).toBe(409);expect((await blocked.json()).detail).toBe('candidate_changes_need_review');
    expect((await state()).candidates.find((c:any)=>c.ref===journal.remainingRefs[0]).version).toBe(versionBefore);
    await candidates.getByRole('checkbox',{name:`纳入 ${journal.remainingRefs[0]}`,exact:true}).uncheck();await expect(page.locator('.principle-composer textarea')).toBeEnabled();
    expect(await formal()).toEqual(journal.firstFormal);await review.locator('.collection-changes__items > details').evaluateAll(rows=>rows.forEach(row=>row.setAttribute('open','')));await page.screenshot({path:`${dir}/03-first-body-diff.png`,fullPage:true});
  });
  await stage('05_dissatisfied_second_round',async()=>{
    const ref=journal.remainingRefs[0];const turn=await request('round2',`不满意，继续修改候选 ${ref}：把预期写得可直接判断，响应体不得包含access_token和refresh_token，Cookie与localStorage不得新增任何登录令牌；审计日志必须包含user_id=qa_user_001和本次失败结果且不含明文密码。保留上一版前置条件和其他候选的修改，最多4步，不改已纳入用例、标题、模块或优先级。`);
    const change=await ready(turn);expect(change.items).toHaveLength(2);const item=change.items.find((i:any)=>i.ref===ref);expect(item.previous_snapshot).toEqual(journal.round1.items.find((i:any)=>i.ref===ref).proposed_snapshot);expect(JSON.stringify(item.proposed_snapshot)).toContain('refresh_token');
    const untouched=change.items.find((i:any)=>i.ref!==ref);expect(untouched.proposed_snapshot).toEqual(journal.round1.items.find((i:any)=>i.ref===untouched.ref).proposed_snapshot);journal.round2=change;
    expect(await formal()).toEqual(journal.firstFormal);await expect(page.locator('.conversation-task-flow > ol > li')).toHaveCount(2);await page.screenshot({path:`${dir}/04-second-round-keeps-both.png`,fullPage:true});
  });
  await stage('06_accept_one_suggestion',async()=>{
    await openReview();const row=review.locator('.collection-changes__items > details').filter({has:page.locator('summary').filter({hasText:new RegExp('^'+journal.remainingRefs[0]+' ·')})});await row.evaluate(el=>el.setAttribute('open',''));await row.getByRole('button',{name:'采纳此用例',exact:true}).click();await expect(review).toContainText('待审阅 1 条');
    journal.afterSingle=await state();expect(await formal()).toEqual(journal.firstFormal);await expect(notice).toBeVisible();
  });
  await stage('07_modify_again_after_single_acceptance',async()=>{
    const ref=journal.remainingRefs[1];const turn=await request('round3',`继续修改未采纳建议的候选 ${ref}，在前置条件补充「只读审计账号可查询本次登录事件」；步骤补充校验user_id=qa_user_001且审计事件结果为登录失败，不得输出明文密码。保留原HTTP状态码、禁止签发令牌及Cookie和localStorage校验，最多4步，其他候选和已纳入用例不变。`);
    const change=await ready(turn);expect(change.items.find((i:any)=>i.ref===journal.remainingRefs[0]).status).toBe('applied');expect(change.items.filter((i:any)=>!['applied','rejected'].includes(i.status))).toHaveLength(1);expect(JSON.stringify(change.items.find((i:any)=>i.ref===ref).proposed_snapshot)).toContain('只读审计账号');
    await review.getByRole('button',{name:'一键采纳全部待审阅用例（1 条）',exact:true}).click();await expect(notice).toBeVisible();expect(await formal()).toEqual(journal.firstFormal);journal.afterRewrite=await state();
    await page.screenshot({path:`${dir}/05-after-third-round-acceptance.png`,fullPage:true});
  });
  await stage('08_adopt_revised_candidates_and_close',async()=>{
    if ((await formal()).length < 3) { await openReview();for(const c of (await state()).candidates){const checkbox=candidates.getByRole('checkbox',{name:`纳入 ${c.ref}`,exact:true});await checkbox.check();await expect(page.locator('.principle-composer textarea')).toBeEnabled();}
    await candidates.getByRole('button',{name:'纳入已选候选',exact:true}).click();await expect.poll(async()=>(await formal()).length).toBe(3);await expect(notice).toHaveCount(0); }
    const current=await formal();expect(current.find((c:any)=>c.id===journal.firstFormal[0].id)).toEqual(journal.firstFormal[0]);
    for(const candidate of journal.afterRewrite.candidates){const saved=current.find((c:any)=>c.title===candidate.snapshot.title);expect(saved).toBeTruthy();for(const key of ['preconditions','module','priority'])expect(saved[key]).toEqual(candidate.snapshot[key]);expect(saved.steps.map(({action,expected}:any)=>({action,expected}))).toEqual(candidate.snapshot.steps.map(({action,expected}:any)=>({action,expected})));}
    journal.finalState=await state();journal.finalCases=current;expect(journal.finalState.context.active_mutation_task_id).toBeNull();expect(journal.finalState.candidates).toHaveLength(0);
    const mutations=journal.finalState.operation_history.filter((o:any)=>['CASE_GENERATE','CASE_MODIFY'].includes(o.intent));expect(new Set(mutations.map((o:any)=>o.payload.task_id)).size).toBe(1);expect(mutations).toHaveLength(4+(journal.scopeMismatch?1:0));
    await page.screenshot({path:`${dir}/06-final-three-formal-cases.png`,fullPage:true});
  });
  await stage('09_new_task_after_final_acceptance',async()=>{
    const target=journal.finalCases[0];const turn=await request('round4',`继续修改用例 ${target.case_key} 的前置条件，增加「测试结束后恢复账号初始状态」，其他字段保持不变。`);await ready(turn);
    const s=await state();const latest=s.operation_history.filter((o:any)=>o.intent==='CASE_MODIFY').at(-1);expect(latest.payload.task_id).not.toBe(journal.finalState.operation_history.find((o:any)=>o.intent==='CASE_GENERATE').payload.task_id);await expect(page.locator('.conversation-task-flow > ol > li')).toHaveCount(3);
    await page.getByRole('button',{name:'放弃当前任务',exact:true}).click();await expect(notice).toHaveCount(0);expect(await formal()).toEqual(journal.finalCases);
  });
  expect(errors).toEqual([]);expect(documents).toHaveLength(1);journal.passed=true;journal.errors=errors;journal.documents=documents;save();
});

test('remaining candidate multi intent query rewrite discard revise and abandon', async ({page}) => {
  test.setTimeout(1500000);mkdirSync(dir,{recursive:true});
  const journal:any=process.env.CASEPILOT_CHAIN_RESUME?JSON.parse(readFileSync(process.env.CASEPILOT_CHAIN_RESUME,'utf8')):{stages:{},responses:{}};
  const save=()=>writeFileSync(`${dir}/discard-branch-results.json`,JSON.stringify(journal,null,2));
  const stage=async(name:string,work:()=>Promise<void>)=>{if(journal.stages[name])return;await test.step(name,work);journal.stages[name]=true;save();};
  const request=async(name:string,content:string)=>{if(name==='multi'&&journal.responses[name]?.action.type==='clarification'){journal.originalMulti=journal.responses[name];journal.responses[name]=await send(page,'查询剩余未纳入的候选用例。');save();}if(!journal.responses[name]){journal.responses[name]=await send(page,content);save();}if(journal.responses[name].requires_intent_confirmation){journal.intentFallback=journal.responses[name];save();const confirmation=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/confirm-intent'),{timeout:180000});await page.locator('.conversation-intent-confirmation').getByRole('button',{name:'修改用例',exact:true}).click();const r=await confirmation;expect(r.ok()).toBeTruthy();journal.responses[name]=await r.json();save();}return journal.responses[name];};
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));await page.addInitScript(()=>localStorage.setItem('casepilot.locale.v1','zh-CN'));
  const login=await page.request.post(`${api}/auth/login`,{data:{email:'demo@casepilot.local',password:'CasePilot123!'}});expect(login.ok()).toBeTruthy();const account=await login.json();
  if(!journal.collection){const r=await page.request.post(`${api}/spaces/${account.spaces[0].id}/collections`,{data:{name:`QA 部分采纳与丢弃-${Date.now()}`,description:'多意图查询改写、丢弃后重写、保留已采纳'}});expect(r.ok()).toBeTruthy();journal.collection=await r.json();save();}
  await page.goto(journal.conversationId?`/workbench/conversations/${journal.conversationId}`:`/workbench/collections/${journal.collection.id}`);
  const state=async()=>await(await page.request.get(`${api}/conversations/${journal.conversationId}`)).json();const formal=async()=>await(await page.request.get(`${api}/collections/${journal.collection.id}/test-cases`)).json();
  const notice=page.getByTestId('active-mutation-task-notice');const candidates=page.locator('.task-result-cases');const review=page.locator('.collection-changes__review');const open=async()=>await notice.getByRole('button',{name:'前往工作区审阅',exact:true}).click();
  await stage('01_generate',async()=>{const turn=await request('generate','为「密码重置」模块生成恰好2条候选用例：已注册邮箱接收有效期10分钟的重置链接，有效期内设置12位新密码后可以登录；超过10分钟的链接必须禁止重置并提示重新申请。只覆盖这两个场景，每场景1条，先供我审阅，不纳入正式集合。');journal.conversationId=turn.conversation_id;save();if((await state()).candidates.length!==2 && (await state()).context.phase !== 'generating'){await expect(page.getByRole('button',{name:'确认范围并生成用例',exact:true})).toBeEnabled({timeout:300000});await page.getByRole('button',{name:'确认范围并生成用例',exact:true}).click();}await expect.poll(async()=>{const s=await state();const failed=s.workflow_runs.find((r:any)=>r.status==='failed');if(failed)throw new Error(failed.error_code);return s.candidates.length;},{timeout:600000}).toBe(2);journal.generated=await state();});
  await stage('02_partial',async()=>{await open();if(!journal.firstFormal){const remaining=(await state()).candidates;journal.target=remaining[1];save();await candidates.getByRole('checkbox',{name:`纳入 ${journal.target.ref}`,exact:true}).uncheck();await expect(page.locator('.principle-composer textarea')).toBeEnabled();await candidates.getByRole('button',{name:'纳入已选候选',exact:true}).click();await expect.poll(async()=>(await formal()).length).toBe(1);journal.firstFormal=await formal();save();}await expect(notice).toBeVisible();});
  await stage('03_multi_intent',async()=>{
    await request('multi','先查询剩余未纳入的候选用例，然后修改查到的候选：在前置条件增加「使用独立测试邮箱并可调整测试时钟」，步骤明确记录链接签发时间、当前测试时间和两者间隔，保留原有效期及结果规则、标题、模块和优先级；已纳入用例不变。');
    await expect.poll(async()=>{const s=await state();const op=s.operation_history.filter((o:any)=>o.intent==='CASE_MODIFY').at(-1);if(op?.status==='awaiting_target')throw new Error(JSON.stringify(op.payload.plan));return op?.status;},{timeout:300000}).toBe('awaiting_confirmation');
    await open();await expect(review).toContainText('测试时钟');journal.afterMulti=await state();const queries=journal.afterMulti.operation_history.filter((o:any)=>o.intent==='CASE_QUERY');expect(queries.at(-1).result.query_cases).toHaveLength(1);expect(journal.afterMulti.context.active_mutation_task_id).toBe(journal.generated.context.active_mutation_task_id);
    expect(await formal()).toEqual(journal.firstFormal);await page.screenshot({path:`${dir}/01-multi-intent-one-remaining.png`,fullPage:true});
  });
  await stage('04_discard_suggestion',async()=>{await open();const row=review.locator('.collection-changes__items > details');await row.evaluate(el=>el.setAttribute('open',''));await row.getByRole('button',{name:'丢弃此建议',exact:true}).click();await expect(notice).toBeVisible();const current=(await state()).candidates[0];expect(current.snapshot).toEqual(journal.target.snapshot);expect(await formal()).toEqual(journal.firstFormal);});
  await stage('05_rewrite_after_discard',async()=>{
    const turn=await request('rewrite',`刚才那版不要。重新修改剩余候选 ${journal.target.ref}：前置条件增加「已准备专用只读审计账号」；步骤补充记录重置请求结果并验证审计日志中不包含新密码明文。保留原测试场景和规则，不改已纳入用例。`);expect(turn.action.change_set_id).toBeTruthy();
    await expect.poll(async()=>(await(await page.request.get(`${api}/case-change-sets/${turn.action.change_set_id}`)).json()).status,{timeout:300000}).toBe('ready');await open();await expect(review).toContainText('只读审计账号');
    const change=await(await page.request.get(`${api}/case-change-sets/${turn.action.change_set_id}`)).json();expect(change.items[0].base_snapshot).toEqual(journal.target.snapshot);expect(JSON.stringify(change.items[0].proposed_snapshot)).not.toContain('使用独立测试邮箱并可调整测试时钟');
    await review.getByRole('button',{name:'一键采纳全部待审阅用例（1 条）',exact:true}).click();await expect(notice).toBeVisible();expect(await formal()).toEqual(journal.firstFormal);await page.screenshot({path:`${dir}/02-rewrite-after-discard.png`,fullPage:true});
  });
  await stage('06_abandon_remaining',async()=>{await open();await page.getByRole('button',{name:'放弃当前任务',exact:true}).click();await expect(notice).toHaveCount(0);expect(await formal()).toEqual(journal.firstFormal);const s=await state();expect(s.candidates).toHaveLength(0);expect(s.candidate_history.filter((c:any)=>c.status==='excluded')).toHaveLength(1);expect(s.candidate_history.filter((c:any)=>c.status==='incorporated')).toHaveLength(1);expect(s.context.active_mutation_task_id).toBeNull();journal.finalState=s;await page.screenshot({path:`${dir}/03-abandoned-preserves-adopted.png`,fullPage:true});});
  expect(errors).toEqual([]);journal.passed=true;journal.errors=errors;save();
});

test('completed task history supports read only comparison long content and filtering',async({page})=>{
  test.skip(!process.env.CASEPILOT_HISTORY_JOURNAL,'Requires a completed real-model chain');
  const source=JSON.parse(readFileSync(process.env.CASEPILOT_HISTORY_JOURNAL!,'utf8'));mkdirSync(dir,{recursive:true});
  await page.addInitScript(()=>localStorage.setItem('casepilot.locale.v1','zh-CN'));expect((await page.request.post(`${api}/auth/login`,{data:{email:'demo@casepilot.local',password:'CasePilot123!'}})).ok()).toBeTruthy();
  const read=async()=>await(await page.request.get(`${api}/collections/${source.collection.id}/test-cases`)).json();const before=await read();
  await page.goto(`/workbench/conversations/${source.conversationId}`);await page.locator('.principle-viewbar').getByRole('button',{name:'用例工作区',exact:true}).click();
  await page.getByRole('button',{name:/^历史结果 ·/}).click();await page.locator('#case-task-history').getByRole('button').filter({hasText:'生成用例'}).click();
  const version=page.getByRole('combobox',{name:'查看修改版本',exact:true});await expect(version.locator('option')).toHaveCount(4);await version.selectOption({index:2});
  const review=page.locator('.collection-changes__review');await expect(review).toContainText('修改方案 V3');await expect(page.locator('.case-task-revisions')).toContainText('当前为历史版本');
  await expect(review.getByRole('button',{name:'采纳此用例',exact:true})).toHaveCount(0);await expect(review.getByRole('button',{name:/一键采纳/})).toHaveCount(0);await expect(page.locator('.task-result-cases')).toHaveCount(0);
  const search=review.getByRole('textbox',{name:'按编号、标题或模块查找变更',exact:true});await search.fill(source.remainingRefs[0]);await expect(review.locator('.collection-changes__items > details')).toHaveCount(1);
  const row=review.locator('.collection-changes__items > details');if(!(await row.evaluate(el=>(el as HTMLDetailsElement).open)))await row.locator('summary').click();
  const expand=row.getByRole('button',{name:/展开完整内容.*建议内容.*步骤/});await expect(expand).toBeVisible();await expand.click();
  const content=row.getByRole('region',{name:/建议内容.*步骤/});await expect(content).toContainText('refresh_token');await expect(content).toContainText('qa_user_001');
  expect(await content.evaluate(el=>el.scrollHeight<=el.clientHeight+2)).toBeTruthy();expect(await content.evaluate(el=>el.scrollWidth<=el.clientWidth+2)).toBeTruthy();await content.scrollIntoViewIfNeeded();await page.screenshot({path:`${dir}/01-history-long-content.png`,fullPage:true});
  await review.getByRole('button',{name:'相对上一版变化',exact:true}).click();await expect(review).toContainText('上一版方案');await page.screenshot({path:`${dir}/02-previous-version-comparison.png`,fullPage:true});
  await page.setViewportSize({width:1280,height:900});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+2)).toBeTruthy();await page.screenshot({path:`${dir}/03-1280-review-layout.png`,fullPage:true});
  await search.clear();await page.getByRole('button',{name:'返回最新版本',exact:true}).click();await expect(review).toContainText('修改方案 V4');await expect(page.locator('.task-result-cases')).toContainText('已纳入');
  expect(await read()).toEqual(before);writeFileSync(`${dir}/history-audit.json`,JSON.stringify({passed:true,conversationId:source.conversationId,readOnly:true,longContentExpanded:true,comparison:true,filtering:true,viewport1280:true,formalCasesUnchanged:true},null,2));
});
