import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
test.skip(!process.env.CASEPILOT_QA_SAVED_EVIDENCE,'Requires synthetic saved acceptance evidence');
test('saved applied case loads visibly after a fresh authenticated browser session',async({page},info)=>{
 const evidence=JSON.parse(readFileSync(resolve(process.cwd(),process.env.CASEPILOT_QA_SAVED_EVIDENCE!), 'utf8'));
 expect(evidence.email).toMatch(/^(?:broker|cancel-refine)-\d+@casepilot\.test$/);
 const login=await page.request.post(`${process.env.CASEPILOT_E2E_API_URL}/api/v1/auth/login`,{data:{email:evidence.email,password:'CasePilot123!'}});expect(login.ok()).toBeTruthy();
 await page.addInitScript(()=>localStorage.setItem('casepilot.locale.v1','zh-CN'));
 await page.goto(`/workbench/collections/${evidence.state.collection_id}`);
 await page.getByRole('button',{name:'用例列表',exact:true}).click();
 await expect(page.getByRole('button',{name:`${evidence.after[0].case_key} ${evidence.after[0].title} ${evidence.after[0].module} ${evidence.after[0].priority}`,exact:true})).toBeVisible();
 await expect(page.getByText('正在准备工作区…',{exact:true})).toHaveCount(0);
 await page.screenshot({path:info.outputPath('saved-applied-case.png'),fullPage:true});
});
