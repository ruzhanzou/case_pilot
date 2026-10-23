import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
test.skip(!process.env.CASEPILOT_QA_SAVED_CRUD,'Requires saved synthetic CRUD journey');
test('completed generation remains reviewable after frontend service restart',async({page},info)=>{
 const evidence=JSON.parse(readFileSync(resolve(process.cwd(),process.env.CASEPILOT_QA_SAVED_CRUD!), 'utf8'));
 const api=`${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
 const login=await page.request.post(`${api}/auth/login`,{data:{email:'demo@casepilot.local',password:'CasePilot123!'}});expect(login.ok()).toBeTruthy();
 const response=await page.request.get(`${api}/conversations/${evidence.records[0].binding.conversation_id}`);expect(response.ok()).toBeTruthy();const state=await response.json();
 expect(state.candidates).toHaveLength(2);
 await page.addInitScript(()=>localStorage.setItem('casepilot.locale.v1','zh-CN'));
 await page.goto(`/workbench/collections/${state.collection_id}`);
 await expect(page.getByRole('button',{name:'纳入正式集合（2）',exact:true})).toBeVisible();
 await page.screenshot({path:info.outputPath('preserved-candidates.png'),fullPage:true});
});
