import assert from "node:assert/strict";
import test from "node:test";
import { canonicalSelection, createSelectionQueue, legacySelectionTargets } from "../lib/workbench-selection";

test("canonical selection rejects missing revision without guessing", () => {
  assert.equal(canonicalSelection({ targets: [], items: [] }), null);
  assert.equal(canonicalSelection({ schema_version: 1, version: 0, targets: [], items: [] })?.version, 0);
});
test("rapid selection edits serialize against acknowledged CAS revisions", async () => {
  const calls: [number, string][] = [];
  const queue = createSelectionQueue(async (version, input: string) => { calls.push([version, input]); return version + 1; }, result => result);
  queue.rebase(4);
  const first = queue.submit("a"), second = queue.submit("b");
  await Promise.all([first, second]); await queue.wait();
  assert.deepEqual(calls, [[4, "a"], [5, "b"]]);
  assert.equal(queue.version, 6); assert.equal(queue.pending, false);
});
test("conflict never replays queued stale scope; fresh user action requires rehydrate", async () => {
  const calls: string[] = [];
  const queue = createSelectionQueue(async (_version, input: string) => { calls.push(input); if (input === "a") throw new Error("409"); return 9; }, result => result);
  await Promise.allSettled([queue.submit("a"), queue.submit("stale")]);
  await assert.rejects(queue.wait(), /409/);
  assert.deepEqual(calls, ["a"]);
  queue.rebase(8);
  await queue.submit("fresh");
  assert.deepEqual(calls, ["a", "fresh"]);
});


test("reload ignores legacy shapes entirely when canonical selection exists", () => {
  const context = { workbench_selection: { schema_version: 1, version: 3, targets: [{kind: "case", case_ids:["new"]}], items:[] },
    get selected_targets(): unknown { throw new Error("must not access legacy selection"); } };
  assert.deepEqual(legacySelectionTargets(context, "Selected"), []);
});
test("legacy reload accepts both exact wrappers and bare targets without broadening", () => {
  const wrapped = {kind: "case" as const, case_ids:["a"], collection_id:"collection-a"};
  const bare = {kind: "case" as const, candidate_refs:["candidate:b"]};
  const rows = legacySelectionTargets({ selected_targets:[{label:"One case", target:wrapped}, bare] }, "Selected");
  assert.equal(rows.length, 2);
  assert.deepEqual(rows[0].target, wrapped); assert.deepEqual(rows[1].target, bare);
  assert.equal(rows[0].label, "One case"); assert.equal(rows[1].label, "Selected");
});
test("malformed legacy entries never turn missing case IDs into collection-wide targets", () => {
  const values = [null, 1, [], {}, {target:null}, {kind:"case"}, {kind:"case", case_ids:["a", 5]},
    {kind:"module"}, {kind:"condition", condition:42}, {kind:"previous_result"}, {kind:"all"}];
  assert.deepEqual(legacySelectionTargets({selected_targets:values}, "Selected"), []);
});
