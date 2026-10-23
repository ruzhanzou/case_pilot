import {test,expect} from '@playwright/test';
import {resolve} from 'node:path';
import {writeFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE!=='1','Requires isolated services and PDF fixtures');
test.setTimeout(360000);
test('PDF rules ground a rewrite and unusable PDFs report actionable failure',async({page},info)=>{
 const fixtures=info.outputPath('fixtures');
 const primary=process.env.CASEPILOT_QA_PRIMARY_SCAN==='1'?'scan-only.pdf':'requirements.pdf';
 const secondary=primary==='scan-only.pdf'?'requirements.pdf':'scan-only.pdf';
 execFileSync(resolve(process.cwd(),'../../.venv/bin/python'),[resolve(process.cwd(),'../../scripts/qa/pdf_acceptance_fixtures.py'),fixtures,...(process.env.CASEPILOT_QA_CHINESE_MIXED==='1'?['--chinese-mixed']:[])]);
 const api=`${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
 const post=async(path:string,data:unknown)=>{const r=await page.request.post(api+path,{data});expect(r.ok(),await r.text()).toBeTruthy();return r.json();};
 const get=async(path:string)=>{const r=await page.request.get(api+path);expect(r.ok()).toBeTruthy();return r.json();};
 const user=await post('/auth/register',{email:`pdf-${Date.now()}@casepilot.test`,password:'CasePilot123!',display_name:'PDF依据验收'});
 const collection=await post(`/spaces/${user.spaces[0].id}/collections`,{name:'PDF业务依据验收'});
 const item=await post(`/collections/${collection.id}/test-cases`,{title:'验证码过期登录',module:'账号',priority:'P1',preconditions:['已签发验证码'],steps:[{action:'签发后420秒提交验证码',expected:'返回OLD'}]});
 const workspace=await page.request.put(`${api}/collections/${collection.id}/workspace`);const cid=(await workspace.json()).id;
 await page.addInitScript(()=>localStorage.setItem('casepilot.locale.v1','zh-CN'));await page.goto(`/workbench/collections/${collection.id}`);
 const file=page.locator('.principle-composer input[type=file]');await expect(file).toBeEnabled();
 await file.setInputFiles(resolve(fixtures,primary));
 await expect(page.locator('.principle-attachment[data-status=ready]')).toContainText(primary,{timeout:90000});
 await page.locator('.principle-composer textarea').fill(`依据PDF中的现行规则修改用例 ${item.case_key} 的步骤和预期，将等待时长设为PDF规定的过期边界值，使用其中规定的错误码。标题、优先级、前置条件保持不变。`);
 const pending=page.waitForResponse(r=>r.url().endsWith('/messages')&&r.request().method()==='POST',{timeout:180000});await page.locator('.principle-composer button[type=submit]').click();expect((await pending).ok()).toBeTruthy();
 const confirm=page.waitForResponse(r=>r.url().endsWith('/resume')&&r.request().method()==='POST',{timeout:180000});await page.getByRole('button',{name:'确认修改并生成建议',exact:true}).last().click();const turn=await(await confirm).json();
 await expect(page.locator('.collection-changes__review').getByRole('button',{name:/一键采纳全部待审阅用例/})).toBeEnabled({timeout:180000});
 const change=await get(`/case-change-sets/${turn.action.change_set_id}`);const proposed=change.items[0].proposed_snapshot;
 expect(JSON.stringify(proposed.steps)).toContain('300');expect(JSON.stringify(proposed.steps)).toContain('E731');expect(proposed.title).toBe(item.title);expect(proposed.priority).toBe(item.priority);expect(proposed.preconditions).toEqual(item.preconditions);
 if(process.env.CASEPILOT_QA_CHINESE_MIXED==='1') {
  expect(JSON.stringify(proposed.steps)).not.toContain('OLD');
  expect(proposed.source_refs.some((ref:{label:string;locator:string})=>ref.label===primary&&ref.locator==='第 2 页')).toBe(true);
 }
 expect(await get(`/collections/${collection.id}/test-cases`)).toEqual([item]);
 await expect(file).toBeEnabled();await file.setInputFiles(resolve(fixtures,secondary));
 if(process.env.CASEPILOT_QA_OCR_UNAVAILABLE==='1') {
 await expect(page.locator('.principle-attachment[data-status=failed]').first()).toBeVisible({timeout:90000});
 await expect(file).toBeEnabled();await page.reload();
 await expect(page.locator('.principle-attachment[data-status=failed]')).toContainText('扫描件文字识别服务暂不可用');
 } else {
 await expect(page.locator('.principle-attachment[data-status=ready]').filter({hasText:secondary})).toBeVisible({timeout:90000});
 }
 await expect(file).toBeEnabled();await file.setInputFiles(resolve(fixtures,'empty.pdf'));
 const empty=page.locator('.principle-attachment[data-status=failed]').filter({hasText:'empty.pdf'});
 await expect(file).toBeEnabled({timeout:90000});await expect(empty).toHaveCount(1);
 await expect(empty).toContainText('无法提取文字',{timeout:90000});
 await page.reload();await expect(empty).toContainText('无法提取文字');
 const state=await get(`/conversations/${cid}`);expect(await get(`/collections/${collection.id}/test-cases`)).toEqual([item]);
 writeFileSync(info.outputPath('evidence.json'),JSON.stringify({turn,change,state},null,2));await page.screenshot({path:info.outputPath('pdf-feedback.png'),fullPage:true});
});
