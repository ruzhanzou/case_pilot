import { parseDurableRun, type DurableRun } from "./workbench-durable-run";
export type AgentEvent = { sequence: number; type: string; tool?: string };
export type AgentReceipt = { id: string; tool: string; effect: "read" | "prepare" };
export type AgentActivity = { status: string; durable_run?: DurableRun; domain_status?: string; agent_turn_status?: string; events: AgentEvent[]; receipts: AgentReceipt[]; final: { kind: "answer" | "clarify" | "action"; effect: "none" | "read" | "prepare"; message: string; receipt_ids: string[] } | null };
export function parseAgentActivity(value: unknown): AgentActivity | null {
  if (!value || typeof value !== "object") return null;
  const input = value as Record<string, unknown>;
  if (typeof input.status !== "string" || !Array.isArray(input.events)) return null;
  const events = input.events.flatMap((raw): AgentEvent[] => {
    if (!raw || typeof raw !== "object" || !Number.isSafeInteger(raw.sequence) || typeof raw.type !== "string") return [];
    return [{ sequence: raw.sequence, type: raw.type, ...(typeof raw.tool === "string" ? {tool: raw.tool.slice(0, 80)} : {}) }];
  }).slice(0, 256);
  const receipts: AgentReceipt[] = Array.isArray(input.receipts) ? input.receipts.flatMap(raw => {
    if (!raw || typeof raw !== "object" || typeof raw.id !== "string" || typeof raw.tool !== "string" || !["read", "prepare"].includes(raw.effect)) return [];
    return [{ id: raw.id, tool: raw.tool, effect: raw.effect }];
  }) : [];
  const raw = input.final as AgentActivity["final"] | undefined;
  const final = raw && ["answer", "clarify", "action"].includes(raw.kind) && ["none", "read", "prepare"].includes(raw.effect) && typeof raw.message === "string" && Array.isArray(raw.receipt_ids)
    ? { kind: raw.kind, effect: raw.effect, message: raw.message, receipt_ids: raw.receipt_ids.filter(id => typeof id === "string") } : null;
  const durable = parseDurableRun(input.durable_run);
  return { status: input.status, ...(durable ? { durable_run: durable } : {}), ...(typeof input.domain_status === "string" ? {domain_status: input.domain_status} : {}), ...(typeof input.agent_turn_status === "string" ? {agent_turn_status: input.agent_turn_status} : {}), events, receipts, final };
}
export function verifiedAgentEffect(activity: AgentActivity): "read" | "prepare" | null {
  const final = activity.final;
  if (!final || final.kind !== "action" || final.effect === "none" || !final.receipt_ids.length) return null;
  return final.receipt_ids.every(id => activity.receipts.some(receipt => receipt.id === id && receipt.effect === final.effect)) ? final.effect : null;
}
