/* eslint-disable @typescript-eslint/no-explicit-any -- Isolated QA response snapshots. */
import {expect,test} from '@playwright/test';
import {writeFileSync} from 'node:fs';
test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1','Requires isolated services');
test.use({video:'off'});
const api = `${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
test('paged search preserves selections across queries, saving and reopening',async({page},info)=>{
 const evidence:any={requests:[],errors:[]};
 page.on('pageerror',error=>evidence.errors.push(error.message));
 page.on('request',request=>{if(/\/spaces\/[^/]+\/test-cases/.test(request.url()))evidence.requests.push(request.url());});
 const post=async(route:string,data:any)=>{const r=await page.request.post(api+route,{data});expect(r.ok(),await r.text()).toBeTruthy();return r.json();};
 try{
  await page.addInitScript(()=>localStorage.setItem('casepilot.locale.v1','zh-CN'));
  const user=await post('/auth/register',{email:`paging-${Date.now()}@casepilot.test`,password:'CasePilot123!',display_name:'分页验收'});
  const collection=await post(`/spaces/${user.spaces[0].id}/collections`,{name:'分页候选集合'});
  const cases=await post(`/collections/${collection.id}/test-cases/batch`,{cases:Array.from({length:110},(_,i)=>({title:`分页验收${String(i).padStart(3,'0')}`,module:'分页',priority:'P1',case_type:'功能',preconditions:[],steps:[{action:'打开',expected:'就绪'}]}))});
  await page.goto('/executions');
  await page.getByRole('button',{name:'新建 Playlist 执行任务',exact:true}).click();
  await page.getByRole('button',{name:'新建 Playlist',exact:true}).click();
  const tree=page.locator('.playlist-case-tree');
  await expect(tree.getByRole('checkbox')).toHaveCount(100);
  await tree.getByRole('checkbox').first().check();
  await page.getByRole('button',{name:'加载更多用例',exact:true}).click();
  await expect(tree.getByRole('checkbox')).toHaveCount(110);
  await tree.getByRole('checkbox').last().check();
  const search=page.getByRole('textbox',{name:'搜索用例',exact:true});
  await search.fill('不存在的付款');
  await expect(tree.getByText('没有匹配的用例',{exact:true})).toBeVisible();
  await expect(page.locator('.playlist-selected-tree').getByRole('checkbox')).toHaveCount(2);
  await expect(page.getByText('不可用用例',{exact:true})).toBeHidden();
  let failOnce=true;
  await page.route('**/spaces/*/test-cases?**',async(route)=>{
   if(new URL(route.request().url()).searchParams.get('q')==='分页验收000' && failOnce){
    failOnce=false;await route.fulfill({status:503,json:{detail:'暂时无法搜索'}});return;
   }
   await route.continue();
  });
  await search.fill('分页验收000');
  await expect(tree.getByRole('alert')).toBeVisible();
  await page.getByRole('button',{name:'重试搜索',exact:true}).click();
  await expect(tree.getByRole('checkbox')).toHaveCount(1);
  await expect(tree.getByRole('alert')).toHaveCount(0);
  await expect(page.locator('.playlist-selected-tree').getByRole('checkbox')).toHaveCount(2);
  await search.fill('分页验收109');
  await expect(tree.getByRole('checkbox')).toHaveCount(1);
  await expect(tree.getByRole('checkbox')).toBeChecked();
  for(const width of [1440,1280,1024]){
   await page.setViewportSize({width,height:900});
   await expect(search).toBeVisible();
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
   await page.screenshot({path:info.outputPath(`selected-${width}.png`),fullPage:true});
  }
  await page.getByRole('textbox',{name:'Playlist 名称 *',exact:true}).fill('分页选择验收');
  await page.getByRole('button',{name:'保存 Playlist',exact:true}).click();
  await expect(page.getByRole('button',{name:'编辑 分页选择验收',exact:true})).toBeVisible();
  const saved=await(await page.request.get(`${api}/spaces/${user.spaces[0].id}/playlists`)).json();
  expect(saved[0].cases.map((c:any)=>c.case_id).sort()).toEqual([cases[0].id,cases[109].id].sort());
  await page.reload();
  await page.getByRole('button',{name:'新建 Playlist 执行任务',exact:true}).click();
  await page.getByRole('button',{name:'编辑 分页选择验收',exact:true}).click();
  await expect(page.locator('.playlist-selected-tree').getByRole('checkbox')).toHaveCount(2);
  await expect(page.getByText('不可用用例',{exact:true})).toBeHidden();
  await expect(tree.getByRole('checkbox')).toHaveCount(100);
  await tree.getByRole('button',{name:'完整加入',exact:true}).click();
  await expect(page.locator('.playlist-selected-tree').getByRole('checkbox')).toHaveCount(110);
  await search.fill('分页');
  await expect(tree.getByRole('checkbox')).toHaveCount(100);
  await page.getByRole('button',{name:'加载更多用例',exact:true}).click();
  await expect(tree.getByRole('checkbox')).toHaveCount(110);
  await page.locator('.playlist-editor').getByRole('button',{name:'取消',exact:true}).click();
  await page.getByRole('button',{name:'新建 Playlist',exact:true}).click();
  await expect(tree.getByRole('checkbox')).toHaveCount(100);
  await expect(page.locator('.playlist-selected-tree').getByRole('checkbox')).toHaveCount(0);
  expect(evidence.requests.every((url:string)=>new URL(url).searchParams.get('limit')==='100')).toBeTruthy();
  expect(evidence.errors).toEqual([]);evidence.passed=true;
 }finally{writeFileSync(info.outputPath('evidence.json'),JSON.stringify(evidence,null,2));}
});
