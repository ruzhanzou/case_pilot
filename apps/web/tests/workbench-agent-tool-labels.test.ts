import assert from "node:assert/strict";
import test from "node:test";
import { agentToolLabels } from "../lib/workbench-agent-tool-labels";
import { parseAgentActivity } from "../lib/workbench-agent-activity";
import { parseAgentStreamEvent } from "../lib/workbench-agent-stream";

test("historical table tools have honest bilingual query and draft-preview labels", () => {
  const english = agentToolLabels(en => en);
  const chinese = agentToolLabels((_en, zh) => zh);
  assert.equal(english.query_uploaded_cases, "Query historical table cases");
  assert.equal(chinese.query_uploaded_cases, "历史表用例查询");
  assert.equal(english.preview_uploaded_cases, "Preview historical case drafts");
  assert.equal(chinese.preview_uploaded_cases, "历史用例草稿预览");
});

test("live and persisted activity accept both historical table tool names", () => {
  for (const tool of ["query_uploaded_cases", "preview_uploaded_cases"]) {
    const event = { sequence: 1, type: "tool_started", tool };
    assert.equal(parseAgentStreamEvent(JSON.stringify(event))?.tool, tool);
    assert.equal(parseAgentActivity({ status: "running", events: [event] })?.events[0].tool, tool);
  }
});


test("collection deletion activity describes preparation, not approval or completed deletion", () => {
  assert.equal(agentToolLabels(en => en).delete_collection, "Prepare collection soft deletion");
  assert.equal(agentToolLabels((_en, zh) => zh).delete_collection, "准备集合软删除方案");
  const event = { sequence: 1, type: "tool_completed", tool: "delete_collection" };
  assert.equal(parseAgentStreamEvent(JSON.stringify(event))?.tool, "delete_collection");
});

test("collection navigation activity is distinct from asset selection", () => {
  assert.equal(agentToolLabels(en => en).select_collection, "Switch working collection");
  assert.equal(agentToolLabels((_en, zh) => zh).select_collection, "切换工作集合");
  const event = { sequence: 1, type: "tool_completed", tool: "select_collection" };
  assert.equal(parseAgentStreamEvent(JSON.stringify(event))?.tool, "select_collection");
});
