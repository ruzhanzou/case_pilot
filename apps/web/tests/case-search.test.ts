import assert from "node:assert/strict";
import test from "node:test";

import { matchesCaseSearch, matchesCollectionSearch } from "../lib/case-search";
import type { CaseCollectionDto, TestCaseDto } from "../lib/casepilot-api";

const testCase: TestCaseDto = {
  id: "case-1",
  case_key: "CP-42-CASE-001",
  collection_ids: ["collection-1"],
  current_revision_id: "revision-1",
  revision_number: 1,
  title: "登录链路回归",
  module: "认证中心",
  priority: "P0",
  case_type: "功能",
  tags: ["smoke"],
  preconditions: [],
  steps: [],
  source: "需求生成",
  source_refs: [],
  creator: {
    id: "account-1",
    display_name: "张三",
    email: "zhangsan@example.com",
  },
  test_targets: [
    {
      source_system: "testtool",
      target_type: "fr_test",
      target_id: 150079209,
      target_key: "FR-2026-042",
      title: "统一登录",
      linked_fr_ids: [150079209],
      linked_qpm_ids: ["QPM-88"],
    },
  ],
  created_at: "2026-09-12T00:00:00Z",
};

test("matches test_target and creator with multi-term fuzzy search", () => {
  assert.equal(matchesCaseSearch(testCase, "fr_test"), true);
  assert.equal(matchesCaseSearch(testCase, "007920"), true);
  assert.equal(matchesCaseSearch(testCase, "fr-2026 张三"), true);
  assert.equal(matchesCaseSearch(testCase, "qpm-88 zhangsan"), true);
  assert.equal(matchesCaseSearch(testCase, "FR-2026 李四"), false);
});

const collection: CaseCollectionDto = {
  id: "collection-1",
  space_id: "space-1",
  name: "统一登录搜索验收",
  description: "登录资产集合",
  case_count: 2,
  creator: testCase.creator,
  test_target: testCase.test_targets?.[0],
  created_at: "2026-09-12T00:00:00Z",
};

test("matches collections by target and creator", () => {
  assert.equal(matchesCollectionSearch(collection, "统一 登录"), true);
  assert.equal(matchesCollectionSearch(collection, "fr-2026 张三"), true);
  assert.equal(matchesCollectionSearch(collection, "007920 zhangsan"), true);
  assert.equal(matchesCollectionSearch(collection, "fr-2026 李四"), false);
});
