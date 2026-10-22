/* eslint-disable @typescript-eslint/no-explicit-any -- Real acceptance journal. */
import { expect, test } from '@playwright/test';
import { writeFileSync } from 'node:fs';
test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1','Requires isolated real services');
test.use({ video: 'off' });
test.setTimeout(1200000);
const api = `${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
test('ten rounds preserve scope and constraints until reviewed adoption', async ({page},info)=>{
  const evidence: any={turns:[],errors:[]}; page.on('pageerror',e=>evidence.errors.push(e.message));
  const post=async(route:string,data:any)=>{const r=await page.request.post(api+route,{data,timeout:180000});expect(r.ok(),await r.text()).toBeTruthy();return r.json();};
  const get=async(route:string)=>{const r=await page.request.get(api+route);expect(r.ok()).toBeTruthy();return r.json();};
  try {
    await page.addInitScript(()=>localStorage.setItem('casepilot.locale.v1','zh-CN'));
    const user=await post('/auth/register',{email:`tenround-${Date.now()}@casepilot.test`,password:'CasePilot123!',display_name:'十轮修改验收'});
    const collection=(await get(`/spaces/${user.spaces[0].id}/collections`))[0];
    const cases:any[]=[];
    for(const title of ['账号系统登录成功','账号系统退出成功']) cases.push(await post(`/collections/${collection.id}/test-cases`,{title,module:'账号系统',priority:'P1',case_type:'functional',preconditions:['已有启用账号'],steps:[{action:title.includes('登录')?'提交有效凭据':'退出当前会话',expected:title.includes('登录')?'建立会话':'会话失效'}]}));
    const r=await page.request.put(`${api}/collections/${collection.id}/workspace`);expect(r.ok()).toBeTruthy();
    await page.goto(`/workbench/collections/${collection.id}`);
    const chat=async(content:string)=>{
      const input=page.getByRole('textbox',{name:/^(对话消息|用自然语言修改选中用例)$/});await expect(input).toBeEnabled();await input.fill(content);
      const response=page.waitForResponse(r=>/\/(messages|resume)$/.test(r.url())&&r.request().method()==='POST');
      await page.getByRole('button',{name:/^(发送|继续执行修改)$/}).click();const reply=await response;expect(reply.ok(),await reply.text()).toBeTruthy();return reply.json();
    };
    const first=await chat(`只修改用例${cases[0].case_key}，优先级改为P0，其他用例不变。步骤和预期保持不变。`);
    expect(first.intent).toBe('CASE_MODIFY');evidence.turns.push(first);
    const updates=['标题改为“登录验收初稿”','刚才优先级说错了，改为P2','标题改为“登录验收二稿”','优先级改为P0，其他要求保留','标题改为“登录验收三稿”','优先级改为P2，步骤和预期仍不变','标题改为“登录验收四稿”','优先级最终改为P1，其他要求保持','标题最终改为“登录验收定稿”，其他要求不变'];
    for(const content of updates){
      const turn=await chat(content);evidence.turns.push(turn);
      expect(turn.action.job_id).toBeFalsy();
      expect(turn.assistant_message.target_case_ids).toEqual([cases[0].id]);
      expect(await get(`/collections/${collection.id}/test-cases`)).toEqual(cases);
    }
    await page.goto(`/workbench/collections/${collection.id}`);
    await expect(page.getByRole('button',{name:'确认修改并生成建议',exact:true}).last()).toBeVisible({timeout:60000});
    await page.screenshot({path:info.outputPath('ten-round-confirmation.png'),fullPage:true});
    const response=page.waitForResponse(r=>r.url().endsWith('/resume')&&r.request().method()==='POST');
    await page.getByRole('button',{name:'确认修改并生成建议',exact:true}).last().click();
    const confirmed=await(await response).json();expect(confirmed.action.job_id).toBeTruthy();
    let change:any;
    await expect.poll(async()=>{change=await get(`/case-change-sets/${confirmed.action.change_set_id}`);if(change.status==='failed')throw Error(JSON.stringify(change));return change.status;},{timeout:300000}).toBe('ready');
    expect(await get(`/collections/${collection.id}/test-cases`)).toEqual(cases);
    await page.reload();
    const apply=page.locator('.collection-changes__review').getByRole('button',{name:/一键采纳全部待审阅用例/});
    await expect(apply).toBeVisible({timeout:60000});const applied=page.waitForResponse(r=>r.url().endsWith('/apply')&&r.request().method()==='POST');await apply.click();expect((await applied).ok()).toBeTruthy();
    const after=await get(`/collections/${collection.id}/test-cases`);const target=after.find((c:any)=>c.id===cases[0].id);
    expect(target.title).toBe('登录验收定稿');expect(target.priority).toBe('P1');expect(target.steps).toEqual(cases[0].steps);expect(target.preconditions).toEqual(cases[0].preconditions);expect(after.find((c:any)=>c.id===cases[1].id)).toEqual(cases[1]);
    evidence.after=after;evidence.change=change;expect(evidence.errors).toEqual([]);evidence.status='passed';
    await page.screenshot({path:info.outputPath('ten-round-result.png'),fullPage:true});
  } finally {writeFileSync(info.outputPath('evidence.json'),JSON.stringify(evidence,null,2));}
});
