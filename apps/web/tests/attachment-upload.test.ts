import { test } from 'node:test';
import assert from 'node:assert/strict';
import { uploadKnowledgeFiles } from '../lib/casepilot-api';

class UploadRequest {
  static current: UploadRequest;
  upload: { onprogress?: (event: { lengthComputable: boolean; loaded: number; total: number }) => void } = {};
  status = 200;
  responseText = '{"source":{"id":"source-1"},"document_ids":["doc-1"]}';
  withCredentials = false;
  timeout = 0;
  onload?: () => void;
  onerror?: () => void;
  ontimeout?: () => void;
  onabort?: () => void;
  constructor() { UploadRequest.current = this; }
  open() {}
  send() {}
}

test('attachment upload reports real transfer progress and waits for server response', async (t) => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'XMLHttpRequest');
  Object.defineProperty(globalThis, 'XMLHttpRequest', { configurable: true, value: UploadRequest });
  t.after(() => { if (previous) Object.defineProperty(globalThis, 'XMLHttpRequest', previous); else Reflect.deleteProperty(globalThis, 'XMLHttpRequest'); });
  const progress: number[] = [];
  const pending = uploadKnowledgeFiles('space', 'attachment', [], 'temporary', n => progress.push(n));
  const request = UploadRequest.current;
  assert.equal(request.withCredentials, true);
  request.upload.onprogress?.({ lengthComputable: true, loaded: 30, total: 100 });
  assert.deepEqual(progress, [30]);
  request.onload?.();
  assert.equal((await pending).source.id, 'source-1');
  assert.deepEqual(progress, [30, 100]);
});

test('attachment upload rejects HTTP failure and timeout rather than reporting ready', async (t) => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'XMLHttpRequest');
  Object.defineProperty(globalThis, 'XMLHttpRequest', { configurable: true, value: UploadRequest });
  t.after(() => { if (previous) Object.defineProperty(globalThis, 'XMLHttpRequest', previous); else Reflect.deleteProperty(globalThis, 'XMLHttpRequest'); });
  let pending = uploadKnowledgeFiles('space', 'attachment', [], 'temporary', () => {});
  UploadRequest.current.status = 500;
  UploadRequest.current.responseText = '{"detail":"upload_failed"}';
  UploadRequest.current.onload?.();
  await assert.rejects(pending);
  pending = uploadKnowledgeFiles('space', 'attachment', [], 'temporary', () => {});
  UploadRequest.current.ontimeout?.();
  await assert.rejects(pending, /超时/);
});

test('attachment readiness checks only its own source, not the full library', async (t) => {
  const { waitForKnowledgeSource } = await import('../lib/casepilot-api');
  const original = globalThis.fetch;
  t.after(() => { globalThis.fetch = original; });
  const paths: string[] = [];
  globalThis.fetch = async (input) => {
    paths.push(String(input));
    return new Response(JSON.stringify({ id: 'source-1', space_id: 'space', status: 'ready' }), { status: 200 });
  };
  assert.equal((await waitForKnowledgeSource('space', 'source-1')).status, 'ready');
  assert.equal(paths.length, 1);
  assert.ok(paths[0].endsWith('/api/v1/knowledge-sources/source-1'));
  await assert.rejects(waitForKnowledgeSource('another-space', 'source-1'), /当前空间/);
});
