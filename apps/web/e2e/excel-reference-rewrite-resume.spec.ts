/* eslint-disable @typescript-eslint/no-explicit-any -- Synthetic real-provider QA evidence. */
import {expect,test} from '@playwright/test';
import {readFileSync,writeFileSync} from 'node:fs';
test.skip(!process.env.CASEPILOT_EXCEL_REWRITE_FIXTURE,'Requires isolated real services');
test.use({video:'off'});test.setTimeout(1200000);
const api=`${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
test('confirmed Excel reference changes existing candidate actions and retains bindings',async({page},info)=>{
 const evidence:any={turns:[],checks:[],errors:[]};page.on('pageerror',e=>evidence.errors.push(e.message));
 const post=async(route:string,data:any)=>{const r=await page.request.post(api+route,{data,timeout:180000});expect(r.ok(),await r.text()).toBeTruthy();return r.json();};
 const get=async(route:string)=>{const r=await page.request.get(api+route);expect(r.ok()).toBeTruthy();return r.json();};
 try{
  await page.addInitScript(()=>localStorage.setItem('casepilot.locale.v1','zh-CN'));
  const fixture=JSON.parse(readFileSync(process.env.CASEPILOT_EXCEL_REWRITE_FIXTURE!, 'utf8'));
  await post('/auth/login',{email:fixture.email,password:'CasePilot123!'});
  const collection={id:fixture.collectionId};const cid=fixture.conversationId;
  evidence.conversationId=cid;evidence.collectionId=collection.id;
  await page.goto(`/workbench/collections/${collection.id}`);
  const waitJob=async(job:string)=>{let state:any;await expect.poll(async()=>{state=await get(`/conversations/${cid}`);const run=state.workflow_runs.find((r:any)=>r.job_id===job);if(run?.status==='failed')throw Error(JSON.stringify(run));return run?.status;},{timeout:360000,intervals:[1000,2000]}).toBe('completed');return state;};
  let state=await get(`/conversations/${cid}`);
  const before=state.candidates;evidence.before=before;expect(before).toHaveLength(2);
  expect(before.every((c:any)=>c.status==='candidate')).toBe(true);
  const target=before.find((c:any)=>JSON.stringify(c.snapshot.steps).includes('E731'));expect(target).toBeTruthy();
  expect(JSON.stringify(target.snapshot)).toMatch(/300|5\s*分钟/);expect(JSON.stringify(before)).toContain('E419');
  expect((await get(`/collections/${collection.id}/test-cases`))).toHaveLength(0);
  const previous=state.operation_plan.operations.find((o:any)=>o.intent==='CASE_MODIFY'&&o.payload.asset_reference_sources?.length);
  expect(previous).toBeTruthy();
  evidence.confirmedSources=previous.payload.asset_reference_sources;
  expect(evidence.confirmedSources.map((source:any)=>source.snapshot.original_id)).toEqual(['OLD-001']);
  const turn=await post(`/conversations/${cid}/messages`,{content:previous.payload.instruction.replace('查找刚上传Excel里的已有用例作为参考，','继续按已确认的参考修改，'),source_operation_id:previous.id,intent_override:'CASE_MODIFY'});
  evidence.turns.push(turn);expect(turn.intent).toBe('CASE_MODIFY');
  state=await get(`/conversations/${cid}`);const op=state.operation_plan.operations.find((o:any)=>o.intent==='CASE_MODIFY'&&o.status==='awaiting_target');
  expect(op).toBeTruthy();expect(op.payload.asset_reference_sources).toEqual(previous.payload.asset_reference_sources);
  const modify=await post(`/conversation-operations/${op.id}/resume`,{confirm_modification:true});await waitJob(modify.action.job_id);
  const change=await get(`/case-change-sets/${modify.action.change_set_id}`);evidence.change=change;expect(change.status).toBe('ready');expect(change.items).toHaveLength(1);
  const proposal=change.items[0].proposed_snapshot;evidence.proposal=proposal;
  expect(change.items[0].quality.passed).toBe(true);
  expect(proposal.steps.map((s:any)=>s.action)).not.toEqual(target.snapshot.steps.map((s:any)=>s.action));
  expect(change.items[0].field_diff.some((diff:any)=>diff.field==='steps')).toBe(true);
  const actions=proposal.steps.map((s:any)=>s.action).join('\n');
  expect(actions).toMatch(/记录.*(?:签发|时刻|时间)|(?:签发|时刻|时间).*记录/);
  expect(actions).toMatch(/300|5\s*分钟/);
  expect(proposal.title).toBe(target.snapshot.title);expect(proposal.priority).toBe(target.snapshot.priority);expect(proposal.preconditions).toEqual(target.snapshot.preconditions);
  expect(proposal.steps.map((s:any)=>s.expected).filter(Boolean)).toEqual(target.snapshot.steps.map((s:any)=>s.expected).filter(Boolean));
  const text=JSON.stringify({preconditions:proposal.preconditions,steps:proposal.steps});expect(text).toMatch(/300|5\s*分钟/);expect(text).not.toMatch(/420|7\s*分钟|PAY-EXPIRED/);
  expect(JSON.stringify(proposal.source_refs)).toContain('旧版用例.xlsx');expect(JSON.stringify(proposal.source_refs)).toContain('OLD-001');
  expect((await get(`/conversations/${cid}`)).candidates).toEqual(before);
  await page.reload();const review=page.locator('.collection-changes__review');const apply=page.waitForResponse(r=>r.url().endsWith('/apply')&&r.request().method()==='POST');await review.getByRole('button',{name:/一键采纳全部待审阅用例/}).click();expect((await apply).ok()).toBeTruthy();
  state=await get(`/conversations/${cid}`);evidence.after=state.candidates;for(const c of before.filter((c:any)=>c.id!==target.id))expect(state.candidates.find((x:any)=>x.id===c.id)).toEqual(c);
  for(const c of state.candidates)expect(c.snapshot.test_point_ids).toEqual(before.find((b:any)=>b.id===c.id).snapshot.test_point_ids);
  expect((await get(`/collections/${collection.id}/test-cases`))).toHaveLength(0);await page.reload();await expect(page.getByText('正在恢复工作区',{exact:true})).toBeHidden();
  await page.getByRole('button',{name:'查看更新后的候选',exact:true}).click();
  await expect(page.getByTestId('workspace-case-sources')).toContainText('旧版用例.xlsx');await expect(page.getByTestId('workspace-case-sources')).toContainText('参考改写');await expect(page.getByTestId('workspace-case-sources')).toContainText('OLD-001');await page.screenshot({path:info.outputPath('completed.png'),fullPage:true});
  await post(`/workspaces/${cid}/candidates/commit`,{candidate_ids:state.candidates.map((c:any)=>c.id)});
  const final=await get(`/conversations/${cid}`);const cases=await get(`/collections/${collection.id}/test-cases`);
  expect(cases).toHaveLength(2);const points=before.flatMap((c:any)=>c.snapshot.test_point_ids);
  for(const c of cases){const links=final.planning_case_links.filter((l:any)=>l.test_case_id===c.id);expect(links.length).toBeGreaterThan(0);for(const l of links){expect(points).toContain(l.test_point_id);expect(l.revision_id).toBe(c.current_revision_id);expect(l.stale).toBe(false);}}
  const rewritten=cases.find((c:any)=>c.title===proposal.title);expect(rewritten).toBeTruthy();
  expect(rewritten.steps.map((s:any)=>({action:s.action,expected:s.expected}))).toEqual(proposal.steps);
  evidence.finalCases=cases;evidence.persistedLinks=final.planning_case_links;
  expect(evidence.errors).toEqual([]);evidence.status='passed';
 }finally{writeFileSync(info.outputPath('evidence.json'),JSON.stringify(evidence,null,2));}
});

test('persisted Excel rewrite retains changed actions and current test-point bindings', async ({page},info)=>{
 test.skip(!process.env.CASEPILOT_EXCEL_REWRITE_RESULT,'Requires a completed rewrite snapshot');
 const fixture=JSON.parse(readFileSync(process.env.CASEPILOT_EXCEL_REWRITE_FIXTURE!,'utf8'));
 const evidence=JSON.parse(readFileSync(process.env.CASEPILOT_EXCEL_REWRITE_RESULT!,'utf8'));
 const login=await page.request.post(`${api}/auth/login`,{data:{email:fixture.email,password:'CasePilot123!'}});expect(login.ok()).toBe(true);
 const stateResponse=await page.request.get(`${api}/conversations/${fixture.conversationId}`);expect(stateResponse.ok()).toBe(true);const state=await stateResponse.json();
 const casesResponse=await page.request.get(`${api}/collections/${fixture.collectionId}/test-cases`);expect(casesResponse.ok()).toBe(true);const cases=await casesResponse.json();
 expect(cases).toHaveLength(2);
 const proposal=evidence.proposal;
 const target=evidence.before.find((c:any)=>c.snapshot.id===proposal.id);
 expect(proposal.steps).not.toEqual(target.snapshot.steps);
 expect(proposal.steps.map((s:any)=>s.expected)).toEqual(target.snapshot.steps.map((s:any)=>s.expected));
 for(const original of evidence.before){
  const formal=cases.find((c:any)=>c.title===original.snapshot.title);expect(formal).toBeTruthy();
  const expected=original.id===target.id?proposal:original.snapshot;
  expect(formal.steps.map((s:any)=>({action:s.action,expected:s.expected}))).toEqual(expected.steps);
  expect(formal.preconditions).toEqual(expected.preconditions);expect(formal.priority).toBe(expected.priority);
  const links=state.planning_case_links.filter((l:any)=>l.test_case_id===formal.id);expect(links.length).toBeGreaterThan(0);
  for(const link of links){expect(original.snapshot.test_point_ids).toContain(link.test_point_id);expect(link.revision_id).toBe(formal.current_revision_id);expect(link.stale).toBe(false);}
 }
 await page.addInitScript(()=>localStorage.setItem('casepilot.locale.v1','zh-CN'));
 await page.goto(`/workbench/collections/${fixture.collectionId}`);
 await page.getByRole('button',{name:'用例列表',exact:true}).click();
 await expect(page.getByText(proposal.title,{exact:true}).filter({visible:true}).first()).toBeVisible();
 await page.screenshot({path:info.outputPath('persisted-rewrite.png'),fullPage:true});
 writeFileSync(info.outputPath('verified.json'),JSON.stringify({status:'passed',before:target.snapshot,after:proposal,cases,links:state.planning_case_links},null,2));
});
