import assert from "node:assert/strict";
import test from "node:test";

import { operationStatusLabel, operationStatusLabels } from "../lib/operation-status";

const statuses = [
  "queued",
  "running",
  "awaiting_confirmation",
  "awaiting_intent",
  "awaiting_collection",
  "awaiting_target",
  "completed",
  "skipped",
  "failed",
  "cancelled",
];

test("all operation states have user-facing Chinese and English labels", () => {
  for (const locale of ["zh-CN", "en"] as const) {
    const labels = operationStatusLabels(locale);
    for (const status of statuses) {
      assert.equal(operationStatusLabel(status, locale), labels[status]);
      assert.ok(labels[status]);
      assert.doesNotMatch(labels[status], /_/);
    }
  }
});

test("unknown operation states stay non-technical", () => {
  assert.equal(operationStatusLabel("new_internal_state", "zh-CN"), "处理中");
  assert.equal(operationStatusLabel("new_internal_state", "en"), "Processing");
});
