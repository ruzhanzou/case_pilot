import assert from "node:assert/strict";
import test from "node:test";
import type { CaseChangeSetDto } from "../lib/casepilot-api";
import { reviewableChangeRefs, selectedReviewFields } from "../lib/workbench-review";
const change: CaseChangeSetDto = { id: "proposal", conversation_id: "chat", generation_job_id: null, instruction: "Change title only", scope: "selected", status: "ready", created_at: "", applied_at: null, items: [
  { ref: "a", target_type: "formal", base_revision_id: "r1", base_snapshot: { title: "Old" }, proposed_snapshot: { title: "New" }, field_diff: [{ field: "title", before: "Old", after: "New" }], reason: "Requested", status: "ready" },
  { ref: "b", target_type: "formal", base_snapshot: {}, proposed_snapshot: {}, field_diff: [], reason: "Incomplete", status: "ready", quality: { passed: false } },
  { ref: "c", target_type: "formal", base_snapshot: {}, proposed_snapshot: {}, field_diff: [], reason: "Already saved", status: "applied" },
] };
test("chat and panel selection are exact eligible proposal fields", () => {
  assert.deepEqual(reviewableChangeRefs(change), ["a"]);
  assert.deepEqual(selectedReviewFields(change, { a: ["title", "steps"], b: ["title"], outside: ["title"] }), { a: ["title"] });
  assert.equal(change.items[0].base_revision_id, "r1");
});
test("empty selections remain explicit rejection, never broaden to all fields", () => {
  assert.deepEqual(selectedReviewFields(change, {}), { a: [] });
});
test("historical, failed and conflicted proposal states cannot be submitted", () => {
  for (const status of ["applied", "rejected", "generating", "failed", "superseded", "conflict"] as const) {
    assert.deepEqual(reviewableChangeRefs({ ...change, status }), []);
    assert.deepEqual(selectedReviewFields({ ...change, status }, { a: ["title"] }), {});
  }
});
