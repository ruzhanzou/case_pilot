import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the CasePilot authentication shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>CasePilot — AI 用例工作台<\/title>/i);
  assert.match(html, /class="auth-loading"/);
  assert.match(html, /正在连接本地工作区/);
  assert.match(html, /lang="zh-CN"/);
});

test("keeps the persisted case management and execution baseline", async () => {
  const [
    managementApp,
    caseLibrary,
    caseMindMap,
    caseWorkbench,
    caseEditor,
    executionNotes,
    sampleCases,
    sampleAudioCases,
    executionWorkspace,
    apiClient,
    css,
  ] =
    await Promise.all([
    readFile(new URL("../components/case-management-app.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/case-library.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/case-mind-map.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/case-workbench.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/case-editor-dialog.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/execution-notes.tsx", import.meta.url), "utf8"),
    readFile(new URL("../lib/sample-cases.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/sample-audio-cases.ts", import.meta.url), "utf8"),
    readFile(new URL("../components/execution-workspace.tsx", import.meta.url), "utf8"),
    readFile(new URL("../lib/casepilot-api.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);

  assert.match(managementApp, /账号登录验收用例集/);
  assert.match(managementApp, /<CaseLibrary/);
  assert.match(managementApp, /<CaseWorkbench/);
  assert.match(managementApp, /<ExecutionWorkspace/);
  assert.match(managementApp, /AI 用例工作台/);
  assert.match(caseLibrary, /<CaseMindMap/);
  assert.match(caseLibrary, /onStartExecution/);
  assert.match(caseLibrary, /onOpenWorkbench/);
  assert.match(caseLibrary, /AI 编辑/);
  assert.match(caseLibrary, /case-library__main--list/);
  assert.match(caseLibrary, /case-library__body--list/);
  assert.match(caseLibrary, /CASES_PER_PAGE = 20/);
  assert.match(caseLibrary, /用例列表分页/);
  assert.doesNotMatch(caseLibrary, /<th>用例状态<\/th>/);
  assert.match(caseLibrary, /执行结果请在 QA 执行批次中查看/);
  assert.match(caseMindMap, /在\$\{data.title\}下新增用例/);
  assert.match(caseMindMap, /zoomOnScroll=\{false\}/);
  assert.match(caseMindMap, /panOnScroll/);
  assert.match(caseMindMap, /一键隐藏全部叶子用例/);
  assert.match(caseMindMap, /进入脑图全屏/);
  assert.match(caseMindMap, /requestFullscreen/);
  assert.match(caseMindMap, /toggleModuleLeaves/);
  assert.match(caseMindMap, /position: \{ x: 360, y: moduleCenterRow/);
  assert.match(caseMindMap, /position: \{ x: 1040, y: row/);
  assert.match(caseMindMap, /共同前置/);
  assert.match(caseWorkbench, /把需求变成可评审的测试用例/);
  assert.match(caseWorkbench, /聊天输出默认为候选内容/);
  assert.match(caseWorkbench, /写入用例集/);
  assert.match(caseWorkbench, /用例脑图/);
  assert.match(caseWorkbench, /用例列表/);
  assert.match(caseWorkbench, /selectedModelLabel/);
  assert.match(caseWorkbench, /startGeneration/);
  assert.match(caseWorkbench, /watchGeneration/);
  assert.match(caseWorkbench, /generationStageIndex/);
  assert.doesNotMatch(caseWorkbench, /setInterval/);
  assert.match(caseWorkbench, /onImportCases/);
  assert.match(caseWorkbench, /selectedCandidateIds/);
  assert.match(caseWorkbench, /编辑当前候选用例/);
  assert.match(caseWorkbench, /当前对话或候选用例尚未保存/);
  assert.match(caseWorkbench, /Test Design Pro/);
  assert.match(caseWorkbench, /调整对话区域宽度/);
  assert.match(caseWorkbench, /调整详情区域宽度/);
  assert.match(caseWorkbench, /resizePanel/);
  assert.match(caseWorkbench, /is-preview-resizing/);
  assert.match(caseWorkbench, /const commit/);
  assert.match(caseEditor, /当前用例修改尚未保存/);
  assert.match(caseEditor, /beforeunload/);
  assert.match(sampleCases, /case_key: "AUTH-001"/);
  assert.match(sampleCases, /case_key: "AUTH-012"/);
  assert.match(sampleAudioCases, /case_key: "AUDIO-001"/);
  assert.match(sampleAudioCases, /case_key: "AUDIO-018"/);
  assert.match(managementApp, /Audio Feature 用例集/);
  assert.match(executionWorkspace, /createExecutionRun/);
  assert.match(executionWorkspace, /completed_step_ids/);
  assert.match(executionWorkspace, /任务描述/);
  assert.match(executionWorkspace, /请填写本次执行任务的目标或范围/);
  assert.match(executionWorkspace, /descriptionRef\.current\?\.focus/);
  assert.doesNotMatch(executionWorkspace, /软件版本|构建号|测试环境/);
  assert.match(executionWorkspace, /新建执行任务/);
  assert.match(executionWorkspace, /任务历史/);
  assert.match(executionWorkspace, /参与成员/);
  assert.match(executionWorkspace, /每 5 秒自动同步多人执行进度/);
  assert.match(executionWorkspace, /closeExecutionRun/);
  assert.match(executionWorkspace, /readOnly/);
  assert.match(executionWorkspace, /标记通过前，请先逐项完成所有执行步骤/);
  assert.match(executionWorkspace, /aria-pressed/);
  assert.doesNotMatch(executionWorkspace, /option\.value === "passed"/);
  assert.match(executionNotes, /记录已保存/);
  assert.doesNotMatch(executionWorkspace, /内容状态/);
  assert.match(apiClient, /listSpaceExecutionRuns/);
  assert.match(apiClient, /base_updated_at/);
  assert.match(apiClient, /test-cases\/batch/);
  assert.match(apiClient, /\/execution-records\/\$\{recordId\}/);
  assert.doesNotMatch(apiClient, /CaseStatusApi|status-events/);
  assert.doesNotMatch(apiClient, /startMockGeneration|watchMockGeneration/);
  assert.match(apiClient, /\/api\/v1\/generation-jobs/);
  assert.match(apiClient, /requirement\.analyzed/);
  assert.match(css, /\.management-app/);
  assert.match(css, /\.case-library/);
  assert.match(css, /\.execution-workspace/);
});
