import assert from "node:assert/strict";
import test from "node:test";
import { matchesExecutionSearch } from "../lib/execution-search";
import type { ExecutionRunSummaryDto } from "../lib/casepilot-api";

const run = {
  description: "登录 Smoke 回归", source_name: "支付 Playlist", collection_name: null,
  creator_name: "张三", assignee_names: ["李四"], contributor_names: ["王五"],
} as ExecutionRunSummaryDto;

test("task search matches partial Chinese, case-insensitive and normalized text", () => {
  for (const query of ["", "  ", "登录", "SMOK", "ＳＭＯＫＥ", "支付", "李四", "王五", "张三", "登录  playlist 李四"]) {
    assert.equal(matchesExecutionSearch(run, query), true, query);
  }
  assert.equal(matchesExecutionSearch(run, "登录 missing"), false);
  assert.equal(matchesExecutionSearch(run, "%"), false);
});
