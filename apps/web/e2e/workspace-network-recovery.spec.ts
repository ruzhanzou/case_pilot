import {expect,test} from '@playwright/test';
import {readFileSync,writeFileSync} from 'node:fs';
test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE!=='1','Requires isolated fixture');
test.use({video:'off'});
test('offline refresh restores saved draft, case sources and formal revisions',async({page},info)=>{
 const fixture=JSON.parse(readFileSync('output/journey-acceptance-20261021/perf-fixture.json','utf8'));
 const api=`${process.env.CASEPILOT_E2E_API_URL}/api/v1`;const collection=fixture.collections[0];
 const login=await page.request.post(`${api}/auth/login`,{data:{email:fixture.users[0].email,password:'CasePilot123!'}});expect(login.ok()).toBeTruthy();
 const before=await (await page.request.get(`${api}/collections/${collection.id}/test-cases`)).json();
 await page.addInitScript(()=>localStorage.setItem('casepilot.locale.v1','zh-CN'));
 await page.goto(`/workbench/collections/${collection.id}`);const input=page.getByRole('textbox',{name:'对话消息',exact:true});await expect(input).toBeEnabled();
 const text=`断网前保存的要求：保留原有预期，仅补充操作说明（验收${Date.now()}）`;
 const saved=page.waitForResponse(r=>r.request().method()==='PATCH'&&r.url().includes('/workspaces/')&&r.request().postDataJSON()?.draft_text===text);
 await input.fill(text);expect((await saved).ok()).toBeTruthy();
 await page.context().setOffline(true);let offlineError=false;
 try{await page.reload({waitUntil:'domcontentloaded',timeout:10000});}catch{offlineError=true;}
 await page.context().setOffline(false);await page.goto(`/workbench/collections/${collection.id}`);
 await expect(input).toHaveValue(text);await expect(page.getByTestId('workspace-case-sources')).toBeVisible();
 const after=await (await page.request.get(`${api}/collections/${collection.id}/test-cases`)).json();expect(after).toEqual(before);
 await page.screenshot({path:info.outputPath('restored.png'),fullPage:true});
 writeFileSync(info.outputPath('evidence.json'),JSON.stringify({offlineError,caseCount:after.length,draftRestored:true,revisionsUnchanged:true},null,2));
});
