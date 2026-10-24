import type { ConversationDto, ConversationMessageDto, ConversationOperationDto, ConversationWorkflowRunDto, TestCaseDto, WorkspaceCandidateDto } from "./casepilot-api";

export type WorkspaceTask = {
  id: string;
  messageIds: string[];
  message: ConversationMessageDto;
  request?: ConversationMessageDto;
  workflow?: ConversationWorkflowRunDto;
  operation?: ConversationOperationDto;
  status: string;
  sourceTaskId?: string;
  groupId?: string;
  waitingOn?: string;
  versions?: WorkspaceTask[];
};

/** Assignment values must not be inferred as existing case selections. */
export function scopeReferenceText(instruction: string): string {
  return instruction
    .replace(/(?:标题|名称|描述|所属模块|模块|用例类型|类型|前置条件|步骤|预期结果|校验点)\s*(?:统一|全部)?\s*(?:改为|改成|修改为|调整为|设置为|设为|替换为|更新为|补充为)\s*(?:「[^」]*」|“[^”]*”|"[^"]*")/g, "")
    .replace(/(?:标题|名称|描述|标签|前置条件|步骤|预期结果|预期)(?:中|里|内)?(?:不包含|不含|包含|含有|含)\s*(?:「[^」]+」|“[^”]+”|"[^"]+"|[^，,。；;\n「」“”"]+?(?=的?(?:正式|候选|测试)?用例))/g, "");
}

export function workspaceTasks(conversation: ConversationDto | null): WorkspaceTask[] {
  if (!conversation) return [];
  const operations = conversation.operation_history ?? conversation.operation_plan?.operations ?? [];
  const tasks: WorkspaceTask[] = operations.filter((op) => op.intent !== "SMALL_TALK").map((operation) => {
    const groupId = operation.source_message_id ?? conversation.operation_plan?.source_message_id ?? undefined;
    const request = conversation.messages.find((item) => item.id === groupId);
    const workflow = conversation.workflow_runs.find((run) => run.job_id === operation.related_job_id);
    return {
      id: operation.id, messageIds: [], operation, workflow, request, groupId,
      sourceTaskId: String(operation.payload.source_operation_id ?? "") || undefined,
      status: operation.status,
      message: {
        id: operation.id, role: "assistant", intent: operation.intent, intent_confidence: operation.confidence,
        status: "completed", content: "", citations: [], target_case_ids: [],
        related_job_id: operation.related_job_id, metadata: {}, created_at: operation.created_at,
      },
    };
  });
  let request: ConversationMessageDto | undefined;
  for (const message of conversation.messages) {
    if (message.role === "user") { request = message; continue; }
    if (!message.intent || message.intent === "SMALL_TALK") continue;
    const workflow = conversation.workflow_runs.find((run) => run.message_id === message.id);
    const brief = conversation.test_briefs.find((item) => item.version === Number(message.metadata.brief_version));
    const operationId = message.metadata.operation_id ?? brief?.source_operation_id;
    const existing = tasks.find((task) =>
      (operationId && task.operation?.id === operationId) ||
      (message.metadata.change_set_id && (task.operation?.related_change_set_id === message.metadata.change_set_id || task.message.metadata.change_set_id === message.metadata.change_set_id)) ||
      (message.related_job_id && (task.operation?.related_job_id === message.related_job_id || task.message.related_job_id === message.related_job_id)) ||
      (operationId && task.message.metadata.operation_id === operationId));
    const status = message.status.startsWith("awaiting_") ? message.status : workflow?.status ?? message.status;
    if (existing) {
      existing.messageIds.push(message.id);
      existing.message = { ...message, metadata: { ...existing.message.metadata, ...message.metadata } };
      existing.request ??= request;
      existing.workflow = workflow ?? existing.workflow;
      if (!existing.operation) existing.status = status;
    } else {
      tasks.push({ id: message.id, messageIds: [message.id], message, request, workflow, status });
    }
  }
  for (const task of tasks) {
    if (task.operation) {
      const op = task.operation;
      if (op.result.change_set_status === "conflict") task.status = "conflict";
      task.message.metadata = {
        ...task.message.metadata,
        ...(op.result.analysis_report ? { analysis_report: op.result.analysis_report } : {}),
        ...(op.related_change_set_id ? { change_set_id: op.related_change_set_id } : {}),
      };
      const predecessor = tasks.find((item) => item.groupId && item.groupId === task.groupId && item.operation?.sequence === op.sequence - 1);
      if (op.status === "queued" && predecessor && !["completed", "skipped"].includes(predecessor.status)) task.waitingOn = predecessor.id;
      if (op.result.superseded_by) task.status = "superseded";
      else if (task.message.metadata.action === "rejected" || (op.status === "cancelled" && (op.related_change_set_id || op.result.discarded))) task.status = "not_applied";
    }
  }
  // A rewrite operation records one round; its source chain is one user task.
  const byId = new Map(tasks.map(task => [task.id, task]));
  const rootId = (task: WorkspaceTask): string => {
    if (task.operation?.payload.task_id) return String(task.operation.payload.task_id);
    const visited = new Set<string>();
    let current = task;
    while (current.message.intent === "CASE_MODIFY" && current.sourceTaskId && !visited.has(current.id)) {
      visited.add(current.id);
      const source = byId.get(current.sourceTaskId);
      if (!source || source.message.intent !== "CASE_MODIFY") break;
      current = source;
    }
    return String(current.operation?.payload.task_id ?? current.id);
  };
  const groups = new Map<string, WorkspaceTask[]>();
  for (const task of tasks) {
    const id = ["CASE_MODIFY", "CASE_GENERATE"].includes(task.message.intent ?? "") ? rootId(task) : task.id;
    groups.set(id, [...(groups.get(id) ?? []), task]);
  }
  const merged = [...groups.entries()].map(([id, rounds]) => {
    if (rounds.length === 1) return { ...rounds[0], id };
    // Source links, rather than timestamps alone, order rounds saved within one millisecond.
    const depth = (task: WorkspaceTask) => {
      let n = 0; const seen = new Set<string>(); let source = task.sourceTaskId;
      while (source && byId.has(source) && !seen.has(source)) {
        seen.add(source); n++; source = byId.get(source)?.sourceTaskId;
      }
      return n;
    };
    rounds.sort((a, b) => depth(a) - depth(b) || (a.operation?.created_at ?? "").localeCompare(b.operation?.created_at ?? ""));
    const latest = rounds[rounds.length - 1];
    return { ...latest, id, versions: rounds, sourceTaskId: rounds[0].sourceTaskId,
      messageIds: rounds.flatMap(round => round.messageIds) };
  });
  const activeId = String(conversation.context.active_mutation_task_id ?? "");
  for (const task of merged) {
    if (task.id === activeId && task.status === "completed") task.status = "awaiting_confirmation";
    if (task.operation?.result.task_closed && task.versions?.some(round => (round.operation?.result.test_case_ids as string[] | undefined)?.length)) task.status = "completed";
  }
  return merged.reverse().sort((a, b) => (b.operation?.created_at ?? b.message.created_at ?? "").localeCompare(a.operation?.created_at ?? a.message.created_at ?? "") || (b.operation?.sequence ?? 0) - (a.operation?.sequence ?? 0));
}

