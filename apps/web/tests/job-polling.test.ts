import assert from "node:assert/strict";
import test from "node:test";

import { waitForConversationJob, watchGeneration } from "../lib/casepilot-api";

const flush = () => new Promise<void>((resolve) => setImmediate(resolve));

for (const mode of ["generation", "conversation"] as const) {
  test(`${mode}: slow polling stays bounded and recovers after a failed request`, async (t) => {
    let poll = () => {};
    let cleared = false;
    class Source extends EventTarget {
      static current: Source;
      closed = false;
      constructor() { super(); Source.current = this; }
      close() { this.closed = true; }
    }
    const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
    const previousSource = Object.getOwnPropertyDescriptor(globalThis, "EventSource");
    Object.defineProperty(globalThis, "window", { configurable: true, value: {
      performance: globalThis.performance,
      setInterval(callback: () => void) { poll = callback; return 1; },
      clearInterval() { cleared = true; },
      setTimeout() { return 2; },
      clearTimeout() {},
    } });
    Object.defineProperty(globalThis, "EventSource", { configurable: true, value: Source });
    t.after(() => {
      if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
      else Reflect.deleteProperty(globalThis, "window");
      if (previousSource) Object.defineProperty(globalThis, "EventSource", previousSource);
      else Reflect.deleteProperty(globalThis, "EventSource");
    });
    let resolveRequest!: (response: Response) => void;
    let rejectRequest!: (error: Error) => void;
    const fetch = t.mock.method(globalThis, "fetch", () => new Promise<Response>((resolve, reject) => {
      resolveRequest = resolve;
      rejectRequest = reject;
    }));
    const pending = mode === "generation"
      ? watchGeneration("job", () => {})
      : waitForConversationJob("conversation", "job");
    poll(); poll(); poll();
    assert.equal(fetch.mock.callCount(), 1);
    rejectRequest(new Error("temporary network failure"));
    await flush();
    poll(); poll();
    assert.equal(fetch.mock.callCount(), 2);
    const completed = { status: "completed", role: "assistant", related_job_id: "job" };
    resolveRequest(Response.json(mode === "generation" ? completed : { messages: [completed] }));
    await pending;
    assert.equal(cleared, true);
    assert.equal(Source.current.closed, true);
    poll();
    assert.equal(fetch.mock.callCount(), 2);
  });
}
