import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the CasePilot authentication shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>CasePilot — AI 测试设计工作台<\/title>/i);
  assert.match(html, /class="auth-loading"/);
  assert.match(html, /正在连接本地工作区/);
  assert.match(html, /lang="zh-CN"/);
});

test("keeps the accepted product architecture and status baseline", async () => {
  const [globalHome, prototypeApp, mindMap, mockData, css] = await Promise.all([
    readFile(new URL("../components/global-chat-home.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/prototype-app.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/mind-map.tsx", import.meta.url), "utf8"),
    readFile(new URL("../lib/mock-data.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);

  assert.match(globalHome, /想测试什么？/);
  assert.match(globalHome, /自动创建新用例集/);
  assert.match(globalHome, /\.docx.*\.pdf.*\.xlsx.*\.png/);
  assert.match(prototypeApp, /type WorkspaceView = "map" \| "list" \| "document"/);
  assert.doesNotMatch(prototypeApp, /WorkspaceView.*collections/);
  assert.match(prototypeApp, /<CaseCollections/);
  assert.match(prototypeApp, /generatedCasesToWorkspace/);
  assert.match(prototypeApp, /这个用例集还是空的/);

  assert.match(mindMap, /minZoom=\{0\.25\}/);
  assert.match(mindMap, /maxZoom=\{2\}/);
  assert.match(mindMap, /map-zoom-toolbar/);

  for (const status of ["Pending", "通过", "不通过", "跳过", "堵塞"]) {
    assert.match(mockData, new RegExp(status));
  }

  assert.match(css, /--text-body:\s*14px/);
  assert.match(css, /\.global-home/);
  assert.match(css, /\.map-zoom-toolbar/);
});
