/* eslint-disable @typescript-eslint/no-explicit-any -- QA snapshots from isolated services. */
import {expect,test} from '@playwright/test';
import {writeFileSync} from 'node:fs';
test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE!=='1','Requires isolated services');
test.use({video:'off'});
const api=`${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
test('keyword fragments, combined terms, empty results and space isolation',async({page,browser},info)=>{
 const evidence:any={queries:[],errors:[]};page.on('pageerror',e=>evidence.errors.push(e.message));
 const post=async(route:string,data:any)=>{const r=await page.request.post(api+route,{data});expect(r.ok(),await r.text()).toBeTruthy();return r.json();};
 try{
  await page.addInitScript(()=>localStorage.setItem('casepilot.locale.v1','zh-CN'));
  const user=await post('/auth/register',{email:`fuzzy-qa-${Date.now()}@casepilot.test`,password:'CasePilot123!',display_name:'模糊搜索验收'});
  const space=user.spaces[0].id;
  const collection=await post(`/spaces/${space}/collections`,{name:'模糊搜索验证'});
  const cases:any[]=[];
  for(const title of ['账号系统登录成功','账号系统退出成功','订单系统创建成功'])cases.push(await post(`/collections/${collection.id}/test-cases`,{title,module:title.startsWith('订单')?'订单系统':'账号系统',priority:'P1',case_type:'functional',preconditions:['已准备测试数据'],steps:[{action:'执行操作',expected:'操作成功'}]}));
  for(const [q,ids] of [['登录',[cases[0].id]],['账号 成功',[cases[0].id,cases[1].id]],[cases[0].case_key.slice(-6),[cases[0].id]],['不存在的支付退款',[]],['%',[]]] as [string,string[]][]){
   const start=performance.now();const response=await page.request.get(`${api}/spaces/${space}/test-cases`,{params:{q}});expect(response.ok()).toBeTruthy();const found=await response.json();
   expect(found.map((c:any)=>c.id).sort()).toEqual(ids.sort());evidence.queries.push({q,ms:performance.now()-start,count:found.length});
  }
  await page.goto(`/cases/${collection.id}`);
  await page.getByRole('button',{name:'用例列表',exact:true}).click();
  const search=page.getByRole('textbox',{name:'搜索用例资产',exact:true});await expect(search).toBeVisible();
  await search.fill('登录');await expect(page.getByText('账号系统登录成功',{exact:true}).first()).toBeVisible();await expect(page.getByText('账号系统退出成功',{exact:true})).toHaveCount(0);
  await search.fill('不存在的支付退款');await expect(page.getByText('账号系统登录成功',{exact:true})).toHaveCount(0);
  await search.fill('账号 成功');await expect(page.getByText('账号系统退出成功',{exact:true}).first()).toBeVisible();
  await page.screenshot({path:info.outputPath('fuzzy-search.png'),fullPage:true});
  const other=await browser.newContext();try{
   const r=await other.request.post(`${api}/auth/register`,{data:{email:`fuzzy-other-${Date.now()}@casepilot.test`,password:'CasePilot123!',display_name:'隔离账号'}});expect(r.ok()).toBeTruthy();
   const denied=await other.request.get(`${api}/spaces/${space}/test-cases`,{params:{q:'账号'}});expect([403,404]).toContain(denied.status());evidence.isolationStatus=denied.status();
  }finally{await other.close();}
  expect(evidence.errors).toEqual([]);evidence.passed=true;
 }finally{writeFileSync(info.outputPath('evidence.json'),JSON.stringify(evidence,null,2));}
});
