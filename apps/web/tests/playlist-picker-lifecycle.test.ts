import assert from "node:assert/strict";
import { after, afterEach, test } from "node:test";
import { JSDOM } from "jsdom";
import type { CaseCollectionDto, PlaylistDto, TestCaseDto } from "../lib/casepilot-api";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost" });
const originalFetch = globalThis.fetch;
Object.assign(globalThis, {
  window: dom.window, document: dom.window.document,
  HTMLElement: dom.window.HTMLElement, Event: dom.window.Event,
  IS_REACT_ACT_ENVIRONMENT: true,
});
const { act, createElement } = await import("react");
const { createRoot } = await import("react-dom/client");
const { PlaylistPicker } = await import("../components/playlist-picker");
const { I18nProvider } = await import("../lib/i18n");
type Pending = { url: URL; resolve: (value: Response) => void };
let requests: Pending[] = [];
let root: ReturnType<typeof createRoot> | undefined;
let container: HTMLDivElement;
const selected: Array<PlaylistDto | null> = [];
const errors: string[] = [];
const collection = (id: string): CaseCollectionDto => ({ id, space_id: "space", name: id,
  description: "", case_count: 1, lifecycle_status: "maintenance", created_at: "2026-11-01" });
const asset = (id: string, collectionId = "A"): TestCaseDto => ({ id, case_key: id, collection_ids: [collectionId],
  current_revision_id: `${id}-v1`, revision_number: 1, title: id, module: "original", priority: "P1",
  case_type: "functional", tags: [], preconditions: [], steps: [], source: "manual", source_refs: [], created_at: "2026-11-01" });
const playlist: PlaylistDto = { id: "saved", space_id: "space", name: "Saved playlist", source_collection_ids: ["A"],
  source_collection_names: ["A"], cases: [], case_count: 0, unavailable_case_ids: [], created_at: "2026-11-01", updated_at: "2026-11-01" };
function setup() {
  requests = []; selected.length = 0; errors.length = 0;
  globalThis.fetch = (input) => new Promise<Response>((resolve) => requests.push({ url: new URL(String(input), "http://localhost"), resolve }));
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
}
async function render(requestId = 1, seedCollectionId = "") {
  await act(async () => root!.render(createElement(I18nProvider, null, createElement(PlaylistPicker, {
    spaceId: "space", collections: [collection("A"), collection("B")], seedCollectionId, requestId,
    selectedPlaylistId: "", onSelect: (value) => selected.push(value), onError: (value) => errors.push(value),
  }))));
}
function pending(path: string): Pending {
  const index = requests.findIndex((item) => item.url.pathname.endsWith(path));
  assert.notEqual(index, -1, `missing request ${path}`);
  return requests.splice(index, 1)[0];
}
async function reply(request: Pending, body: unknown, status = 200) {
  await act(async () => request.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })));
}
async function click(text: string) {
  const button = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes(text) || item.getAttribute("aria-label") === text);
  assert.ok(button, `missing button ${text}`); await act(async () => button.click());
}
async function tick() { await act(async () => { await new Promise((resolve) => setTimeout(resolve, 280)); }); }
async function query(value: string) {
  const input = container.querySelector<HTMLInputElement>('input[placeholder^="Search collection"]'); assert.ok(input);
  await act(async () => {
    Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
  });
}
afterEach(async () => { if (root) await act(async () => root!.unmount()); root = undefined; container?.remove(); });
after(() => { globalThis.fetch = originalFetch; dom.window.close(); });

test("navigation resets loading; a late old seed selection cannot overwrite the new session", async () => {
  setup(); await render(1, "A"); assert.match(container.textContent!, /Loading Playlists/);
  await reply(pending("/playlists"), []); const oldSeed = pending("/collections/A/test-cases");
  await render(2, "B"); assert.match(container.textContent!, /Loading Playlists/);
  await reply(pending("/playlists"), []); await reply(pending("/collections/B/test-cases"), [asset("B-one", "B")]);
  const count = selected.length; await reply(oldSeed, [asset("A-late")]);
  assert.equal(selected.length, count); assert.doesNotMatch(container.textContent!, /A-late/); assert.match(container.textContent!, /B-one/);
});

