import {test,expect} from '@playwright/test';
import {writeFileSync} from 'node:fs';
test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE!=='1','Requires isolated real-model services');
test.setTimeout(300000);
test('failed upload siblings retain individual errors while a valid file remains usable',async({page},info)=>{
 const api=`${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
 const post=async(path:string,data:unknown)=>{const r=await page.request.post(api+path,{data});expect(r.ok(),await r.text()).toBeTruthy();return r.json();};
 const get=async(path:string)=>{const r=await page.request.get(api+path);expect(r.ok()).toBeTruthy();return r.json();};
 const user=await post('/auth/register',{email:`batch-${Date.now()}@casepilot.test`,password:'CasePilot123!',display_name:'多附件验收'});
 const collection=await post(`/spaces/${user.spaces[0].id}/collections`,{name:'多附件部分失败恢复'});
 const item=await post(`/collections/${collection.id}/test-cases`,{title:'验证码过期',module:'登录',priority:'P1',preconditions:['已签发验证码'],steps:[{action:'提交过期验证码',expected:'返回OLD'}]});
 await page.addInitScript(()=>localStorage.setItem('casepilot.locale.v1','zh-CN'));await page.goto(`/workbench/collections/${collection.id}`);
 const file=page.locator('.principle-composer input[type=file]');await expect(file).toBeEnabled();
 await file.setInputFiles([
  {name:'empty.txt',mimeType:'text/plain',buffer:Buffer.from('   \n')},
  {name:'rules.txt',mimeType:'text/plain',buffer:Buffer.from('当前规则：过期验证码登录必须失败，错误码为E731。')},
  {name:'broken.xlsx',mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer:Buffer.concat([Buffer.from([0x50,0x4b,0x03,0x04]),Buffer.from('truncated workbook')])},
 ]);
 const cards=page.locator('.principle-attachment');
 await expect(cards.filter({hasText:'rules.txt'})).toHaveAttribute('data-status','ready',{timeout:90000});
 await expect(cards.filter({hasText:'empty.txt'})).toHaveAttribute('data-status','failed',{timeout:90000});
 await expect(file).toBeEnabled();await expect(cards).toHaveCount(3);
 await expect(cards.filter({hasText:'empty.txt'})).toContainText('无法提取文字');
 await expect(cards.filter({hasText:'broken.xlsx'})).toContainText('文件损坏或格式不符');
 const failedBatch=await get(`/collections/${collection.id}/workspace`);
 await page.screenshot({path:info.outputPath('partial-upload.png'),fullPage:true});
 await page.reload();await expect(cards.filter({hasText:'rules.txt'})).toHaveAttribute('data-status','ready');
 await page.getByRole('button',{name:'移除 empty.txt',exact:true}).click();
 await page.getByRole('button',{name:'移除 broken.xlsx',exact:true}).click();
 await expect(cards).toHaveCount(1);
 const workspace=await get(`/collections/${collection.id}/workspace`);
 expect(workspace.context.pending_attachments).toHaveLength(1);
 await page.locator('.principle-composer textarea').fill(`依据保留附件的现行规则，只修改用例 ${item.case_key} 的预期结果，其他字段保持不变。`);
 const pending=page.waitForResponse(r=>r.url().endsWith('/messages')&&r.request().method()==='POST',{timeout:180000});await page.locator('.principle-composer button[type=submit]').click();expect((await pending).ok()).toBeTruthy();
 const resumed=page.waitForResponse(r=>r.url().endsWith('/resume')&&r.request().method()==='POST',{timeout:180000});await page.getByRole('button',{name:'确认修改并生成建议',exact:true}).last().click();const turn=await(await resumed).json();
 await expect(page.locator('.collection-changes__review').getByRole('button',{name:/一键采纳全部待审阅用例/})).toBeEnabled({timeout:180000});
 const change=await get(`/case-change-sets/${turn.action.change_set_id}`);const proposed=change.items[0].proposed_snapshot;
 expect(JSON.stringify(proposed.steps)).toContain('E731');expect(proposed.title).toBe(item.title);expect(proposed.priority).toBe(item.priority);expect(proposed.preconditions).toEqual(item.preconditions);expect(proposed.steps[0].action).toBe(item.steps[0].action);
 expect(await get(`/collections/${collection.id}/test-cases`)).toEqual([item]);
 writeFileSync(info.outputPath('evidence.json'),JSON.stringify({failedBatch,workspace,turn,change},null,2));await page.screenshot({path:info.outputPath('usable-sibling.png'),fullPage:true});
});