// Reads can straddle a worker commit: the job is already terminal while the
// operation snapshot still says running. Keep observing until both agree.
export function workspaceJobNeedsWatch(conversation: ConversationDto | null, jobId: string) {
  if (!conversation || !jobId) return false;
  const run = conversation.workflow_runs.find(item => item.job_id === jobId);
  const operationRunning = (conversation.operation_history ?? conversation.operation_plan?.operations ?? [])
    .some(item => item.related_job_id === jobId && item.status === "running");
  return operationRunning || !run || !["completed", "failed", "cancelled"].includes(run.status);
}

export function workspaceIsRunning(conversation: ConversationDto | null) {
  return Boolean(conversation?.workflow_runs.some((run) => ["queued", "running"].includes(run.status)) ||
    (conversation?.operation_history ?? conversation?.operation_plan?.operations)?.some((operation) => operation.status === "running"));
}

export function taskScopeChanged(task: WorkspaceTask | undefined, cases: TestCaseDto[]) {
  const versions = task?.operation?.result.scope_versions as Record<string, string> | undefined;
  if (!versions) return false;
  const current = new Map(cases.map((item) => [item.id, item.current_revision_id]));
  const deletedByTask = new Set(task?.operation?.intent === "CASE_DELETE"
    ? task.operation.result.updated_refs as string[] | undefined : []);
  return Object.entries(versions).some(([id, version]) =>
    !(deletedByTask.has(id) && !current.has(id)) && current.get(id) !== version);
}

export function candidatesForTask(task: WorkspaceTask | undefined, conversation: ConversationDto | null): WorkspaceCandidateDto[] {
  if (!task || !conversation) return [];
  const generation = task.message.intent === "CASE_GENERATE" ? task : task.versions?.findLast(round => round.operation?.intent === "CASE_GENERATE");
  if (!generation) return [];
  const candidates = conversation.candidate_history ?? conversation.candidates;
  const ids = new Set(generation.operation?.result.candidate_ids as string[] ?? []);
  const messageIds = new Set(generation.messageIds);
  const jobIds = new Set([
    generation.operation?.related_job_id ?? generation.message.related_job_id,
    ...conversation.messages.filter(message => messageIds.has(message.id) && message.intent === "CASE_GENERATE")
      .map(message => message.related_job_id),
  ].filter(Boolean));
  return candidates.filter(candidate => ids.has(candidate.id) || (candidate.generation_job_id && jobIds.has(candidate.generation_job_id)))
    .sort((left, right) => left.position - right.position || left.version - right.version);
}

export function nextWorkspaceOperation(conversation: ConversationDto | null) {
  const operations = conversation?.operation_plan?.operations ?? [];
  return operations.find((operation) => operation.status === "queued" && operations
    .filter((item) => item.sequence < operation.sequence)
    .every((item) => ["completed", "skipped"].includes(item.status)));
}
