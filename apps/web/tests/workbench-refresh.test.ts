import assert from "node:assert/strict";
import test from "node:test";
import { refreshCurrentWorkspace } from "../lib/workbench-refresh";
import type { CaseChangeSetDto, ConversationDto } from "../lib/casepilot-api";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
const workspace = { id: "old", operation_plan: { operations: [
  { status: "awaiting_confirmation", related_change_set_id: "old-review" },
] } } as ConversationDto;
const changeSet = { id: "old-review", status: "ready" } as CaseChangeSetDto;

for (const stage of ["workspace", "approval"] as const) {
  test(`late terminal refresh cannot apply old ${stage} after thread navigation`, async () => {
    const first = deferred<ConversationDto>(), second = deferred<CaseChangeSetDto>();
    let epoch = 1;
    const capturedEpoch = epoch;
    const applied: string[] = [];
    let reviewReads = 0;
    const pending = refreshCurrentWorkspace({
      isCurrent: () => epoch === capturedEpoch,
      loadWorkspace: () => first.promise,
      applyWorkspace: value => applied.push(value.id),
      loadChangeSet: () => { reviewReads++; return second.promise; },
      applyChangeSet: value => applied.push(value.id),
    });
    if (stage === "workspace") epoch++;
    first.resolve(workspace);
    await Promise.resolve();
    if (stage === "approval") epoch++;
    second.resolve(changeSet);
    assert.equal(await pending, null);
    assert.deepEqual(applied, stage === "workspace" ? [] : ["old"]);
    assert.equal(reviewReads, stage === "workspace" ? 0 : 1);
  });
}

test("current terminal refresh restores workspace and exact ready approval", async () => {
  const applied: string[] = [];
  assert.equal(await refreshCurrentWorkspace({
    isCurrent: () => true, loadWorkspace: async () => workspace,
    applyWorkspace: value => applied.push(value.id), loadChangeSet: async () => changeSet,
    applyChangeSet: value => applied.push(value.id),
  }), workspace);
  assert.deepEqual(applied, ["old", "old-review"]);
});

import { createJobObserverGuard } from "../lib/workbench-refresh";
test("draft job callbacks and cleanup lose ownership on navigation, unmount, or replacement job", () => {
  const navigation = {active:true};
  const currentNavigation = {current:navigation};
  const watchedJob = {current:"draft-a"};
  const current = createJobObserverGuard(navigation,currentNavigation,watchedJob,"draft-a");
  assert.equal(current(),true);
  watchedJob.current="draft-b";
  assert.equal(current(),false);
  watchedJob.current="draft-a";
  currentNavigation.current={active:true};
  assert.equal(current(),false);
  currentNavigation.current=navigation;
  navigation.active=false;
  assert.equal(current(),false);
});
