import assert from "node:assert/strict";
import test from "node:test";
import type { ConversationDto, ConversationMessageDto } from "../lib/casepilot-api";
import { requestsImplicitMutation, workspaceIsRunning, workspaceTasks, shouldResumePendingTask } from "../lib/workspace-tasks";

const message = (id: string, overrides: Partial<ConversationMessageDto> = {}): ConversationMessageDto => ({
  id, role: "assistant", content: id, intent: "CASE_MODIFY", intent_confidence: 1,
  status: "completed", target_case_ids: [], related_job_id: null, citations: [], metadata: {}, created_at: "2026-10-07", ...overrides,
});
const conversation = (messages: ConversationMessageDto[]): ConversationDto => ({
  id: "conversation", space_id: "space", collection_id: "collection", title: "Tasks", status: "active", context: {},
  messages, test_briefs: [], candidates: [], workflow_runs: [], operation_plan: null, created_at: "", updated_at: "",
});

test("confirmation updates the original task and keeps its originating request", () => {
  const result = workspaceTasks(conversation([
    message("request", { role: "user", content: "Rewrite login" }),
    message("draft", { metadata: { change_set_id: "change" }, status: "awaiting_confirmation" }),
    message("question", { role: "user", content: "What is password policy?" }),
    message("answer", { intent: "KNOWLEDGE_QA" }),
    message("applied", { metadata: { change_set_id: "change", action: "applied" } }),
  ]));
  assert.equal(result.length, 2);
  assert.equal(result[1].request?.id, "request");
  assert.equal(result[1].message.id, "applied");
  assert.deepEqual(result[1].messageIds, ["draft", "applied"]);
  assert.equal(result[1].status, "completed");
});

test("completed workers awaiting confirmation release messaging", () => {
  const state = conversation([message("draft", { status: "awaiting_confirmation" })]);
  state.workflow_runs = [{ job_id: "job", message_id: "draft", operation: "CASE_MODIFY", status: "completed", current_stage: "completed", progress: 100, error_code: null, stages: [], created_at: "", updated_at: "" }];
  assert.equal(workspaceTasks(state)[0].status, "awaiting_confirmation");
  assert.equal(workspaceIsRunning(state), false);
  state.workflow_runs[0].status = "running";
  assert.equal(workspaceIsRunning(state), true);
  state.workflow_runs[0].status = "failed";
  assert.equal(workspaceIsRunning(state), false);
});

test("operations, including queued siblings, are the stable task identity", () => {
  const state = conversation([
    message("request", { role: "user" }),
    message("draft", { metadata: { operation_id: "generate" } }),
    message("confirmed", { role: "user", content: "Confirm scope" }),
    message("candidates", { related_job_id: "job" }),
  ]);
  const base = { confidence: 1, target: {}, payload: {}, result: {}, requires_confirmation: true, related_job_id: null, related_change_set_id: null, error_code: null, created_at: "2026-10-07", source_message_id: "request" };
  state.operation_history = [
    { ...base, id: "generate", sequence: 0, intent: "CASE_GENERATE", status: "awaiting_confirmation", related_job_id: "job" },
    { ...base, id: "review", sequence: 1, intent: "CASE_REVIEW", status: "queued" },
  ];
  const tasks = workspaceTasks(state);
  assert.equal(tasks.length, 2);
  const generation = tasks.find((item) => item.id === "generate")!;
  assert.deepEqual(generation.messageIds, ["draft", "candidates"]);
  assert.equal(generation.request?.id, "request");
  assert.equal(generation.status, "awaiting_confirmation");
  assert.equal(tasks.find((item) => item.id === "review")?.waitingOn, "generate");
});

