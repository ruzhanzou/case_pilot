export const durableStatuses = ["active", "running", "paused", "waiting_job", "waiting_approval", "completed", "failed", "cancelled", "invalidated", "budget_exhausted"] as const;
export type DurableStatus = typeof durableStatuses[number];
export const budgetKeys = ["segments", "model_turns", "tool_calls", "reserved_sdk_requests"] as const;
export type DurableRun = {
  id: string; request_id?: string; segment_sequence_base?: number; status: DurableStatus; epoch: number; cursor: number; reason?: string;
  plan: { steps: { action: string; description: string; depends_on: (string | number)[]; status: string }[] };
  budget: Partial<Record<typeof budgetKeys[number], number>>; used: Partial<Record<typeof budgetKeys[number], number>>;
};
const record = (value: unknown): Record<string, unknown> | null => value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
const nonnegative = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
export function parseDurableRun(value: unknown): DurableRun | null {
  const raw = record(value);
  const status = raw?.status === "paused_question" ? "paused" : raw?.status;
  if (!raw || typeof raw.id !== "string" || !raw.id || !durableStatuses.includes(status as DurableStatus) || !nonnegative(raw.epoch) || !nonnegative(raw.cursor)) return null;
  const plan = record(raw.plan);
  if (!plan || !Array.isArray(plan.steps) || plan.steps.length > 64 || raw.cursor > plan.steps.length) return null;
  const steps: DurableRun["plan"]["steps"] = [];
  for (const input of plan.steps) {
    const step = record(input);
    if (!step || typeof step.action !== "string" || typeof step.description !== "string" || !Array.isArray(step.depends_on)) return null;
    steps.push({ action: step.action.slice(0, 100), description: step.description.slice(0, 1000), depends_on: step.depends_on.filter((item): item is string | number => typeof item === "string" || nonnegative(item)).slice(0, 64), status: typeof step.status === "string" ? step.status.slice(0, 80) : "pending" });
  }
  const numbers = (value: unknown) => {
    const input = record(value), result: DurableRun["budget"] = {};
    for (const key of budgetKeys) if (input && nonnegative(input[key])) result[key] = input[key];
    return result;
  };
  const reason = typeof raw.reason === "string" && ["side_question_in_progress", "new_user_instruction", "new_mutating_instruction", "selection_changed", "scope_requires_selection"].includes(raw.reason) ? raw.reason : undefined;
  const requestId = typeof raw.request_id === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(raw.request_id) ? raw.request_id : undefined;
  const segmentBase = nonnegative(raw.segment_sequence_base) && raw.segment_sequence_base <= 1000 ? raw.segment_sequence_base : undefined;
  return { id: raw.id, ...(requestId && segmentBase !== undefined ? {request_id: requestId, segment_sequence_base: segmentBase} : {}), reason, status: status as DurableStatus, epoch: raw.epoch, cursor: raw.cursor, plan: { steps }, budget: numbers(raw.budget), used: numbers(raw.used) };
}
export function durableFromConversation(value: unknown): DurableRun | null {
  return parseDurableRun(record(record(record(value)?.context)?.workbench_agent)?.durable_run);
}
export function durableIsTerminal(run: DurableRun): boolean {
  return ["completed", "failed", "cancelled", "invalidated", "budget_exhausted"].includes(run.status);
}
export function acceptsDurableProjection(current: DurableRun, next: DurableRun): boolean {
  if (current.id !== next.id || next.epoch < current.epoch) return false;
  if (current.request_id && next.request_id && current.request_id !== next.request_id) return false;
  if (current.segment_sequence_base !== undefined && next.segment_sequence_base !== undefined && next.segment_sequence_base < current.segment_sequence_base) return false;
  if (next.epoch === current.epoch && next.cursor < current.cursor) return false;
  if (durableIsTerminal(current) && !durableIsTerminal(next) && next.epoch === current.epoch) return false;
  return true;
}
/** GET-only observer: no submission, approval, continuation or model invocation. */
export function watchDurableRun(input: {
  conversationId: string; initial: DurableRun;
  read: (id: string) => Promise<unknown>;
  onProjection: (run: DurableRun) => void; onConnection: (state: "live" | "reconnecting") => void;
  schedule?: typeof setTimeout; clearSchedule?: typeof clearTimeout;
}) {
  let closed = false, current = input.initial;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const schedule = input.schedule ?? setTimeout, clear = input.clearSchedule ?? clearTimeout;
  const poll = async () => {
    try {
      const conversation = await input.read(input.conversationId);
      if (closed) return;
      if (record(conversation)?.id !== input.conversationId) throw new Error("projection_owner_mismatch");
      const next = durableFromConversation(conversation);
      if (!next || !acceptsDurableProjection(current, next)) throw new Error("projection_not_current");
      current = next;
      input.onConnection("live"); input.onProjection(next);
    } catch { if (!closed) input.onConnection("reconnecting"); }
    if (!closed && !durableIsTerminal(current)) timer = schedule(() => { void poll(); }, 2500);
  };
  if (!durableIsTerminal(current)) void poll();
  return () => { closed = true; if (timer !== undefined) clear(timer); };
}
