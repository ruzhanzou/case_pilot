import { test, expect } from '@playwright/test';

test('mixed reuse decisions expose reasons and sources without claiming missing decisions are new', async ({ page }, testInfo) => {
  await page.addInitScript(() => localStorage.setItem('casepilot.locale.v1', 'zh-CN'));
  const collection = { id:'target', space_id:'space', name:'复用建议验收', lifecycle_status:'planning', case_count:0, mind_map_notes:[] };
  const planning = { feature_points:[{id:'f',name:'登录',module:'账号',description:'',requirement_refs:[]}], test_points: ['成功登录','新密码规则','新增设备校验','未完成判断'].map((title,i)=>({id:`p${i}`,title,objective:title,feature_point_ids:['f']})), reuse:{strategy:'regression',decisions:[
    {point_id:'p0',action:'reuse',reason:'步骤与预期完全适用',source:{label:'原登录用例',locator:'TC-1 / V2',collections:[{id:'origin',name:'账号历史集合'}],snapshot:{title:'登录成功',preconditions:[],steps:[]}}},
    {point_id:'p1',action:'modify',reason:'密码长度从8位改为12位'},
    {point_id:'p2',action:'new',reason:'历史资产没有设备校验场景'}]}};
  const workspace = { id:'work', space_id:'space', collection_id:'target', status:'active', context:{phase:'brief_review',active_view:'plan'}, messages:[],candidates:[],workflow_runs:[],operation_history:[],operation_plan:null,test_briefs:[{id:'brief',version:1,status:'draft',content:{test_object:'账号系统',test_objective:'登录',open_questions:[],planning},markdown_content:'# 账号系统',created_at:new Date().toISOString()}] };
  await page.route('**/api/v1/**',async route=>{
    const path=new URL(route.request().url()).pathname;let data:unknown=[];
    if(path.endsWith('/auth/me'))data={id:'account',display_name:'QA',spaces:[{id:'space',name:'Space',role:'owner'}]};
    else if(path.endsWith('/generation-models'))data={models:[],default_model_id:'auto'};
    else if(path.endsWith('/spaces/space/collections'))data=[collection];
    else if(path.endsWith('/collections/target'))data=collection;
    else if(path.includes('/workspaces/')||path.includes('/conversations/')||path.endsWith('/workspace'))data=workspace;
    await route.fulfill({json:data});
  });
  await page.goto('/workbench/collections/target');
  const overview=page.getByRole('region',{name:'复用处理建议'});
  await expect(overview).toBeVisible();
  await expect(overview.locator('article')).toHaveCount(4);
  await overview.getByRole('button',{name:'直接复用 · 1',exact:true}).click();
  await expect(overview.locator('article')).toHaveCount(1);
  await expect(overview).toContainText('账号历史集合 · TC-1 / V2');
  await overview.getByRole('button',{name:'需要改写 · 1',exact:true}).click();
  await expect(overview).toContainText('密码长度从8位改为12位');
  await overview.getByRole('button',{name:'待判断 · 1',exact:true}).click();
  await expect(overview).toContainText('尚未记录处理判断');
  await overview.getByRole('button',{name:'全部 · 4',exact:true}).click();
  for (const width of [1440, 1280, 1024]) {
    await page.setViewportSize({width,height:1000});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await overview.screenshot({path:testInfo.outputPath(`reuse-decisions-${width}.png`)});
  }
  await overview.locator('article').first().getByRole('button',{name:'查看依据与调整'}).click();
  await expect(page.locator('.test-planning-detail')).toContainText('成功登录');
});
