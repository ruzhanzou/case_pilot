import {test,expect} from '@playwright/test';
import {writeFileSync} from 'node:fs';
test.skip(!process.env.CASEPILOT_QA_FAULT_TOKEN,'Requires opt-in isolated fault worker');
test.setTimeout(600000);
test('failed modification resumes through natural retry without applying or duplicating cases',async({page},info)=>{
 const token=process.env.CASEPILOT_QA_FAULT_TOKEN!;expect(token.startsWith('maturity-')).toBeTruthy();
 const api=`${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
 const post=async(path:string,data:unknown)=>{const r=await page.request.post(api+path,{data});expect(r.ok(),await r.text()).toBeTruthy();return r.json();};
 const get=async(path:string)=>{const r=await page.request.get(api+path);expect(r.ok(),await r.text()).toBeTruthy();return r.json();};
 await page.addInitScript(()=>localStorage.setItem('casepilot.locale.v1','zh-CN'));
 const user=await post('/auth/register',{email:`fault-${Date.now()}@casepilot.test`,password:'CasePilot123!',display_name:'工作进程故障验收'});
 const collection=await post(`/spaces/${user.spaces[0].id}/collections`,{name:'工作进程失败恢复'});
 const item=await post(`/collections/${collection.id}/test-cases`,{title:'原始登录',module:'账号',priority:'P1',preconditions:['账号有效'],steps:[{action:'提交登录',expected:'进入首页'}]});
 const workspace=await page.request.put(`${api}/collections/${collection.id}/workspace`);expect(workspace.ok()).toBeTruthy();const cid=(await workspace.json()).id;
 await page.goto(`/workbench/collections/${collection.id}`);
 const send=async(content:string)=>{const composer=page.locator('.principle-composer textarea');await expect(composer).toBeEnabled({timeout:60000});await composer.fill(content);const wait=page.waitForResponse(r=>/\/(messages|resume)$/.test(new URL(r.url()).pathname)&&r.request().method()==='POST',{timeout:180000});await page.locator('.principle-composer button[type=submit]').click();const r=await wait;expect(r.ok(),await r.text()).toBeTruthy();return r.json();};
 const title=`故障恢复验收-${token}`;
 const first=await send(`仅修改用例 ${item.case_key} 的标题为「${title}」，其他字段保持不变。`);
 expect(first.intent).toBe('CASE_MODIFY');
 const pending=page.waitForResponse(r=>r.url().endsWith('/resume')&&r.request().method()==='POST');
 await page.getByRole('button',{name:'确认修改并生成建议',exact:true}).last().click();const launched=await(await pending).json();
 let state=await get(`/conversations/${cid}`);
 await expect.poll(async()=>{state=await get(`/conversations/${cid}`);return state.workflow_runs.find((r:{job_id:string})=>r.job_id===launched.action.job_id)?.status;},{timeout:180000}).toBe('failed');
 if (token.startsWith('maturity-crash-')) {
  const failedJob=await get(`/generation-jobs/${launched.action.job_id}`);
  // The public API intentionally normalizes internal exception class names.
  expect(failedJob.error_code).toBe('generation_failed');
  expect(state.messages.some((m:{status:string;content:string})=>m.status==='failed'&&m.content.includes('执行进程意外中断'))).toBe(true);
 }
 expect(await get(`/collections/${collection.id}/test-cases`)).toEqual([item]);
 const failedState=state;await page.reload();
 const retried=await send('重试修改任务');expect(retried.intent).toBe('CASE_MODIFY');
 expect(retried.action.job_id).toBeTruthy();
 await expect.poll(async()=>{state=await get(`/conversations/${cid}`);const run=state.workflow_runs.find((r:{job_id:string})=>r.job_id===retried.action.job_id);if(run?.status==='failed')throw Error(JSON.stringify(run));return run?.status;},{timeout:360000}).toBe('completed');
 expect(await get(`/collections/${collection.id}/test-cases`)).toEqual([item]);
 const review=page.locator('.collection-changes__review');
 await review.getByRole('button',{name:/一键采纳全部待审阅用例/}).click();
 await expect.poll(async()=> (await get(`/collections/${collection.id}/test-cases`))[0].title).toBe(title);
 await page.reload();const after=await get(`/collections/${collection.id}/test-cases`);expect(after).toHaveLength(1);expect(after[0].revision_number).toBe(item.revision_number+1);
 expect(after[0].steps.map((s:{action:string;expected:string})=>({action:s.action,expected:s.expected}))).toEqual(item.steps.map((s:{action:string;expected:string})=>({action:s.action,expected:s.expected})));
 expect(after[0].preconditions).toEqual(item.preconditions);expect(after[0].priority).toBe(item.priority);
 writeFileSync(info.outputPath('evidence.json'),JSON.stringify({first,launched,failedState,retried,state,after},null,2));
 await page.screenshot({path:info.outputPath('recovered.png'),fullPage:true});
});
