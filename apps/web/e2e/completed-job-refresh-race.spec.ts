import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
test.skip(!process.env.CASEPILOT_QA_REFRESH_FIXTURE,'Requires a completed synthetic change fixture');
test('refresh reconciles terminal job with a stale running operation',async({page},info)=>{
 const fixture=JSON.parse(readFileSync(resolve(process.env.CASEPILOT_QA_REFRESH_FIXTURE!),'utf8'));
 expect(fixture.email).toMatch(/^parallel-\d+-\d+@casepilot\.test$/);
 const api=`${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
 const login=await page.request.post(`${api}/auth/login`,{data:{email:fixture.email,password:'CasePilot123!'}});expect(login.ok()).toBeTruthy();
 const last=fixture.rounds.findLast((round:{turn?:unknown})=>round.turn);
 let injected=false;
 await page.route(`${api}/collections/${fixture.collection.id}/workspace`,async route=>{
  const response=await route.fetch();const body=await response.json();
  if(!injected){
   const job=body.workflow_runs.find((r:{job_id:string})=>r.job_id===last.turn.action.job_id);expect(job.status).toBe('completed');
   for(const op of [...body.operation_history,...(body.operation_plan?.operations??[])])if(op.related_job_id===job.job_id)op.status='running';
   body.context.active_job_id=job.job_id;injected=true;
  }
  await route.fulfill({response,json:body});
 });
 await page.addInitScript(()=>localStorage.setItem('casepilot.locale.v1','zh-CN'));
 await page.goto(`/workbench/collections/${fixture.collection.id}`);
 const accept=page.locator('.collection-changes__review').getByRole('button',{name:/一键采纳全部待审阅用例/});
 await expect(accept).toBeVisible();await expect(accept).toBeEnabled();
 await expect(page.locator('.case-conversation-running')).toHaveCount(0);
 expect(injected).toBeTruthy();
 await page.screenshot({path:info.outputPath('review-unblocked.png'),fullPage:true});
});