test("search ignores an older query and closing/reopening starts a fresh request", async () => {
  setup(); await render(); await reply(pending("/playlists"), [playlist]); await click("New Playlist");
  assert.match(container.textContent!, /Searching cases/); await tick(); const old = pending("/test-cases");
  await query("new query"); await tick(); const current = pending("/test-cases"); assert.equal(current.url.searchParams.get("q"), "new query");
  await reply(current, [asset("current-result")]); await reply(old, [asset("stale-result")]);
  assert.match(container.textContent!, /current-result/); assert.doesNotMatch(container.textContent!, /stale-result/);
  await click("Saved playlist"); assert.equal(container.querySelector(".playlist-editor"), null);
  await click("Edit Saved playlist"); assert.match(container.textContent!, /Searching cases/);
  await tick(); const reopened = pending("/test-cases"); assert.equal(reopened.url.searchParams.get("q"), "new query");
  await reply(reopened, []); assert.match(container.textContent!, /No matching cases/);
});

test("failed searches show retry, hide stale errors on retry, and unmount ignores late results", async () => {
  setup(); await render(); await reply(pending("/playlists"), []); await click("New Playlist"); await tick();
  await reply(pending("/test-cases"), { detail: "synthetic_search_failed" }, 500);
  assert.ok(container.querySelector('[role="alert"]')); await click("Retry search");
  assert.equal(container.querySelector('[role="alert"]'), null); assert.match(container.textContent!, /Searching cases/);
  await tick(); const late = pending("/test-cases"); const count = selected.length;
  await act(async () => root!.unmount()); root = undefined; await reply(late, [asset("late")]);
  assert.equal(selected.length, count); assert.equal(container.textContent, "");
});

test("switching edit targets and resetting an already open editor each trigger a fresh search", async () => {
  setup(); await render(); await reply(pending("/playlists"), [playlist, { ...playlist, id: "other", name: "Other playlist" }]);
  await click("Edit Saved playlist"); await tick(); await reply(pending("/test-cases"), [asset("first")]);
  await click("Edit Other playlist"); assert.match(container.textContent!, /Searching cases/);
  await tick(); await reply(pending("/test-cases"), [asset("second")]);
  assert.doesNotMatch(container.textContent!, /Searching cases/);
  await click("New Playlist"); await tick(); await reply(pending("/test-cases"), []);
  assert.match(container.textContent!, /No matching cases/);
  await click("New Playlist"); await tick(); await reply(pending("/test-cases"), []);
  assert.doesNotMatch(container.textContent!, /Searching cases/);
});

test("a late add-collection response cannot add old cases to a different editing target", async () => {
  setup(); await render(); await reply(pending("/playlists"), [playlist]); await click("New Playlist");
  await tick(); await reply(pending("/test-cases"), [asset("old-hit")]);
  await click("Add all"); const old = pending("/collections/A/test-cases");
  await click("Edit Saved playlist"); await reply(old, [asset("late-added")]);
  assert.doesNotMatch(container.querySelector(".playlist-selected-tree")!.textContent!, /late-added/);
  assert.match(container.querySelector(".playlist-editor")!.textContent!, /0 selected/);
});

test("a late save does not close a new editing target or replace its selection", async () => {
  const withCase = { ...playlist, cases: [{ case_id: "one", position: 0, available: true, test_case: asset("one") }], case_count: 1 };
  setup(); await render(); await reply(pending("/playlists"), [withCase]); await click("Edit Saved playlist");
  await click("Save Playlist"); const old = pending("/playlists/saved");
  await click("New Playlist"); const count = selected.length; await reply(old, { ...withCase, name: "Updated persisted playlist" });
  assert.match(container.querySelector(".playlist-saved-list")!.textContent!, /Updated persisted playlist/);
  assert.equal(selected.length, count); assert.ok(container.querySelector(".playlist-editor"));
  assert.equal(container.querySelector<HTMLInputElement>('input[placeholder^="e.g."]')!.value, "");
});

test("reusing a saved playlist invalidates a pending seed-collection editor", async () => {
  setup(); await render(1, "A"); await reply(pending("/playlists"), [playlist]);
  await click("Create from current collection"); const late = pending("/collections/A/test-cases");
  await click("Reuse"); assert.equal(selected.at(-1)?.id, playlist.id); const count = selected.length;
  await reply(late, [asset("old-seed")]); assert.equal(selected.length, count);
  assert.equal(container.querySelector(".playlist-editor"), null);
});


test("a completed delete refreshes the catalog without closing the next editor", async () => {
  setup(); dom.window.confirm = () => true;
  await render(); await reply(pending("/playlists"), [playlist, { ...playlist, id: "other", name: "Other playlist" }]);
  await click("Delete Saved playlist"); const old = pending("/playlists/saved");
  await click("Edit Other playlist"); const count = selected.length;
  await reply(old, {}); assert.equal(selected.length, count);
  assert.doesNotMatch(container.querySelector(".playlist-saved-list")!.textContent!, /Saved playlist/);
  assert.equal(container.querySelector<HTMLInputElement>('input[placeholder^="e.g."]')!.value, "Other playlist");
});
