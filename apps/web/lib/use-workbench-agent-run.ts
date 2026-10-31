"use client";
import { useEffect, useRef, useState } from "react";
import { cancelWorkbenchAgentRun, workbenchAgentEventsUrl, type ConversationRequestObserver } from "./casepilot-api";
import type { AgentEvent } from "./workbench-agent-activity";
import { watchAgentStream, scopedAgentObserver, releaseAgentRun, type AgentStreamState } from "./workbench-agent-stream";
export type LiveAgentRun = { conversationId: string; requestId: string; events: AgentEvent[]; connection: AgentStreamState; cancellation: "none" | "sending" | "requested" | "already_terminal" | "failed" };

export function useWorkbenchAgentRun(conversationId: string | undefined, refresh: (id: string) => Promise<void>) {
  const [view, setView] = useState<LiveAgentRun | null>(null);
  const active = useRef<{ conversationId: string; requestId: string; close: () => void; cancelling: boolean } | null>(null);
  const previousConversation = useRef(conversationId);
  const mounted = useRef(true);
  const owner = useRef<object | null>(null);
  useEffect(() => {
    if (previousConversation.current && active.current && active.current.conversationId !== conversationId) {
      active.current.close(); active.current = null; owner.current = null;
    }
    if (previousConversation.current && previousConversation.current !== conversationId && !active.current) owner.current = null;
    previousConversation.current = conversationId;
  }, [conversationId]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; active.current?.close(); active.current = null; owner.current = null; }; }, []);
  const createObserver = (): ConversationRequestObserver => scopedAgentObserver({
    beforeStartIsCurrent: () => mounted.current && previousConversation.current === conversationId,
    ownerIsCurrent: token => mounted.current && owner.current === token,
    start(id, requestId) {
      active.current?.close();
      const run = { conversationId: id, requestId, close: () => {}, cancelling: false };
      active.current = run; owner.current = run;
      setView({ conversationId: id, requestId, events: [], connection: "connecting", cancellation: "none" });
      const update = (change: (current: LiveAgentRun) => LiveAgentRun) => {
        if (active.current !== run) return;
        setView(current => current?.requestId === requestId && current.conversationId === id ? change(current) : current);
      };
      run.close = watchAgentStream({ url: workbenchAgentEventsUrl(id, requestId),
        onEvent: event => update(current => ({ ...current, events: [...current.events, event].slice(-256) })),
        onState: connection => update(current => ({ ...current, connection })),
        onTerminal: () => { if (active.current === run) void refresh(id).catch(() => undefined); },
      });
      return { owner: run, cleanup: () => { run.close(); releaseAgentRun(active, run, () => setView(null)); } };
    },
  });
  const cancel = async () => {
    const run = active.current;
    if (!run || run.cancelling) return;
    run.cancelling = true;
    const update = (cancellation: LiveAgentRun["cancellation"]) => {
      if (active.current === run) setView(current => current?.requestId === run.requestId ? { ...current, cancellation } : current);
    };
    update("sending");
    try {
      const result = await cancelWorkbenchAgentRun(run.conversationId, run.requestId);
      if (!["requested", "already_terminal"].includes(result.status)) throw new Error("Unexpected cancellation response");
      update(result.status);
      if (result.status === "already_terminal" && active.current === run) await refresh(run.conversationId);
    } catch { update("failed"); run.cancelling = false; }
  };
  return { view: view?.conversationId === conversationId ? view : null, createObserver, cancel };
}
