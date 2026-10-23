import {test,expect} from '@playwright/test';
import {writeFileSync} from 'node:fs';
test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE!=='1','Requires isolated real services');
test.setTimeout(600000);
test('dedup combines full-content cross-batch groups and model review without changing cases',async({page},info)=>{
 const api=`${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
 const post=async(path:string,data:unknown)=>{const r=await page.request.post(api+path,{data});expect(r.ok(),await r.text()).toBeTruthy();return r.json();};
 const get=async(path:string)=>{const r=await page.request.get(api+path);expect(r.ok(),await r.text()).toBeTruthy();return r.json();};
 await page.addInitScript(()=>localStorage.setItem('casepilot.locale.v1','zh-CN'));
 const user=await post('/auth/register',{email:`dedup-${Date.now()}@casepilot.test`,password:'CasePilot123!',display_name:'跨批查重验收'});
 const collection=await post(`/spaces/${user.spaces[0].id}/collections`,{name:'跨批次完整原文查重'});
 const duplicated:string[]=[];
 let semanticId='';
 for(let i=0;i<45;i++){
   const body={title:i<24?'启用账号正确密码登录':`独立操作场景${i}`,module:i<24?'账号/登录':`独立模块${i}`,priority:'P1',case_type:'功能',preconditions:['账号启用'],steps:[{action:i<24?'输入正确账号和密码并提交':`执行独立操作${i}`,expected:i<24?'进入首页':`显示独立结果${i}`}]};
   if(i===24&&process.env.CASEPILOT_QA_DEDUP_ALIAS==='1'){
     body.title='有效用户凭匹配口令进入主页';body.module='账号/登录';
     body.preconditions=['账号已启用'];body.steps=[{action:'填写有效用户名及正确口令并提交认证',expected:'身份认证通过并展示应用主页'}];
   }
   const item=await post(`/collections/${collection.id}/test-cases`,body);if(i<24)duplicated.push(item.id);
   if(i===24&&process.env.CASEPILOT_QA_DEDUP_ALIAS==='1')semanticId=item.id;
 }
 const before=await get(`/collections/${collection.id}/test-cases`);
 const workspace=await page.request.put(`${api}/collections/${collection.id}/workspace`);expect(workspace.ok()).toBeTruthy();const cid=(await workspace.json()).id;
 await page.goto(`/workbench/collections/${collection.id}`);
 const composer=page.locator('.principle-composer textarea');await composer.fill('检查当前集合所有45条用例的重复关系，只检查，不修改或删除任何用例。');
 const wait=page.waitForResponse(r=>r.url().endsWith('/messages')&&r.request().method()==='POST',{timeout:180000});
 await page.locator('.principle-composer button[type=submit]').click();const r=await wait;expect(r.ok(),await r.text()).toBeTruthy();const turn=await r.json();
 expect(turn.intent).toBe('CASE_DEDUP');
 let state=await get(`/conversations/${cid}`);
 await expect.poll(async()=>{state=await get(`/conversations/${cid}`);const run=state.workflow_runs.find((item:{job_id:string})=>item.job_id===turn.action.job_id);if(run?.status==='failed')throw Error(JSON.stringify(run));return run?.status;},{timeout:480000}).toBe('completed');
 const message=state.messages.findLast((m:{metadata:{analysis_report?:unknown}})=>m.metadata.analysis_report);
 const report=message.metadata.analysis_report;
 const exact=report.findings.find((f:{title:string})=>f.title==='用例业务内容完全相同');expect(exact).toBeTruthy();
 expect(new Set(exact.case_refs)).toEqual(new Set(duplicated));
 if(semanticId)expect(report.findings.some((f:{relationship:string;case_refs:string[]})=>f.relationship==='duplicate'&&f.case_refs.includes(semanticId)&&duplicated.every(id=>f.case_refs.includes(id)))).toBe(true);
 expect(report.limitations.join(' ')).toContain('990/990');
 expect(await get(`/collections/${collection.id}/test-cases`)).toEqual(before);
 await page.reload();await expect(page.locator('.principle-composer textarea')).toBeEnabled();
 expect(await get(`/collections/${collection.id}/test-cases`)).toEqual(before);
 writeFileSync(info.outputPath('evidence.json'),JSON.stringify({turn,report,duplicated,semanticId},null,2));
 await page.screenshot({path:info.outputPath('cross-batch-review.png'),fullPage:true});
});
