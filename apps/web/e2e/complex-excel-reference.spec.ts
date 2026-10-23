/* eslint-disable @typescript-eslint/no-explicit-any -- Synthetic real-provider QA evidence. */
import {expect,test} from '@playwright/test';
import * as XLSX from 'xlsx';
import {writeFileSync} from 'node:fs';
test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE!=='1','Requires isolated real services');
test.use({video:'off'});test.setTimeout(1200000);
const api=`${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
test('negative reuse clause followed by explicit Excel search respects selected rows',async({page},info)=>{
 const evidence:any={turns:[],checks:[],errors:[]};page.on('pageerror',e=>evidence.errors.push(e.message));
 const post=async(route:string,data:any)=>{const r=await page.request.post(api+route,{data,timeout:180000});expect(r.ok(),await r.text()).toBeTruthy();return r.json();};
 const get=async(route:string)=>{const r=await page.request.get(api+route);expect(r.ok()).toBeTruthy();return r.json();};
 try{
  await page.addInitScript(()=>localStorage.setItem('casepilot.locale.v1','zh-CN'));
  const user=await post('/auth/register',{email:`deep-excel-${Date.now()}@casepilot.test`,password:'CasePilot123!',display_name:'深度质量验收'});
  const collection=await post(`/spaces/${user.spaces[0].id}/collections`,{name:'星桥验证码登录系统质量回归'});
  const conversation=await post('/conversations',{collection_id:collection.id,title:'多轮Excel参考'});const cid=conversation.id;evidence.conversationId=cid;evidence.collectionId=collection.id;
  await page.goto(`/workbench/collections/${collection.id}`);
  const chat=async(content:string)=>{
   const input=page.locator('.principle-composer textarea');await expect(input).toBeEnabled();await input.fill(content);
   const response=page.waitForResponse(r=>/\/(messages|resume)$/.test(r.url())&&r.request().method()==='POST',{timeout:180000});
   await page.locator('.principle-composer button[type=submit]').click();const r=await response;expect(r.ok(),await r.text()).toBeTruthy();const value=await r.json();evidence.turns.push({content,result:value});return value;
  };
  const waitJob=async(job:string)=>{let state:any;await expect.poll(async()=>{state=await get(`/conversations/${cid}`);const run=state.workflow_runs.find((r:any)=>r.job_id===job);if(run?.status==='failed')throw Error(JSON.stringify(run));return run?.status;},{timeout:360000,intervals:[1000,2000]}).toBe('completed');return state;};
  const first=await chat('测试对象：星桥验证码登录系统。全新生成，不搜索或复用历史。严格2个测试点，每点1条：R1 测试开始前已成功为手机号13800000001签发验证码并记录签发时刻，签发后经过时间达到300秒即过期，登录失败返回E731；R1步骤不得重新签发验证码。R2 连续输错验证码达到4次锁定账号1140秒，锁定期间返回E419。环境提供推进服务端时钟、重置错误次数的测试接口；手机号13800000001已注册且启用。不得自行补充其他规则。先规划。');
  let state=await waitJob(first.action.job_id);expect(state.test_briefs.at(-1).content.planning.test_points).toHaveLength(2);
  const generated=await post(`/workspaces/${cid}/test-briefs/confirm`,{version:state.test_briefs.at(-1).version});state=await waitJob(generated.action.job_id);
  const before=state.candidates;evidence.before=before;expect(before).toHaveLength(2);
  const target=before.find((c:any)=>JSON.stringify(c.snapshot.steps).includes('E731'));expect(target).toBeTruthy();
  expect(JSON.stringify(target.snapshot)).toMatch(/300|5\s*分钟/);expect(JSON.stringify(before)).toContain('E419');
  expect(target.snapshot.preconditions.join('\n')).toMatch(/已.*签发|签发.*完成/);
  expect((await get(`/collections/${collection.id}/test-cases`))).toHaveLength(0);
  const workbook=XLSX.utils.book_new();XLSX.utils.book_append_sheet(workbook,XLSX.utils.aoa_to_sheet([
   ['用例编号','用例名称','模块','优先级','前置条件','测试步骤','预期结果'],
   ['OLD-001','星桥验证码登录系统验证码过期','星桥验证码登录系统','P1','手机号13800000001已注册，服务端测试时钟可控','调用签发接口获取验证码并记录签发时刻；推进服务端时钟到签发后420秒；提交手机号和验证码登录','登录失败，返回E731'],
   ['OLD-002','星桥验证码登录系统错误锁定','星桥验证码登录系统','P1','手机号13800000001已启用，错误次数为0','连续4次提交错误验证码，再提交正确验证码','锁定期间返回E419，锁定时长1140秒'],
   ['OTHER-001','支付系统验证码过期','支付系统','P0','支付订单待确认','推进支付时钟到60秒，提交支付验证码','返回PAY-EXPIRED'],
   ['BAD-001','缺少预期的旧用例','星桥验证码登录系统','P1','账号有效','提交登录',''],
  ]),'旧版用例');
  const buffer=XLSX.write(workbook,{type:'buffer',bookType:'xlsx'});writeFileSync(info.outputPath('旧版用例.xlsx'),buffer);
  await page.reload();await expect(page.locator('.principle-composer input[type=file]')).toBeEnabled();const upload=page.waitForResponse(r=>r.url().endsWith('/attachments')&&r.request().method()==='POST');
  await page.locator('.principle-composer input[type=file]').setInputFiles({name:'旧版用例.xlsx',mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer});
  expect((await upload).ok()).toBeTruthy();await expect(page.locator('.principle-attachment[data-status=ready]')).toContainText('旧版用例.xlsx',{timeout:90000});
  const search=await chat(`测试对象：星桥验证码登录系统。先别复用，但请搜一下刚上传Excel里的已有用例让我确认后参考改写，只改写候选${target.ref}的步骤。原Excel是旧规则，当前仍是300秒即过期，不能沿用420秒。标题、优先级、前置条件、预期保持不变，其他候选不修改。`);
  state=await waitJob(search.action.job_id);const brief=state.test_briefs.at(-1);evidence.selection=brief;
  const sources=brief.content.asset_selection.sources;expect(sources.some((s:any)=>s.kind==='excel')).toBe(true);
  expect(sources.some((s:any)=>s.snapshot.original_id==='OTHER-001'||s.snapshot.original_id==='BAD-001')).toBe(false);
  const selected=sources.find((s:any)=>s.kind==='excel'&&s.snapshot.original_id==='OLD-001');expect(selected).toBeTruthy();
  const chosen=await post(`/workspaces/${cid}/generation-assets/confirm`,{version:brief.version,case_ids:[selected.case_id]});expect(chosen.intent).toBe('CASE_MODIFY');
  state=await get(`/conversations/${cid}`);const op=state.operation_plan.operations.find((o:any)=>o.intent==='CASE_MODIFY');
  const modify=await post(`/conversation-operations/${op.id}/resume`,{confirm_modification:true});await waitJob(modify.action.job_id);
  const change=await get(`/case-change-sets/${modify.action.change_set_id}`);evidence.change=change;expect(change.status).toBe('ready');expect(change.items).toHaveLength(1);
  const proposal=change.items[0].proposed_snapshot;evidence.proposal=proposal;
  expect(proposal.title).toBe(target.snapshot.title);expect(proposal.priority).toBe(target.snapshot.priority);expect(proposal.preconditions).toEqual(target.snapshot.preconditions);
  expect(proposal.steps.map((s:any)=>s.expected).filter(Boolean)).toEqual(target.snapshot.steps.map((s:any)=>s.expected).filter(Boolean));
  const text=JSON.stringify({preconditions:proposal.preconditions,steps:proposal.steps});expect(text).toMatch(/300|5\s*分钟/);expect(text).not.toMatch(/420|7\s*分钟|PAY-EXPIRED/);
  const actions=proposal.steps.map((s:any)=>s.action).join('\n');expect(actions).not.toMatch(/调用.{0,12}签发接口|重新签发|再次签发|获取验证码/);
  const trigger=proposal.steps.find((s:any)=>s.expected?.includes('E731'));expect(trigger?.action).toMatch(/300|5\s*分钟/);
  expect(JSON.stringify(proposal.source_refs)).toContain('旧版用例.xlsx');expect(JSON.stringify(proposal.source_refs)).toContain('OLD-001');
  expect((await get(`/conversations/${cid}`)).candidates).toEqual(before);
  await page.reload();const review=page.locator('.collection-changes__review');const apply=page.waitForResponse(r=>r.url().endsWith('/apply')&&r.request().method()==='POST');await review.getByRole('button',{name:/一键采纳全部待审阅用例/}).click();expect((await apply).ok()).toBeTruthy();
  state=await get(`/conversations/${cid}`);evidence.after=state.candidates;for(const c of before.filter((c:any)=>c.id!==target.id))expect(state.candidates.find((x:any)=>x.id===c.id)).toEqual(c);
  expect((await get(`/collections/${collection.id}/test-cases`))).toHaveLength(0);await page.reload();await expect(page.getByText('正在恢复工作区',{exact:true})).toBeHidden();
  await page.getByRole('button',{name:'查看更新后的候选',exact:true}).click();
  await expect(page.getByTestId('workspace-case-sources')).toContainText('旧版用例.xlsx');await expect(page.getByTestId('workspace-case-sources')).toContainText('参考改写');await expect(page.getByTestId('workspace-case-sources')).toContainText('OLD-001');await page.screenshot({path:info.outputPath('completed.png'),fullPage:true});
  expect(evidence.errors).toEqual([]);evidence.status='passed';
 }finally{writeFileSync(info.outputPath('evidence.json'),JSON.stringify(evidence,null,2));}
});
