import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { CandidateReviewNotice } from "../components/candidate-review-notice";
import { I18nProvider } from "../lib/i18n";
import { candidateReviewGroups } from "../lib/candidate-generation-review";
import type { ConversationDto, WorkspaceCandidateDto } from "../lib/casepilot-api";

const candidates = [
  { id: "candidate", generation_job_id: "job", snapshot: { generation_review: { status: "certified" } } },
] as unknown as WorkspaceCandidateDto[];
const conversation = {
  messages: [],
  generation_reviews: { job: {
    authority: "server_generation_job", generation_job_id: "job", status: "pending_manual",
    independent_quality_verified: false, structural_passed: true, grounding_status: "unverified",
    issues: [{ code: "planning_source_unverified", message: "Unverified <script>source</script>", severity: "warning", object_id: "point" }],
  } },
} as unknown as ConversationDto;

test("server generation notes remain unverified even if a candidate claims certification", () => {
  const groups = candidateReviewGroups(conversation, candidates);
  assert.equal(groups[0].status, "pending_manual");
  assert.match(groups[0].notes[0].message, /Unverified/);
  const html = renderToStaticMarkup(createElement(I18nProvider, null,
    createElement(CandidateReviewNotice, { conversation, candidates })));
  assert.match(html, /Business content needs independent review/);
  assert.match(html, /does not certify business expectations or coverage/);
  assert.match(html, /Pending manual review/);
  assert.match(html, /&lt;script&gt;source&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>/);
});

test("legacy useful notes survive without becoming a quality certificate", () => {
  const legacy = { ...conversation, generation_reviews: undefined, messages: [
    { related_job_id: "job", metadata: { generation_quality_issues: [{ message: "Prior warning" }] } },
    { related_job_id: "other", metadata: { generation_quality_issues: [{ message: "Other job" }] } },
  ] } as unknown as ConversationDto;
  const group = candidateReviewGroups(legacy, candidates)[0];
  assert.equal(group.status, "not_assessed");
  assert.deepEqual(group.notes, [{ code: "unknown", message: "Prior warning" }]);
  const forged = { ...conversation, generation_reviews: { job: {
    ...conversation.generation_reviews!.job, independent_quality_verified: true,
  } } } as unknown as ConversationDto;
  assert.equal(candidateReviewGroups(forged, candidates)[0].status, "not_assessed");
});

test("notes follow exact job identity and group multiple candidates without duplication", () => {
  const changed = { ...conversation, generation_reviews: { job: {
    ...conversation.generation_reviews!.job, generation_job_id: "foreign",
  } } } as ConversationDto;
  assert.equal(candidateReviewGroups(changed, candidates)[0].status, "not_assessed");
  const grouped = candidateReviewGroups(conversation, [...candidates, ...candidates]);
  assert.equal(grouped.length, 1);
  assert.equal(grouped[0].count, 2);
  assert.equal(grouped[0].notes.length, 1);
});

test("new not-assessed records do not hide legacy notes; exact duplicates merge", () => {
  const value = { ...conversation, generation_reviews: { job: {
    ...conversation.generation_reviews!.job, status: "not_assessed", issues: [],
  } }, messages: [{ related_job_id: "job", metadata: { generation_quality_issues: [
    { code: "old", message: "Still useful", object_id: "p1" },
    { code: "old", message: "Still useful", object_id: "p1" },
    { code: "old", message: "Still useful", object_id: "p2" },
  ] } }] } as unknown as ConversationDto;
  const groups = candidateReviewGroups(value, candidates);
  assert.equal(groups[0].status, "not_assessed");
  assert.equal(groups[0].notes.length, 2);
  assert.deepEqual(groups[0].notes.map(item => item.objectId), ["p1", "p2"]);
});

test("conversation inline adoption also presents unverified notes before its action", async () => {
  const { ConversationCandidates } = await import("../components/conversation-candidates");
  const item = { ...candidates[0], id: "c", version: 1, snapshot: {
    id: "c", title: "Review this case", module: "Synthetic", priority: "P1",
    preconditions: [], steps: [],
  } } as unknown as WorkspaceCandidateDto;
  const html = renderToStaticMarkup(createElement(I18nProvider, null,
    createElement(ConversationCandidates, { conversation, candidates: [item], busy: false,
      onCommit: () => {}, onInspect: () => {} })));
  assert.match(html, /does not certify business expectations or coverage/);
  assert.ok(html.indexOf("candidate-review-notice") < html.indexOf("Accept these 1 candidates"));
});

test("historical errors cannot be weakened by an otherwise equal current warning", () => {
  const value = { ...conversation, messages: [{ related_job_id: "job", metadata: {
    generation_quality_issues: [{ ...conversation.generation_reviews!.job.issues[0], severity: "error" }],
  } }] } as unknown as ConversationDto;
  const group = candidateReviewGroups(value, candidates)[0];
  assert.equal(group.notes.length, 1);
  assert.equal(group.notes[0].severity, "error");
  const malformed = { ...value, generation_reviews: { job: {
    ...value.generation_reviews!.job, issues: value.generation_reviews!.job.issues.map(note => ({ ...note, severity: "constructor" })),
  } } } as ConversationDto;
  assert.equal(candidateReviewGroups(malformed, candidates)[0].notes[0].severity, "error");
});
