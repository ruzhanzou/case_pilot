import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ReferenceSnapshot } from "../components/reference-snapshot";
import {
  getCollectionReferences, getWorkspaceReferenceContext, updateCollectionReferences,
} from "../lib/casepilot-api";

test("reading context never binds; explicit binding sends exact user CAS", async () => {
  const original = globalThis.fetch;
  const calls: { url: string; init?: RequestInit }[] = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return new Response(JSON.stringify({ version: 4, sources: [] }), {
      status: 200, headers: { "content-type": "application/json" },
    });
  };
  try {
    await getCollectionReferences("collection-a");
    await getWorkspaceReferenceContext("conversation-a");
    assert(calls.every(call => !call.init?.method || call.init.method === "GET"));
    await updateCollectionReferences("collection-a", 3, ["source-a"]);
    const call = calls.at(-1)!;
    assert.equal(call.init?.method, "PUT");
    assert.deepEqual(JSON.parse(String(call.init?.body)), { base_version: 3, source_ids: ["source-a"] });
    assert.match(call.url, /collections\/collection-a\/references$/);
  } finally { globalThis.fetch = original; }
});

test("stale binding surfaces without silently retrying a replacement version", async () => {
  const original = globalThis.fetch;
  let count = 0;
  globalThis.fetch = async () => {
    count++;
    return new Response(JSON.stringify({ detail: "collection_reference_version_conflict" }), {
      status: 409, headers: { "content-type": "application/json" },
    });
  };
  try {
    await assert.rejects(updateCollectionReferences("collection-a", 2, []));
    assert.equal(count, 1);
  } finally { globalThis.fetch = original; }
});

test("proposal displays captured source versions and escapes reference names", () => {
  const html = renderToStaticMarkup(createElement(ReferenceSnapshot, { binding: {
    collection_version: 3,
    sources: [{ source_id: "s", name: "<script>not instructions</script>",
      source_revision: 7, available: true,
      documents: [{ id: "d", name: "requirements.txt", mime_type: "text/plain", version: 2,
        checksum: "a".repeat(64) }],
    }],
  } }));
  assert.match(html, /来源 v7/);
  assert.match(html, /文件 v2/);
  assert.match(html, /requirements.txt/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /旧确认会被拒绝/);
});
