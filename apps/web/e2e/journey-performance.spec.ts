/* eslint-disable @typescript-eslint/no-explicit-any -- Acceptance fixture records real service evidence. */
import { expect, test } from '@playwright/test';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
test.skip(process.env.CASEPILOT_REAL_ACCEPTANCE !== '1', 'Isolated acceptance services required');
test.use({ video: 'off', trace: 'off' });
test.setTimeout(900000);
const api = `${process.env.CASEPILOT_E2E_API_URL}/api/v1`;
const dir = path.resolve(process.env.CASEPILOT_PERF_OUTPUT ?? 'output/journey-acceptance-20261021/performance');
const p95 = (values: number[]) => [...values].sort((a,b) => a-b)[Math.ceil(values.length * .95)-1];
test('1000 assets, 100 case workspace, 10 turns, five users and desktop widths', async ({ browser, page }) => {
  await mkdir(dir, { recursive: true });
  const users: any[] = [], contexts = [];
  const evidence: any = { api: {}, ui: {}, browserErrors: [] };
  page.on('pageerror', error => evidence.browserErrors.push(error.message));
  const post = async (client: any, route: string, data: any) => {
    const r = await client.post(api+route, {data}); expect(r.ok(), await r.text()).toBeTruthy(); return r.json();
  };
  try {
    const fixture = process.env.CASEPILOT_PERF_REUSE ? JSON.parse(await readFile('output/journey-acceptance-20261021/perf-fixture.json','utf8')) : null;
    for (let i=0;i<5;i++) {
      const context = i===0 ? page.context() : await browser.newContext(); contexts.push(context);
      const email = `performance-${Date.now()}-${i}@casepilot.test`;
      const user = fixture ? await post(context.request, "/auth/login", {email:fixture.users[i].email,password:"CasePilot123!"}) : await post(context.request, "/auth/register", {email,password:"CasePilot123!",display_name:`性能验收${i}`});
      users.push({client:context.request, email, ...user});
    }
    const space = fixture?.space ?? users[0].spaces[0].id;
    if (!fixture) for (const user of users.slice(1)) await post(users[0].client, `/spaces/${space}/members`, {email:user.email,role:'member'});
    const collections: any[] = fixture?.collections ?? [];
    if (!fixture) for (let i=0;i<10;i++) collections.push(await post(users[0].client, `/spaces/${space}/collections`, {name:`性能资产${i}`}));
    if (!fixture) for (let i=0;i<100;i++) await Promise.all(collections.map((collection,index) => post(users[0].client, `/collections/${collection.id}/test-cases`, {title:`性能账号系统${index} 登录场景${i} 长标题布局验证`,module:'账号系统',priority:'P1',case_type:'functional',preconditions:['存在可用账号'],steps:[{action:`输入场景${i}对应账号并提交登录`,expected:'登录成功并建立会话'}]})));
    const collection = collections[0];
    const workspaces: any[] = fixture?.workspaces ?? [];
    if (!fixture) for (const user of users) {
      const r = await user.client.put(`${api}/collections/${collection.id}/workspace`); expect(r.ok()).toBeTruthy(); workspaces.push(await r.json());
    }
    if (!fixture) for (let i=0;i<10;i++) await post(users[0].client, `/conversations/${workspaces[0].id}/messages`, {content:'你好'});
    const samples: Record<string,number[]> = {list:[], search:[], history:[]};
    await Promise.all(users.map(async (user,index) => {
      for(let n=0;n<30;n++) for(const [kind,route] of [['list',`/collections/${collection.id}/test-cases`],['search',`/spaces/${space}/test-cases?q=登录`],['history',`/conversations/${workspaces[index].id}`]]) {
        const start=performance.now(); const r=await user.client.get(api+route); await r.body(); expect(r.ok()).toBeTruthy(); samples[kind].push(performance.now()-start);
      }
    }));
    for(const [key,values] of Object.entries(samples)) evidence.api[key]={samples:values,p95:p95(values)};
    await page.addInitScript(()=>localStorage.setItem('casepilot.locale.v1','zh-CN'));
    for (const width of [1440,1280,1024]) {
      await page.setViewportSize({width,height:1000});
      const recovery=[], interaction=[];
      for(let n=0;n<30;n++) {
        const start=performance.now(); await page.goto(`/workbench/collections/${collection.id}`);
        const input=page.getByRole('textbox',{name:'对话消息',exact:true}); await expect(input).toBeEnabled();
        await expect(page.getByText('正在恢复工作区',{exact:true})).toBeHidden();
        recovery.push(performance.now()-start);
        const begin=performance.now(); await input.fill(`补充要求${n}`); interaction.push(performance.now()-begin);
      }
      expect(await page.evaluate(()=>document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await page.screenshot({path:path.join(dir,`workspace-${width}.png`),fullPage:true});
      evidence.ui[width]={recovery,interaction,recoveryP95:p95(recovery),interactionP95:p95(interaction)};
    }
    expect(evidence.browserErrors).toEqual([]);
    const submission: number[] = [];
    for (let n=0;n<30;n++) {
      const input=page.getByRole('textbox',{name:'对话消息',exact:true});
      await expect(input).toBeEnabled(); await input.fill('你好');
      const response=page.waitForResponse(r=>r.url().endsWith('/messages')&&r.request().method()==='POST');
      const start=performance.now();
      await page.getByRole('button',{name:'发送',exact:true}).click();
      await expect(input).toHaveValue('');
      submission.push(performance.now()-start);
      expect((await response).ok()).toBeTruthy();
      await expect(page.getByRole('button',{name:'发送',exact:true})).toBeVisible();
    }
    evidence.submission={samples:submission,p95:p95(submission)};
    expect(evidence.submission.p95).toBeLessThanOrEqual(1000);
    for(const metric of Object.values(evidence.api) as any[]) expect(metric.p95).toBeLessThanOrEqual(2000);
    for(const metric of Object.values(evidence.ui) as any[]) {expect(metric.recoveryP95).toBeLessThanOrEqual(3000);expect(metric.interactionP95).toBeLessThanOrEqual(200);}
    evidence.status='passed';
  } finally {
    await writeFile(path.join(dir,'results.json'),JSON.stringify(evidence,null,2));
    for(const context of contexts.slice(1)) await context.close();
  }
});
