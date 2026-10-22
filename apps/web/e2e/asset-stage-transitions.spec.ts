/* eslint-disable @typescript-eslint/no-explicit-any -- Real cross-stage acceptance evidence. */
import { expect, test } from '@playwright/test';
import { writeFileSync } from 'node:fs';
test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1','Requires isolated real services');
test.use({video:'off'});test.setTimeout(900000);
const api=`${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
for(const kind of ['candidate','formal']) test(`asset search after ${kind} results preserves unrelated work`,async({page},info)=>{
 const evidence:any={kind,events:[]};
 const post=async(route:string,data:any)=>{const r=await page.request.post(api+route,{data,timeout:180000});expect(r.ok(),await r.text()).toBeTruthy();return r.json();};
 const get=async(route:string)=>{const r=await page.request.get(api+route);expect(r.ok()).toBeTruthy();return r.json();};
 try{
  await page.addInitScript(()=>localStorage.setItem('casepilot.locale.v1','zh-CN'));
  const user=await post('/auth/register',{email:`transition-${kind}-${Date.now()}@casepilot.test`,password:'CasePilot123!',display_name:'阶段衔接验收'});
  const space=user.spaces[0].id;
  const origin=await post(`/spaces/${space}/collections`,{name:'账号验收系统原始资产'});
  const target=await post(`/spaces/${space}/collections`,{name:'账号验收系统当前工作'});
  const body={title:'账号验收系统登录成功',module:'账号验收系统',priority:'P1',case_type:'functional',preconditions:['账号user01已启用，正确密码Good123!'],steps:[{action:'打开登录表单，输入user01与Good123!，点击登录',expected:'建立会话'}]};
  const asset=await post(`/collections/${origin.id}/test-cases`,body);
  const conversation=await post('/conversations',{collection_id:target.id,title:'当前任务'});const cid=conversation.id;
  const waitJob=async(job:string)=>{let state:any;await expect.poll(async()=>{state=await get(`/conversations/${cid}`);const run=state.workflow_runs.find((r:any)=>r.job_id===job);if(run?.status==='failed')throw Error(JSON.stringify(run));return run?.status;},{timeout:300000,intervals:[1000,2000]}).toBe('completed');return state;};
  const chat=async(content:string)=>{
   await page.goto(`/workbench/collections/${target.id}`);
   const input=page.getByRole('textbox',{name:'对话消息',exact:true});await expect(input).toBeEnabled();await input.fill(content);
   const reply=page.waitForResponse(r=>r.url().endsWith('/messages')&&r.request().method()==='POST');
   await page.getByRole('button',{name:'发送',exact:true}).click();const response=await reply;
   expect(response.ok(),await response.text()).toBeTruthy();const result=await response.json();evidence.events.push({content,result});return result;
  };
  let before:any[]=[];
  if(kind==='candidate'){
   const initial=await post(`/conversations/${cid}/messages`,{content:'测试对象：账号验收系统。全新生成2条用例，不复用历史。规则一：启用账号user01用Good123!登录后建立会话。规则二：登录后退出会话失效。不添加其他规则。'});
   let state=await waitJob(initial.action.job_id);
   expect(state.test_briefs.at(-1).content.planning.test_points).toHaveLength(2);
   const generate=await post(`/workspaces/${cid}/test-briefs/confirm`,{version:state.test_briefs.at(-1).version});state=await waitJob(generate.action.job_id);before=state.candidates;evidence.before=before;
   const search=await chat('帮我找找以前登录那块的用例，参考当前测试点，仅重新生成接下来确认的测试点，其他候选保留。');
   state=await waitJob(search.action.job_id);const brief=state.test_briefs.at(-1);
   expect(state.candidates.filter((c:any)=>c.status==='candidate').map((c:any)=>c.id).sort()).toEqual(before.map((c:any)=>c.id).sort());
   expect(brief.content.asset_selection.target_points).toHaveLength(2);
   const point=brief.content.asset_selection.target_points.find((p:any)=>p.title.includes('登录'))??brief.content.asset_selection.target_points[0];
   const chosen=await post(`/workspaces/${cid}/generation-assets/confirm`,{version:brief.version,case_ids:[asset.id],test_point_ids:[point.id]});
   state=await waitJob(chosen.action.job_id);const revised=state.test_briefs.at(-1);expect(revised.content.planning.test_points.map((p:any)=>p.id)).toEqual([point.id]);
   const regenerate=await post(`/workspaces/${cid}/test-briefs/confirm`,{version:revised.version});state=await waitJob(regenerate.action.job_id);
   const unaffected=before.filter((c:any)=>!c.snapshot.test_point_ids.includes(point.id));
   expect(state.candidates).toHaveLength(2);
   for(const candidate of unaffected)expect(state.candidates.find((c:any)=>c.id===candidate.id)).toEqual(candidate);
   evidence.after=state;evidence.status='passed';
  }else{
   const current=await post(`/collections/${target.id}/test-cases`,{...body,title:'账号验收系统待完善登录用例',steps:[{action:'登录',expected:'建立会话'}]});
   const sibling=await post(`/collections/${target.id}/test-cases`,{...body,title:'账号验收系统其他用例'});before=[current,sibling];
   const search=await chat(`测试对象：账号验收系统。帮我找类似登录流程的用例参考，改写${current.case_key}的操作步骤，使其明确可执行，标题、优先级、前置条件、预期保持不变，不修改其他用例。`);
   let state=await waitJob(search.action.job_id);const brief=state.test_briefs.at(-1);
   expect(brief.content.asset_selection.followup_intent).toBe('CASE_MODIFY');
   const chosen=await post(`/workspaces/${cid}/generation-assets/confirm`,{version:brief.version,case_ids:[asset.id]});
   expect(chosen.intent).toBe('CASE_MODIFY');expect(chosen.action.job_id).toBeFalsy();expect(chosen.assistant_message.metadata.modification_confirmation).toBe(true);
   state=await get(`/conversations/${cid}`);const operation=state.operation_plan.operations.find((o:any)=>o.intent==='CASE_MODIFY');
   const modify=await post(`/conversation-operations/${operation.id}/resume`,{confirm_modification:true});await waitJob(modify.action.job_id);
   const change=await get(`/case-change-sets/${modify.action.change_set_id}`);expect(change.status).toBe('ready');expect(await get(`/collections/${target.id}/test-cases`)).toEqual(before);
   await page.goto(`/workbench/collections/${target.id}`);
   const apply=page.locator('.collection-changes__review').getByRole('button',{name:/一键采纳全部待审阅用例/});await expect(apply).toBeVisible({timeout:60000});
   const applied=page.waitForResponse(r=>r.url().endsWith('/apply')&&r.request().method()==='POST');await apply.click();expect((await applied).ok()).toBeTruthy();
   const after=await get(`/collections/${target.id}/test-cases`);const modified=after.find((c:any)=>c.id===current.id);
   expect(modified.title).toBe(current.title);expect(modified.steps).not.toEqual(current.steps);expect(modified.steps.map((s:any)=>s.expected).filter(Boolean)).toEqual(['建立会话']);
   expect(after.find((c:any)=>c.id===sibling.id)).toEqual(sibling);
   expect(JSON.stringify(modified.source_refs)).toContain(asset.id);
   expect((await get(`/collections/${origin.id}/test-cases`))[0]).toEqual(asset);
   const finished=await get(`/conversations/${cid}`);
   const finishedOperation=finished.operation_plan.operations.find((o:any)=>o.id===operation.id);
   expect(finishedOperation.payload.task_intent).toBe('CASE_MODIFY');
   expect(finishedOperation.result.task_closed).toBe(true);
   evidence.after=after;evidence.change=change;evidence.status='passed';
  }
  await page.goto(`/workbench/collections/${target.id}`);await expect(page.getByTestId('workspace-case-sources')).toBeVisible({timeout:60000});await expect(page.getByText('正在恢复工作区',{exact:true})).toBeHidden();
  if(kind==='formal'){await expect(page.locator('.case-task-detail__actions .case-task-status')).toHaveText('已完成');await expect(page.locator('.case-task-detail > header h3')).toHaveText('修改用例');}
  await page.screenshot({path:info.outputPath('result.png'),fullPage:true});
 }finally{writeFileSync(info.outputPath('evidence.json'),JSON.stringify(evidence,null,2));}
});
