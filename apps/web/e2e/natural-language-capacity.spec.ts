/* eslint-disable @typescript-eslint/no-explicit-any -- Browser timing observations are retained as acceptance evidence. */
import { expect, test } from '@playwright/test';
import { readFileSync, writeFileSync } from 'node:fs';

test.skip(process.env.CASEPILOT_CAPACITY_ACCEPTANCE !== '1', 'Opt in to a 1000-case isolated fixture');
test.use({ viewport: { width: 1280, height: 720 }, trace: 'on' });
test('NL-PER-04 exploratory thousand-case list, map and small-window interaction', async ({ page }, info) => {
  test.setTimeout(300000);
  const api = `${process.env.CASEPILOT_E2E_API_URL ?? "http://localhost:8000"}/api/v1`;
  const evidence: any = { size: 1000, timing_scope: 'single functional observation, shared services; no p95 or SLA conclusion', timings: [], errors: [] };
  const save = () => writeFileSync(info.outputPath('evidence.json'), JSON.stringify(evidence, null, 2));
  page.on('pageerror', error => evidence.errors.push(error.message));
  await page.addInitScript(() => {
    localStorage.setItem('casepilot.locale.v1', 'zh-CN');
    (window as any).__qaLongTasks = [];
    new PerformanceObserver(list => (window as any).__qaLongTasks.push(...list.getEntries().map(e => ({ start: e.startTime, duration: e.duration })))).observe({ entryTypes: ['longtask'] });
  });
  const post = async (path: string, data: unknown) => {
    const r = await page.request.post(api + path, { data, timeout: 180000 }); expect(r.ok(), await r.text()).toBeTruthy(); return r.json();
  };
  const login = await post('/auth/login', { email: 'demo@casepilot.local', password: 'CasePilot123!' });
  const stamp = Date.now();
  evidence.collection = process.env.CASEPILOT_CAPACITY_SEED
    ? JSON.parse(readFileSync(process.env.CASEPILOT_CAPACITY_SEED, 'utf8')).collection
    : await post(`/spaces/${login.spaces[0].id}/collections`, { name: `千条界面探测-${stamp}` }); save();
  const fixtures = Array.from({ length: 1000 }, (_, i) => ({
    case_key: `CAP-${stamp}-${i + 1}`, title: `账号${i + 1}登录校验`, module: `M${String(Math.floor(i / 20) + 1).padStart(2, '0')}`,
    priority: 'P1', case_type: '功能', preconditions: [`账号${i + 1}已启用`], steps: [{ action: `账号${i + 1}提交正确密码`, expected: '建立登录会话' }],
  }));
  const seeded = Date.now();
  // Moderate batches keep fixture preparation separate from the observation itself.
  if (!process.env.CASEPILOT_CAPACITY_SEED) {
    for (let i = 0; i < fixtures.length; i += 100) expect(await post(`/collections/${evidence.collection.id}/test-cases/batch`, { cases: fixtures.slice(i, i + 100) })).toHaveLength(100);
  }
  evidence.fixture_ms = Date.now() - seeded; save();
  try {
    let started = Date.now();
    await page.goto(`/workbench/collections/${evidence.collection.id}`);
    await expect(page.locator('.principle-composer textarea')).toBeEnabled({ timeout: 90000 });
    await expect(page.getByText('1000 条用例 · 50 个模块', { exact: true })).toBeVisible();
    evidence.timings.push({ action: 'initial_workspace_ready', ms: Date.now() - started });
    started = Date.now();
    await page.getByRole('button', { name: '用例列表', exact: true }).click();
    await expect(page.locator('.principle-case-row')).toHaveCount(1000);
    evidence.timings.push({ action: 'list_1000_rows', ms: Date.now() - started });
    started = Date.now();
    await page.locator('.principle-case-row').last().scrollIntoViewIfNeeded();
    await expect(page.locator('.principle-case-row').last()).toContainText('账号1000登录校验');
    evidence.timings.push({ action: 'reach_last_row', ms: Date.now() - started });
    await page.screenshot({ path: info.outputPath('thousand-list.png'), fullPage: false });
    started = Date.now();
    await page.getByRole('button', { name: '用例脑图', exact: true }).click();
    const search = page.getByRole('textbox', { name: '搜索用例资产', exact: true });
    await expect(search).toBeVisible();
    evidence.timings.push({ action: 'map_search_available', ms: Date.now() - started });
    started = Date.now(); await search.fill('账号1000登录校验');
    await expect(search).toHaveValue('账号1000登录校验');
    evidence.timings.push({ action: 'search_input_feedback_only', ms: Date.now() - started });
    await page.screenshot({ path: info.outputPath('thousand-map-small-window.png'), fullPage: false });
    evidence.long_tasks = await page.evaluate(() => (window as any).__qaLongTasks);
    evidence.document_width = await page.evaluate(() => ({ viewport: innerWidth, scrollWidth: document.documentElement.scrollWidth }));
    const response = await page.request.get(`${api}/collections/${evidence.collection.id}/test-cases`); expect(response.ok()).toBeTruthy();
    const final = await response.json(); expect(final).toHaveLength(1000);
    expect(final.every((c: any) => c.revision_number === 1)).toBeTruthy();
    expect(new Set(final.map((c: any) => c.case_key)).size).toBe(1000);
    expect(evidence.errors).toEqual([]); evidence.status = 'passed';
  } catch (error) { evidence.status = 'failed'; evidence.failure = String(error); throw error; }
  finally { save(); }
});
