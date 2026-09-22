import assert from "node:assert/strict";
import test from "node:test";
import { isModuleWithin, moduleAncestors, modulePath } from "../lib/case-module-tree";

test("module paths trim whitespace and ignore empty segments", () => {
  assert.equal(modulePath(" / Selective Logging / ODP // Location / "), "Selective Logging/ODP/Location");
  assert.deepEqual(moduleAncestors("Selective Logging/ODP/ODP Condition Matching/Location"), [
    "Selective Logging", "Selective Logging/ODP", "Selective Logging/ODP/ODP Condition Matching",
    "Selective Logging/ODP/ODP Condition Matching/Location",
  ]);
  assert.deepEqual(moduleAncestors(" / "), []);
});

test("module membership respects segment boundaries", () => {
  assert.equal(isModuleWithin("A/B/C", "A/B"), true);
  assert.equal(isModuleWithin(" A / B ", "A/B"), true);
  assert.equal(isModuleWithin("A/BC", "A/B"), false);
});
