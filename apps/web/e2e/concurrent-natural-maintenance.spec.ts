import {test, expect} from '@playwright/test';
import {writeFileSync} from 'node:fs';

test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1', 'Requires real services and model');
test.describe.configure({mode:'parallel'});
test.setTimeout(900000);
test.use({actionTimeout:60000, navigationTimeout:60000});
for (let actor=1;actor<=5;actor++) {
  test(`independent user ${actor} completes repeated natural edits and replay-safe adoption`, async ({page}, info) => {
    const api=`${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
    const errors:string[]=[];
    page.on('pageerror', error=>errors.push(error.message));
    const post=async(path:string,data:unknown)=>{const r=await page.request.post(api+path,{data});expect(r.ok(),await r.text()).toBeTruthy();return r.json();};
    const get=async(path:string)=>{const r=await page.request.get(api+path);expect(r.ok(),await r.text()).toBeTruthy();return r.json();};
    const email=`parallel-${actor}-${Date.now()}@casepilot.test`;
    const user=await post('/auth/register',{email,password:'CasePilot123!',display_name:`并发验收${actor}`});
    const collection=await post(`/spaces/${user.spaces[0].id}/collections`,{name:`并发连续维护${actor}`});
    const initial=await post(`/collections/${collection.id}/test-cases`,{title:`用户${actor}原始登录`,module:'账号',priority:'P1',preconditions:[`用户${actor}账号有效`],steps:[{action:'提交登录',expected:'进入首页'}]});
    const sentinel=await post(`/collections/${collection.id}/test-cases`,{title:`用户${actor}保留用例`,module:'库存',priority:'P2',steps:[{action:'查询库存',expected:'显示数量'}]});
    const rounds:unknown[]=[];
    const save=()=>writeFileSync(info.outputPath('evidence.json'),JSON.stringify({actor,email,collection,initial,sentinel,rounds,errors},null,2));
    save();
    await page.addInitScript(()=>localStorage.setItem('casepilot.locale.v1','zh-CN'));
    await page.goto(`/workbench/collections/${collection.id}`);
    const expectedTitle=`并发用户${actor}登录成功`;
    const expectedResult=`进入用户${actor}专属主页`;
    const instructions=[`仅将用例 ${initial.case_key} 的标题改为「${expectedTitle}」，其他字段保持不变。`,
      `仅将用例 ${initial.case_key} 的优先级改为P0，保留标题及其他已有内容。`,
      `仅将用例 ${initial.case_key} 第一步的预期结果改为「${expectedResult}」，保留标题、优先级、操作步骤和前置条件。`];
    for(let round=0;round<instructions.length;round++){
      const startedAt=new Date().toISOString();
      const sendButton=page.locator('.principle-composer button[type=submit]');
      await expect(sendButton).toBeVisible({timeout:60000});
      await page.locator('.principle-composer textarea').fill(instructions[round]);
      const response=page.waitForResponse(r=>/\/(messages|resume)$/.test(new URL(r.url()).pathname)&&r.request().method()==='POST',{timeout:180000});
      await sendButton.click();const sent=await response;expect(sent.ok(),await sent.text()).toBeTruthy();let turn=await sent.json();
      expect(turn.intent).toBe('CASE_MODIFY');
      if(turn.assistant_message?.metadata.modification_confirmation){
        const confirmation=page.waitForResponse(r=>r.url().endsWith('/resume')&&r.request().method()==='POST',{timeout:180000});
        await page.getByRole('button',{name:'确认修改并生成建议',exact:true}).last().click();
        const r=await confirmation;expect(r.ok(),await r.text()).toBeTruthy();turn=await r.json();
      }
      expect(turn.action.job_id).toBeTruthy();
      rounds.push({round,startedAt,instruction:instructions[round],turn});save();
      await page.reload();
      await expect.poll(async()=>{
        const job=await get(`/generation-jobs/${turn.action.job_id}`);
        expect(job.status,JSON.stringify(job)).not.toBe('failed');return job.status;
      },{timeout:360000,intervals:[1000,2000]}).toBe('completed');
      const before=await get(`/collections/${collection.id}/test-cases`);
      expect(before.find((c:{id:string})=>c.id===initial.id).revision_number).toBe(initial.revision_number+round);
      const review=page.locator('.collection-changes__review');
      const applyResponse=page.waitForResponse(r=>r.url().endsWith(`/case-change-sets/${turn.action.change_set_id}/apply`)&&r.request().method()==='POST');
      await review.getByRole('button',{name:/一键采纳全部待审阅用例/}).click();
      const applied=await applyResponse;expect(applied.ok(),await applied.text()).toBeTruthy();
      // Simulate a client retry after losing its successful apply response.
      await post(`/case-change-sets/${turn.action.change_set_id}/apply`,applied.request().postDataJSON());
      const after=await get(`/collections/${collection.id}/test-cases`);
      expect(after).toHaveLength(2);
      expect(after.find((c:{id:string})=>c.id===sentinel.id)).toEqual(sentinel);
      const current=after.find((c:{id:string})=>c.id===initial.id);
      expect(current.revision_number).toBe(initial.revision_number+round+1);
      expect(current.title).toBe(expectedTitle);
      expect(current.priority).toBe(round===0?'P1':'P0');
      expect(current.preconditions).toEqual(initial.preconditions);
      expect(current.steps[0].action).toBe(initial.steps[0].action);
      expect(current.steps[0].expected).toBe(round===2?expectedResult:initial.steps[0].expected);
      rounds.push({round,completedAt:new Date().toISOString(),after});save();
      await page.reload();
    }
    await page.getByRole('button',{name:'用例列表',exact:true}).click();
    await expect(page.getByRole('button',{name:`${initial.case_key} ${expectedTitle} 账号 P0`,exact:true})).toBeVisible();
    expect(errors).toEqual([]);save();
    await page.screenshot({path:info.outputPath('final-saved-cases.png'),fullPage:true});
  });
}