test("cancelled changes are displayed as not applied, with their source link", () => {
  const state = conversation([message("cancelled", { metadata: { change_set_id: "change", action: "rejected" } })]);
  state.operation_history = [{ id: "modify", sequence: 0, intent: "CASE_MODIFY", confidence: 1, status: "cancelled", target: {}, payload: { source_operation_id: "review" }, result: {}, requires_confirmation: true, related_job_id: null, related_change_set_id: "change", error_code: null, created_at: "2026-10-07" }];
  const [task] = workspaceTasks(state);
  assert.equal(task.status, "not_applied");
  assert.equal(task.sourceTaskId, "review");
});


test("explicit new intents do not resume an unrelated pending task", () => {
  assert.equal(shouldResumePendingTask("CASE_QUERY", "修改用例 CP-001：标题改为成功登录"), false);
  assert.equal(shouldResumePendingTask("CASE_MODIFY", "请查询账号登录模块"), false);
  assert.equal(shouldResumePendingTask("CASE_MODIFY", "修改用例 CP-001：标题改为成功登录"), true);
  assert.equal(shouldResumePendingTask("CASE_MODIFY", "目标是 CP-001"), true);
  assert.equal(shouldResumePendingTask("CASE_QUERY", "查询登录模块，然后查询商品搜索模块"), false);
});

test("read-only requests do not inherit a stale mutation selection", () => {
  assert.equal(requestsImplicitMutation("查询账号登录模块，然后查询商品搜索模块，只查询不修改"), false);
  assert.equal(requestsImplicitMutation("query cases, do not modify"), false);
  assert.equal(requestsImplicitMutation("修改标题，不要删除"), true);
});

test("three rewrite rounds form one stable task with inspectable history", () => {
  const state = conversation([]);
  const base = { sequence: 0, confidence: 1, target: {}, result: {}, requires_confirmation: true, related_job_id: null, error_code: null, created_at: "2026-10-08" };
  state.operation_history = [
    { ...base, id: "v3", intent: "CASE_MODIFY", status: "awaiting_confirmation", payload: { source_operation_id: "v2", task_id: "v1" }, related_change_set_id: "c3" },
    { ...base, id: "query", intent: "CASE_QUERY", status: "completed", payload: {}, related_change_set_id: null },
    { ...base, id: "v1", intent: "CASE_MODIFY", status: "cancelled", payload: {}, related_change_set_id: "c1" },
    { ...base, id: "v2", intent: "CASE_MODIFY", status: "cancelled", payload: { source_operation_id: "v1" }, related_change_set_id: "c2" },
    { ...base, id: "separate", intent: "CASE_MODIFY", status: "awaiting_confirmation", payload: {}, related_change_set_id: "other" },
  ];
  const tasks = workspaceTasks(state);
  assert.equal(tasks.length, 3);
  const task = tasks.find(t => t.id === "v1")!;
  assert.equal(task.operation?.id, "v3");
  assert.equal(task.message.metadata.change_set_id, "c3");
  assert.deepEqual(task.versions?.map(t => t.id), ["v1", "v2", "v3"]);
  assert.equal(task.status, "awaiting_confirmation");
});

test("generation reviews stay open and explicit new roots do not rejoin closed tasks", () => {
  const state = conversation([]);
  const base = { sequence: 0, confidence: 1, target: {}, result: {}, requires_confirmation: true, related_job_id: null, error_code: null, created_at: "2026-10-08", related_change_set_id: null };
  state.context = { active_mutation_task_id: "generate" };
  state.operation_history = [
    { ...base, id: "generate", intent: "CASE_GENERATE", status: "awaiting_confirmation", payload: { task_id: "generate" } },
    { ...base, id: "query", intent: "CASE_QUERY", status: "completed", payload: {} },
    { ...base, id: "rewrite", intent: "CASE_MODIFY", status: "completed", payload: { task_id: "generate", source_operation_id: "generate" } },
    { ...base, id: "new", intent: "CASE_MODIFY", status: "awaiting_confirmation", payload: { task_id: "new", source_operation_id: "rewrite" } },
  ];
  const tasks = workspaceTasks(state);
  assert.equal(tasks.length, 3);
  assert.equal(tasks.find(t => t.id === "generate")?.status, "awaiting_confirmation");
  assert.deepEqual(tasks.find(t => t.id === "generate")?.versions?.map(t => t.id), ["generate", "rewrite"]);
  assert.equal(tasks.find(t => t.id === "new")?.operation?.id, "new");
});


