import type { AgentEvent } from "./workbench-agent-activity";
import type { DurableRun } from "./workbench-durable-run";
import { watchAgentStream, type AgentStreamState } from "./workbench-agent-stream";
export type DurableSegmentActivity = { base: number; events: AgentEvent[]; connection: AgentStreamState };
/** Observes real SDK events only. The separate durable GET observer owns plan progress. */
export function watchDurableSegments(input: {
  conversationId: string;
  eventsUrl: (conversationId: string, requestId: string) => string;
  onActivity: (activity: DurableSegmentActivity) => void;
  subscribe?: typeof watchAgentStream;
}) {
  let closed = false, identity = "", base = -1, cursor = 0;
  let token: object | null = null, dispose: (() => void) | undefined;
  let activity: DurableSegmentActivity | null = null;
  let finished = false;
  const stop = () => { token = null; dispose?.(); dispose = undefined; };
  const publish = () => { if (!closed && activity) input.onActivity({...activity, events: [...activity.events]}); };
  return {
    update(run: DurableRun) {
      if (closed || !run.request_id || run.segment_sequence_base === undefined) { stop(); return; }
      const nextIdentity = `${run.id}:${run.request_id}`;
      if (identity && identity !== nextIdentity) { stop(); cursor = 0; base = -1; finished = false; activity = null; }
      identity = nextIdentity;
      const nextBase = run.segment_sequence_base;
      if (nextBase < base) return;
      if (run.status !== "running") { stop(); return; }
      if (nextBase !== base) {
        stop(); base = nextBase; cursor = Math.max(cursor, base); finished = false;
        activity = {base, events: [], connection: "connecting"};
        publish();
      }
      if (token || finished) return;
      const owner = {}; token = owner;
      const isCurrent = () => !closed && token === owner;
      dispose = (input.subscribe ?? watchAgentStream)({
        url: input.eventsUrl(input.conversationId, run.request_id), initialCursor: Math.max(cursor, base),
        onEvent: event => {
          if (!isCurrent() || event.sequence <= cursor || event.sequence <= base) return;
          cursor = event.sequence;
          // A genuine new segment begins afresh; never carry an old terminal badge forward.
          if (event.type === "run_started") activity = {base, events: [], connection: "live"};
          activity = {base, events: [...(activity?.events ?? []), event].slice(-256), connection: activity?.connection ?? "live"};
          publish();
        },
        onState: connection => { if (isCurrent() && activity) { activity = {...activity, connection}; publish(); } },
        onTerminal: () => { if (isCurrent()) { finished = true; token = null; } },
      });
    },
    close() { closed = true; stop(); },
  };
}
