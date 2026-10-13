import assert from "node:assert/strict";
import test from "node:test";
import { draftFromRecord, executionRecordUpdate } from "../lib/execution-record-draft";
import type { ExecutionRecordDto } from "../lib/casepilot-api";

test("polling a newer result cannot advance an unsaved draft's conflict version", () => {
  const original = { id: "record", status: "not_run", actual_result: "old", defect_ref: "", completed_step_ids: [], updated_at: "2026-10-13T01:00:00Z" } as unknown as ExecutionRecordDto;
  const draft = { ...draftFromRecord(original), actualResult: "local edit" };
  const polled = { ...original, actual_result: "another window", updated_at: "2026-10-13T01:01:00Z" };
  const update = executionRecordUpdate(polled, { actual_result: draft.actualResult }, draft);
  assert.equal(update.actual_result, "local edit");
  assert.equal(update.base_updated_at, original.updated_at);
  assert.equal(executionRecordUpdate(polled, { status: "passed" }, draft).base_updated_at, original.updated_at);
  const reloaded = draftFromRecord(polled);
  assert.equal(reloaded.actualResult, "another window");
  assert.equal(executionRecordUpdate(polled, { actual_result: "revised" }, reloaded).base_updated_at, polled.updated_at);
});
