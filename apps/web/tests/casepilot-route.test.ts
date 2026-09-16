import assert from "node:assert/strict";
import test from "node:test";

import { casePilotPath, parseCasePilotRoute } from "../lib/casepilot-route";

test("parses semantic CasePilot routes", () => {
  assert.deepEqual(parseCasePilotRoute(undefined), { page: "workbench" });
  assert.deepEqual(
    parseCasePilotRoute(["workbench", "conversations", "conversation-1"]),
    { page: "workbench", conversationId: "conversation-1" },
  );
  assert.deepEqual(parseCasePilotRoute(["cases", "collection-1", "case-1"]), {
    page: "library",
    collectionId: "collection-1",
    caseId: "case-1",
  });
  assert.deepEqual(parseCasePilotRoute(["executions", "collection-1"]), {
    page: "execution",
    collectionId: "collection-1",
  });
});

test("builds bookmarkable CasePilot paths", () => {
  assert.equal(casePilotPath({ page: "workbench" }), "/workbench");
  assert.equal(
    casePilotPath({ page: "workbench", conversationId: "conversation-1" }),
    "/workbench/conversations/conversation-1",
  );
  assert.equal(
    casePilotPath({
      page: "library",
      collectionId: "collection-1",
      caseId: "case-1",
    }),
    "/cases/collection-1/case-1",
  );
  assert.equal(
    casePilotPath({ page: "execution", collectionId: "collection-1" }),
    "/executions/collection-1",
  );
});
