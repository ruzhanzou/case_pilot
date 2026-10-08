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
};

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
  return tasks.reverse().sort((a, b) => (b.operation?.created_at ?? b.message.created_at ?? "").localeCompare(a.operation?.created_at ?? a.message.created_at ?? "") || (b.operation?.sequence ?? 0) - (a.operation?.sequence ?? 0));
}

export function workspaceIsRunning(conversation: ConversationDto | null) {
  return Boolean(conversation?.workflow_runs.some((run) => ["queued", "running"].includes(run.status)) ||
    (conversation?.operation_history ?? conversation?.operation_plan?.operations)?.some((operation) => operation.status === "running"));
}

export function taskScopeChanged(task: WorkspaceTask | undefined, cases: TestCaseDto[]) {
  const versions = task?.operation?.result.scope_versions as Record<string, string> | undefined;
  if (!versions) return false;
  const current = new Map(cases.map((item) => [item.id, item.current_revision_id]));
  return Object.entries(versions).some(([id, version]) => current.get(id) !== version);
}

export function candidatesForTask(task: WorkspaceTask | undefined, conversation: ConversationDto | null): WorkspaceCandidateDto[] {
  if (!task || task.message.intent !== "CASE_GENERATE" || !conversation) return [];
  const candidates = conversation.candidate_history ?? conversation.candidates;
  const ids = new Set(task.operation?.result.candidate_ids as string[] ?? []);
  return candidates.filter((candidate) => ids.has(candidate.id) || (candidate.generation_job_id && candidate.generation_job_id === task.operation?.related_job_id));
}

export function nextWorkspaceOperation(conversation: ConversationDto | null) {
  const operations = conversation?.operation_plan?.operations ?? [];
  return operations.find((operation) => operation.status === "queued" && operations
    .filter((item) => item.sequence < operation.sequence)
    .every((item) => ["completed", "skipped"].includes(item.status)));
}

/** Keep clarifications on their task, but do not swallow an explicit new action. */
export function shouldResumePendingTask(intent: string, content: string): boolean {
  if (/(?:然后|随后|接着|再|\bthen\b)\s*(?:查询|查找|修改|改写|生成|删除|检查|query\b|find\b|modify\b|generate\b|delete\b)/i.test(content)) return false;
  const command = content.trim().replace(/^(?:(?:请|帮我|麻烦|please)\s*)+/i, "");
  const explicitIntents: [RegExp, string][] = [
    [/^(?:修改|改写|调整|替换|modify\b|edit\b|rewrite\b)/i, "CASE_MODIFY"],
    [/^(?:删除|移除|delete\b|remove\b)/i, "CASE_DELETE"],
    [/^(?:查询|查找|搜索|列出|query\b|find\b|search\b|list\b)/i, "CASE_QUERY"],
    [/^(?:生成|新增|创建|编写|generate\b|create\b|write\b)/i, "CASE_GENERATE"],
    [/^(?:查重|检查重复|检查冗余|dedup\b)/i, "CASE_DEDUP"],
    [/^(?:评审|审阅|review\b|audit\b)/i, "CASE_REVIEW"],
    [/^(?:分析覆盖|检查遗漏|检查覆盖)/i, "COVERAGE_ANALYZE"],
    [/^(?:解释|什么是|如何|为什么|explain\b|what\b|how\b)/i, "KNOWLEDGE_QA"],
    [/^(?:你好|谢谢|hello\b|thanks\b)/i, "SMALL_TALK"],
  ];
  const nextIntent = explicitIntents.find(([pattern]) => pattern.test(command))?.[1];
  return !nextIntent || nextIntent === intent;
}

/** Only implicit mutation commands may reuse a previous single-case selection. */
export function requestsImplicitMutation(content: string): boolean {
  const positive = content.replace(/(?:不|不要|无需|禁止|暂不)\s*(?:修改|改写|调整|替换|删除|移除)/g, "")
    .replace(/(?:do\s+not|don't|without)\s+(?:modify|edit|rewrite|delete|remove)(?:ing)?/gi, "");
  return /(?:修改|改写|调整|替换|改成|改为|删除|移除|\b(?:edit|modify|rewrite|delete|remove)\b)/i.test(positive);
}
