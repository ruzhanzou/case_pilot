import { parseDurableRun, type DurableRun } from "./workbench-durable-run";
export type AgentEvent = { sequence: number; type: string; tool?: string };
export type AgentReceipt = { id: string; tool: string; effect: "read" | "plan" | "prepare" };
export type BusinessOutcome = { plan_coverage?: "not_planned" | "pending_steps" | "steps_verified"; activity: "not_executed" | "context_observed" | "read_completed" | "workspace_updated" | "planned" | "preparation_verified"; run_id: string; receipt_ids: string[]; authority: "server_tool_records" };
export type ExecutionSection = { receipt_id: string; tool: string; effect: "read" | "plan" | "prepare"; state: string };
export type AnswerSections = { actions: ExecutionSection[]; read_results: { receipt_id: string; kind: string; rows: unknown[]; truncated: boolean; has_more: boolean }[] };
export type AgentActivity = { answer_sections?: AnswerSections; business_outcome?: BusinessOutcome; status: string; durable_run?: DurableRun; domain_status?: string; agent_turn_status?: string; events: AgentEvent[]; receipts: AgentReceipt[]; final: { kind: "answer" | "clarify" | "action"; effect: "none" | "read" | "prepare"; message: string; receipt_ids: string[] } | null };
export function parseAgentActivity(value: unknown): AgentActivity | null {
  if (!value || typeof value !== "object") return null;
  const input = value as Record<string, unknown>;
  if (typeof input.status !== "string" || !Array.isArray(input.events)) return null;
  const events = input.events.flatMap((raw): AgentEvent[] => {
    if (!raw || typeof raw !== "object" || !Number.isSafeInteger(raw.sequence) || typeof raw.type !== "string") return [];
    return [{ sequence: raw.sequence, type: raw.type, ...(typeof raw.tool === "string" ? {tool: raw.tool.slice(0, 80)} : {}) }];
  }).slice(0, 256);
  const receipts: AgentReceipt[] = Array.isArray(input.receipts) ? input.receipts.flatMap(raw => {
    if (!raw || typeof raw !== "object" || typeof raw.id !== "string" || typeof raw.tool !== "string" || !["read", "plan", "prepare"].includes(raw.effect)) return [];
    return [{ id: raw.id, tool: raw.tool, effect: raw.effect }];
  }) : [];
  const raw = input.final as AgentActivity["final"] | undefined;
  const final = raw && ["answer", "clarify", "action"].includes(raw.kind) && ["none", "read", "prepare"].includes(raw.effect) && typeof raw.message === "string" && Array.isArray(raw.receipt_ids)
    ? { kind: raw.kind, effect: raw.effect, message: raw.message, receipt_ids: raw.receipt_ids.filter(id => typeof id === "string") } : null;
  const durable = parseDurableRun(input.durable_run);
  const business = input.business_outcome as BusinessOutcome | undefined;
  const businessOutcome = business && business.authority === "server_tool_records"
    && ["not_executed", "context_observed", "read_completed", "workspace_updated", "planned", "preparation_verified"].includes(business.activity)
    && typeof business.run_id === "string" && business.run_id === input.run_id
    && Array.isArray(business.receipt_ids) && business.receipt_ids.every(id => typeof id === "string" && receipts.some(receipt => receipt.id === id))
    && (business.activity !== "not_executed" || business.receipt_ids.length === 0)
    && (business.activity !== "preparation_verified" || business.receipt_ids.some(id => receipts.some(receipt => receipt.id === id && receipt.effect === "prepare")))
    ? {activity: business.activity, run_id: business.run_id, receipt_ids: [...business.receipt_ids], authority: business.authority, ...(["not_planned", "pending_steps", "steps_verified"].includes(business.plan_coverage ?? "") ? {plan_coverage: business.plan_coverage} : {})} : undefined;
  const sections = parseAnswerSections(input.answer_sections, input.run_id, receipts);
  return { status: input.status, ...(sections ? {answer_sections: sections} : {}), ...(businessOutcome ? {business_outcome: businessOutcome} : {}), ...(durable ? { durable_run: durable } : {}), ...(typeof input.domain_status === "string" ? {domain_status: input.domain_status} : {}), ...(typeof input.agent_turn_status === "string" ? {agent_turn_status: input.agent_turn_status} : {}), events, receipts, final };
}
export function verifiedAgentEffect(activity: AgentActivity): "read" | "prepare" | null {
  const final = activity.final;
  if (!final || final.kind !== "action" || final.effect === "none" || !final.receipt_ids.length) return null;
  return final.receipt_ids.every(id => activity.receipts.some(receipt => receipt.id === id && receipt.effect === final.effect)) ? final.effect : null;
}

function parseAnswerSections(value: unknown, runId: unknown, receipts: AgentReceipt[]): AnswerSections | undefined {
  if (!value || typeof value !== "object") return undefined;
  const raw = value as Record<string, unknown>;
  if (raw.version !== 1 || raw.authority !== "server_tool_records" || raw.run_id !== runId
      || typeof runId !== "string" || raw.information_authority !== "unverified_dialogue"
      || !Array.isArray(raw.actions) || !Array.isArray(raw.read_results)) return undefined;
  const namespace = typeof raw.receipt_namespace === "string" ? raw.receipt_namespace : runId;
  const actions: ExecutionSection[] = [];
  for (const item of raw.actions) {
    if (!item || typeof item !== "object") return undefined;
    const receipt = receipts.find(r => r.id === item.receipt_id && r.tool === item.tool && r.effect === item.effect);
    const allowed = item.effect === "read" ? ["read_completed"] : item.effect === "plan" ? ["plan_recorded"]
      : ["queued", "awaiting_review", "preparation_recorded", "workspace_updated", "failed", "cancelled"];
    if (!receipt || !receipt.id.startsWith(`${namespace}:`) || !allowed.includes(item.state)) return undefined;
    actions.push({receipt_id: receipt.id, tool: receipt.tool, effect: receipt.effect, state: item.state});
  }
  const read_results: AnswerSections["read_results"] = [];
  for (const item of raw.read_results) {
    if (!item || !actions.some(a => a.receipt_id === item.receipt_id && a.effect === "read")
        || !["cases", "collections"].includes(item.kind) || !Array.isArray(item.rows)
        || item.rows.length > 10000 || typeof item.truncated !== "boolean" || typeof item.has_more !== "boolean") return undefined;
    read_results.push({receipt_id: item.receipt_id, kind: item.kind, rows: item.rows,
      truncated: item.truncated, has_more: item.has_more});
  }
  return {actions, read_results};
}
