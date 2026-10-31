import type { AgentEvent } from "./workbench-agent-activity";
export type AgentStreamState = "connecting" | "live" | "reconnecting" | "unavailable" | "terminal";
type Source = { addEventListener(type: string, listener: EventListener): void; removeEventListener(type: string, listener: EventListener): void; close(): void };
export const agentTerminalEvents = new Set(["run_completed", "run_awaiting_input", "run_failed", "run_cancelled"]);
const safeTypes = new Set(["run_started", "model_started", "tool_started", "tool_completed", "tool_rejected", "tool_failed", "tool_replayed", "plan_continuation", "final_correction", ...agentTerminalEvents]);
export function parseAgentStreamEvent(data: string): AgentEvent | null {
  try {
    const raw = JSON.parse(data);
    if (!raw || !Number.isSafeInteger(raw.sequence) || raw.sequence < 0 || raw.sequence > 1000 || !safeTypes.has(raw.type)) return null;
    return { sequence: raw.sequence, type: raw.type, ...(typeof raw.tool === "string" ? { tool: raw.tool.slice(0, 80) } : {}) };
  } catch { return null; }
}

/** Subscriptions never cancel the job. Request submission owns this lifecycle. */
export function watchAgentStream(input: {
  url: string; initialCursor?: number; onEvent: (event: AgentEvent) => void; onState: (state: AgentStreamState) => void;
  onTerminal: () => void; createSource?: (url: string) => Source;
  schedule?: (fn: () => void, milliseconds: number) => ReturnType<typeof setTimeout>;
  clearSchedule?: (id: ReturnType<typeof setTimeout>) => void;
}) {
  const create = input.createSource ?? (url => new EventSource(url, { withCredentials: true }));
  const schedule = input.schedule ?? setTimeout, clear = input.clearSchedule ?? clearTimeout;
  let closed = false, cursor = Number.isSafeInteger(input.initialCursor) && input.initialCursor! >= 0 && input.initialCursor! <= 1000 ? input.initialCursor! : 0, retries = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let disposeSource: (() => void) | undefined;
  const close = () => { closed = true; disposeSource?.(); if (timer !== undefined) clear(timer); };
  const connect = () => {
    if (closed) return;
    let source: Source;
    try { source = create(`${input.url}?cursor=${cursor}`); }
    catch { input.onState("unavailable"); close(); return; }
    let disconnected = false;
    const activity = (event: Event) => {
      if (closed || disconnected) return;
      const parsed = parseAgentStreamEvent((event as MessageEvent<string>).data);
      if (!parsed || parsed.sequence <= cursor) return;
      cursor = parsed.sequence;
      input.onEvent(parsed);
      if (agentTerminalEvents.has(parsed.type)) { input.onState("terminal"); close(); input.onTerminal(); }
      else input.onState("live");
    };
    const unavailable = () => { if (!closed && !disconnected) { input.onState("unavailable"); close(); } };
    const error = () => {
      if (closed || disconnected) return;
      if (retries >= 2) { unavailable(); return; }
      disposeSource?.();
      input.onState("reconnecting");
      timer = schedule(connect, 500 * 2 ** retries++);
    };
    source.addEventListener("workbench.activity", activity);
    source.addEventListener("workbench.unavailable", unavailable);
    source.addEventListener("error", error);
    disposeSource = () => {
      disconnected = true;
      source.removeEventListener("workbench.activity", activity);
      source.removeEventListener("workbench.unavailable", unavailable);
      source.removeEventListener("error", error);
      source.close();
    };
  };
  input.onState("connecting"); connect();
  return close;
}

/** Keeps request ownership after stream cleanup until navigation/new request invalidates it. */
export function scopedAgentObserver(input: {
  beforeStartIsCurrent: () => boolean;
  ownerIsCurrent: (owner: object) => boolean;
  start: (conversationId: string, requestId: string) => { owner: object; cleanup: () => void };
}) {
  let owner: object | null = null;
  return {
    isCurrent: () => owner ? input.ownerIsCurrent(owner) : input.beforeStartIsCurrent(),
    onRequest(conversationId: string, requestId: string) {
      const run = input.start(conversationId, requestId);
      owner = run.owner;
      return run.cleanup;
    },
  };
}

export function releaseAgentRun<T>(active: { current: T | null }, run: T, clearView: () => void) {
  if (active.current !== run) return false;
  active.current = null;
  clearView();
  return true;
}
