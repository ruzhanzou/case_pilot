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
