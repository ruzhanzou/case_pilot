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
    newConversation,
    conversationExamples,
    conversationHistory,
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
    readFile(new URL("../components/new-conversation.tsx", import.meta.url), "utf8"),
    readFile(new URL("../content/conversation-examples.ts", import.meta.url), "utf8"),
    readFile(new URL("../components/conversation-history-drawer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../lib/casepilot-api.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);

  assert.doesNotMatch(
    managementApp,
    /默认用例集|sampleLoginCases|sampleAudioCases/,
  );
  assert.match(managementApp, /<CaseLibrary/);
  assert.match(managementApp, /<CaseWorkbench/);
  assert.match(managementApp, /<NewConversation/);
  assert.match(managementApp, /workbenchMode === "create"/);
  assert.match(managementApp, /setWorkbenchMode\("workspace"\)/);
  assert.match(managementApp, /shouldOpenWorkspace\(turn\.intent/);
  assert.match(managementApp, /"CASE_DELETE"/);
  assert.match(managementApp, /"CASE_QUERY"/);
  assert.match(managementApp, /createConversation\(\{/);
  assert.match(managementApp, /spaceId: space\.id/);
  assert.match(newConversation, /确认本对话维护的用例集合/);
  assert.match(newConversation, /confirmConversationOperationCollection/);
  assert.match(caseWorkbench, /本对话仅维护此集合/);
  assert.match(caseWorkbench, /新建对话并打开该集合/);
  assert.match(managementApp, /<ExecutionWorkspace/);
  assert.match(managementApp, /AI 用例工作台/);
  assert.match(caseLibrary, /<CaseMindMap/);
  assert.match(caseLibrary, /onStartExecution/);
  assert.match(caseLibrary, /onOpenWorkbench/);
  assert.match(caseLibrary, /进入\/继续工作区/);
  assert.doesNotMatch(caseLibrary, /AI 编辑/);
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
  assert.match(caseWorkbench, /CasePilot/);
  assert.match(caseWorkbench, /结构化测试说明/);
  assert.match(caseWorkbench, /确认并生成用例/);
  assert.match(caseWorkbench, /正在启动生成/);
  assert.match(caseWorkbench, /confirmPendingIntent/);
  assert.match(caseWorkbench, /conversation-intent-confirmation/);
  assert.match(caseWorkbench, /创建新对话/);
  assert.match(caseWorkbench, /继续修改测试说明、维护当前用例/);
  assert.match(caseWorkbench, /downloadTestBrief/);
  assert.match(caseWorkbench, /chat_width/);
  assert.match(caseWorkbench, /inspector_width/);
  assert.match(caseWorkbench, /useStickToBottom/);
  assert.match(caseWorkbench, /messagesScrollRef/);
  assert.match(caseWorkbench, /setPointerCapture/);
  assert.match(caseWorkbench, /pointercancel/);
  assert.doesNotMatch(caseWorkbench, /切换集合/);
  assert.doesNotMatch(caseWorkbench, /saveTestBrief/);
  assert.doesNotMatch(caseWorkbench, /briefDirty/);
  assert.match(caseWorkbench, /停止生成/);
  assert.match(caseWorkbench, /脑图和用例列表保持空白/);
  assert.match(caseWorkbench, /纳入正式集合/);
  assert.match(caseWorkbench, /用例脑图/);
  assert.match(caseWorkbench, /用例列表/);
  assert.match(caseWorkbench, /sendConversationMessage/);
  assert.match(caseWorkbench, /watchGeneration/);
  assert.doesNotMatch(caseWorkbench, /setInterval/);
  assert.match(apiClient, /resolveApiBaseUrl/);
  assert.match(apiClient, /127\.0\.0\.1/);
  assert.match(caseWorkbench, /commitWorkspaceCandidates/);
  assert.match(caseWorkbench, /updateWorkspaceCandidate/);
  assert.match(caseWorkbench, /updateWorkspaceState/);
  assert.match(caseWorkbench, /result\.context\.model_id/);
  assert.match(caseWorkbench, /model_id: nextModelId/);
  assert.doesNotMatch(caseWorkbench, /当前对话或候选用例尚未保存/);
  assert.doesNotMatch(caseWorkbench, /> 新对话</);
  assert.match(caseWorkbench, /CASE_GENERATE/);
  assert.match(caseWorkbench, /CASE_MODIFY/);
  assert.match(caseWorkbench, /CASE_DELETE/);
  assert.match(caseWorkbench, /CASE_QUERY/);
  assert.match(caseWorkbench, /KNOWLEDGE_QA/);
  assert.match(caseWorkbench, /SMALL_TALK/);
  assert.match(caseWorkbench, /变更审阅/);
  assert.match(caseWorkbench, /确认软删除/);
  assert.match(newConversation, /今天想测试什么/);
  assert.match(newConversation, /自动识别意图/);
  assert.match(newConversation, /正在识别并处理/);
  assert.match(newConversation, /awaiting_intent/);
  assert.match(managementApp, /confirmLandingConversationIntent/);
  assert.match(
    newConversation,
    /仅在确认生成、修改、删除或查询用例时进入绑定集合工作台/,
  );
  assert.match(newConversation, /accept="\.pdf,\.txt,application\/pdf,text\/plain"/);
  assert.match(caseWorkbench, /selectedTargets/);
  assert.match(caseMindMap, /onSelectTarget/);
  assert.match(apiClient, /conversation-operations/);
  assert.match(conversationExamples, /生成登录用例/);
  assert.match(conversationExamples, /梳理测试范围/);
  assert.match(conversationExamples, /局部修改用例/);
  assert.match(newConversation, /历史对话/);
  assert.match(conversationHistory, /listConversationHistory/);
  assert.match(conversationHistory, /role="dialog"/);
  assert.match(conversationHistory, /event\.key === "Escape"/);
  assert.match(conversationHistory, /搜索对话或用例集合/);
  assert.match(apiClient, /\/api\/v1\/conversations/);
  assert.match(apiClient, /\/api\/v1\/conversations\/history/);
  assert.match(apiClient, /test-briefs\/\$\{version\}\/download/);
  assert.match(apiClient, /case-change-sets/);
  assert.match(apiClient, /test-briefs\/confirm/);
  assert.match(apiClient, /workspace-candidates/);
  assert.match(apiClient, /generation-jobs\/\$\{jobId\}\/cancel/);
  assert.match(css, /\.principle-workbench/);
  assert.match(css, /\.principle-brief/);
  assert.match(css, /\.principle-stop/);
  assert.match(css, /\.new-conversation/);
  assert.match(css, /\.principle-new-conversation/);
  assert.match(css, /\.principle-brief-document/);
  assert.match(caseWorkbench, /listGenerationModels/);
  assert.doesNotMatch(caseWorkbench, /Test Design Pro/);
  assert.match(caseEditor, /当前用例修改尚未保存/);
  assert.match(caseEditor, /beforeunload/);
  assert.match(sampleCases, /case_key: "AUTH-001"/);
  assert.match(sampleCases, /case_key: "AUTH-012"/);
  assert.match(sampleAudioCases, /case_key: "AUDIO-001"/);
  assert.match(sampleAudioCases, /case_key: "AUDIO-018"/);
  assert.match(executionWorkspace, /createExecutionRun/);
  assert.match(executionWorkspace, /completed_step_ids/);
  assert.match(executionWorkspace, /任务描述/);
  assert.match(executionWorkspace, /请填写本次执行任务的目标或范围/);
  assert.match(executionWorkspace, /descriptionRef\.current\?\.focus/);
  assert.doesNotMatch(executionWorkspace, /软件版本|构建号|测试环境/);
  assert.match(executionWorkspace, /新建执行任务/);
  assert.match(executionWorkspace, /任务历史/);
  assert.match(executionWorkspace, /执行人/);
  assert.match(executionWorkspace, /空间成员/);
  assert.match(executionWorkspace, /reassignExecutionRecord/);
  assert.match(executionWorkspace, /listSpaceMembers/);
  assert.match(executionWorkspace, /每 5 秒自动同步多人执行进度/);
  assert.match(executionWorkspace, /closeExecutionRun/);
  assert.match(executionWorkspace, /readOnly/);
  assert.doesNotMatch(executionWorkspace, /标记通过前，请先逐项完成所有执行步骤/);
  assert.match(executionWorkspace, /可选记录，不影响执行结果/);
  assert.match(executionWorkspace, /aria-pressed/);
  assert.doesNotMatch(executionWorkspace, /option\.value === "passed"/);
  assert.match(executionNotes, /记录已保存/);
  assert.doesNotMatch(executionWorkspace, /内容状态/);
  assert.match(apiClient, /listSpaceExecutionRuns/);
  assert.match(apiClient, /base_updated_at/);
  assert.match(apiClient, /test-cases\/batch/);
  assert.match(apiClient, /\/execution-records\/\$\{recordId\}/);
  assert.match(apiClient, /\/execution-records\/\$\{recordId\}\/assignee/);
  assert.match(apiClient, /\/spaces\/\$\{spaceId\}\/members/);
  assert.doesNotMatch(apiClient, /CaseStatusApi|status-events/);
  assert.doesNotMatch(apiClient, /startMockGeneration|watchMockGeneration/);
  assert.match(apiClient, /\/api\/v1\/generation-jobs/);
  assert.match(apiClient, /requirement\.analyzed/);
  assert.match(css, /\.management-app/);
  assert.match(css, /\.case-library/);
  assert.match(css, /\.execution-workspace/);
});