test("new field values cannot become implicit target references", async () => {
  const { scopeReferenceText } = await import("../lib/workspace-tasks");
  for (const value of ["库存不足禁止下单", "CP-OTHER-123", "订单/退款"]) {
    assert.equal(scopeReferenceText(`把刚才查到的用例标题改为「${value}」`), "把刚才查到的用例");
    assert.equal(scopeReferenceText(`把用例 CP-001 标题改为「${value}」，其他字段不变`), "把用例 CP-001 ，其他字段不变");
  }
  assert.equal(scopeReferenceText('查询标题包含「订单」的用例'), '查询的用例');
  assert.equal(scopeReferenceText('查询登录模块标题包含订单的用例'), '查询登录模块的用例');
});


test("deletion caused by this task is expected; unrelated revision changes still warn", async () => {
  const { taskScopeChanged } = await import("../lib/workspace-tasks");
  const state = conversation([]);
  state.operation_history = [{ id: "delete", sequence: 0, intent: "CASE_DELETE", confidence: 1, status: "completed", target: {}, payload: {}, result: { scope_versions: { deleted: "v1", retained: "v2" }, updated_refs: ["deleted"] }, requires_confirmation: true, related_job_id: null, related_change_set_id: "change", error_code: null, created_at: "2026-10-09" }];
  const [task] = workspaceTasks(state);
  const cases = [{ id: "retained", current_revision_id: "v2" }] as import("../lib/casepilot-api").TestCaseDto[];
  assert.equal(taskScopeChanged(task, cases), false);
  assert.equal(taskScopeChanged(task, [{ ...cases[0], current_revision_id: "v3" }]), true);
  assert.equal(taskScopeChanged(task, []), true);
  task.operation!.result.updated_refs = [];
  assert.equal(taskScopeChanged(task, cases), true);
  task.operation!.result.updated_refs = ["deleted"];
  task.operation!.intent = "CASE_QUERY";
  assert.equal(taskScopeChanged(task, cases), true);
});

test("batch previews bind to the generating message when a saved brief has no operation", async () => {
  const { candidatesForTask } = await import("../lib/workspace-tasks");
  const state = conversation([message("generation", { intent: "CASE_GENERATE", status: "running", related_job_id: "current-job" })]);
  const preview = { id: "preview", generation_job_id: "current-job", ref: "TC-1", version: 1, position: 0, snapshot: { id: "TC-1", title: "登录", module: "登录", case_type: "功能", priority: "P1" as const, tags: [], status: "pending", preconditions: [], steps: [], source_refs: [] }, included: false, status: "generating", updated_at: "" };
  state.candidate_history = [preview, { ...preview, id: "unrelated", generation_job_id: "previous-job" }];
  assert.deepEqual(candidatesForTask(workspaceTasks(state)[0], state).map(item => item.id), ["preview"]);
});


test("parallel previews follow planned positions instead of completion order", async () => {
  const { candidatesForTask } = await import("../lib/workspace-tasks");
  const state = conversation([message("generation", { intent: "CASE_GENERATE", status: "running", related_job_id: "current-job" })]);
  const base = { generation_job_id: "current-job", ref: "TC", version: 1, snapshot: { id: "TC", title: "Login", module: "Login", case_type: "Functional", priority: "P1" as const, tags: [], status: "pending", preconditions: [], steps: [], source_refs: [] }, included: false, status: "generating", updated_at: "" };
  state.candidate_history = [{ ...base, id: "fast-second", position: 5 }, { ...base, id: "slow-first", position: 0 }];
  assert.deepEqual(candidatesForTask(workspaceTasks(state)[0], state).map(item => item.id), ["slow-first", "fast-second"]);
  assert.equal(state.candidate_history[0].id, "fast-second");
});
