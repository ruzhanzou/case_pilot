import {expect,test} from '@playwright/test';
for(const state of ['empty','scoped','formal','hundred'] as const)test(`asset confirmation ${state} has an explicit next step`,async({page})=>{
 await page.addInitScript(()=>localStorage.setItem('casepilot.locale.v1','zh-CN'));
 const source={key:'asset:1',case_id:'case-1',label:'CASE-001',match_reason:'相同测试对象',collections:[{id:'origin',name:'来源集合'}],snapshot:{title:'登录',module:'账号系统',preconditions:['账号已启用'],steps:[{action:'登录',expected:'成功'}]}};
 const selection={status:'awaiting_confirmation',strategy:'select_and_generate',test_object:'账号系统',sources:state==='empty'?[]:state==='hundred'?Array.from({length:100},(_,i)=>({...source,key:`asset:${i}`,case_id:`case-${i}`,snapshot:{...source.snapshot,title:`登录场景${i}`}})):[source],target_points:state==='scoped'?[{id:'P1',title:'登录成功'},{id:'P2',title:'退出失效'}]:[],followup_intent:state==='formal'?'CASE_MODIFY':null};
 const collection={id:'target',space_id:'space',name:'当前集合',lifecycle_status:'planning',case_count:0,mind_map_notes:[]};
 const workspace={id:'work',space_id:'space',collection_id:'target',status:'active',context:{phase:'brief_review',active_view:'plan'},messages:[],candidates:[],workflow_runs:[],operation_history:[],operation_plan:null,test_briefs:[{id:'brief',version:1,status:'draft',content:{test_object:'账号系统',test_objective:'登录',open_questions:[],planning:{},generation_strategy:'select_and_generate',asset_selection:selection},markdown_content:'# 账号系统',created_at:new Date().toISOString()}]};
 const calls:unknown[]=[];
 await page.route('**/api/v1/**',async route=>{
  const p=new URL(route.request().url()).pathname;let data:unknown=[];
  if(p.endsWith('/auth/me'))data={id:'account',display_name:'QA',spaces:[{id:'space',name:'Space',role:'owner'}]};
  else if(p.endsWith('/generation-models'))data={models:[],default_model_id:'auto'};
  else if(p.endsWith('/spaces/space/collections'))data=[collection];
  else if(p.endsWith('/collections/target'))data=collection;
  else if(p.endsWith('/generation-assets/confirm')){calls.push(route.request().postDataJSON());data={action:{}};}
  else if(p.includes('/workspaces/')||p.includes('/conversations/')||p.endsWith('/workspace'))data=workspace;
  await route.fulfill({json:data});
 });
 await page.goto('/workbench/collections/target');
 const card=page.getByRole('region',{name:'现有用例资产选择'}).first();await expect(card).toBeVisible();
 const button=card.getByRole('button',{name:state==='empty'?'不复用，继续规划':state==='formal'?'确认参考并继续修改':state==='hundred'?'确认复用并开始规划':'确认来源与影响范围',exact:true});
 if(state==='empty')await expect(card).toContainText('未找到可确认测试对象一致的资产');
 if(state==='formal')await expect(card).toContainText('变更建议');
 if(state==='scoped'){
  await card.getByRole('checkbox',{name:'退出失效',exact:true}).uncheck();
  const checkbox=card.getByRole('checkbox',{name:'登录成功',exact:true});
  await checkbox.focus();await page.keyboard.press('Space');await expect(button).toBeDisabled();
  await page.keyboard.press('Space');await expect(button).toBeEnabled();
 }
 if(state==='hundred'){
  const list=card.getByRole('group',{name:'可选资产',exact:true});
  expect(await list.evaluate(el=>el.scrollHeight>el.clientHeight&&el.clientHeight<=360)).toBe(true);
  await list.focus();await page.keyboard.press('End');
  await expect.poll(()=>list.evaluate(el=>el.scrollTop)).toBeGreaterThan(0);
  await expect(card).toContainText('已选：100 / 100');
 }
 await button.focus();await page.keyboard.press('Enter');await expect.poll(()=>calls.length).toBe(1);
 expect(calls[0]).toEqual({version:1,case_ids:state==='empty'?[]:state==='hundred'?Array.from({length:100},(_,i)=>`case-${i}`):['case-1'],test_point_ids:state==='scoped'?['P1']:[]});
});
