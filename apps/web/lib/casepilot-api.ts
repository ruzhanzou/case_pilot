const configuredApiBaseUrl =
  process.env.NEXT_PUBLIC_CASEPILOT_API_URL ?? "http://localhost:8000";

function resolveApiBaseUrl(): string {
  if (typeof window === "undefined") return configuredApiBaseUrl;
  try {
    const url = new URL(configuredApiBaseUrl);
    const loopbackHosts = new Set(["localhost", "127.0.0.1", "::1", "[::1]"]);
    if (
      loopbackHosts.has(url.hostname) &&
      loopbackHosts.has(window.location.hostname)
    ) {
      url.hostname = window.location.hostname;
    }
    return url.toString().replace(/\/$/, "");
  } catch {
    return configuredApiBaseUrl.replace(/\/$/, "");
  }
}

const apiBaseUrl = resolveApiBaseUrl();

export type Account = {
  id: string;
  email: string;
  display_name: string;
  spaces: {
    id: string;
    name: string;
    description: string;
    role: string;
  }[];
};

export type ExecutionStatusApi =
  | "not_run"
  | "passed"
  | "failed"
  | "skipped"
  | "blocked";

export type CaseStepDto = {
  id: string;
  action: string;
  expected: string;
};

export type CaseCollectionDto = {
  id: string;
  space_id: string;
  name: string;
  description: string;
  case_count: number;
  created_at: string;
};

export type TestCaseDto = {
  id: string;
  case_key: string;
  collection_ids: string[];
  current_revision_id: string;
  revision_number: number;
  title: string;
  module: string;
  priority: "P0" | "P1" | "P2";
  case_type: string;
  tags: string[];
  preconditions: string[];
  steps: CaseStepDto[];
  source: string;
  created_at: string;
};

export type TestCaseInput = {
  case_key?: string;
  title: string;
  module: string;
  priority: "P0" | "P1" | "P2";
  case_type: string;
  tags: string[];
  preconditions: string[];
  steps: {
    id?: string;
    action: string;
    expected: string;
  }[];
  source: string;
  source_refs?: SourceRefDto[];
};

export type AgentModelId = string;

export type GenerationModelDto = {
  id: AgentModelId;
  label: string;
  provider: string;
};

export type GenerationModelsDto = {
  default_model_id: AgentModelId;
  models: GenerationModelDto[];
};

export type SourceRefDto = {
  source_id?: string | null;
  document_id?: string | null;
  chunk_id?: string | null;
  label: string;
  locator?: string;
  excerpt: string;
};

export type AgentTestCaseDraft = {
  id: string;
  title: string;
  module: string;
  case_type: string;
  priority: "P0" | "P1" | "P2";
  tags: string[];
  status: string;
  preconditions: string[];
  steps: {
    action: string;
    expected: string;
  }[];
  source_refs: SourceRefDto[];
};

export type GenerationCompleted = {
  case_ids: string[];
  requirement: {
    summary: string;
    open_questions: {
      id: string;
      question: string;
      impact: string;
    }[];
  };
  feature_points: { id: string; name: string }[];
  test_points: { id: string; title: string }[];
  test_cases: AgentTestCaseDraft[];
  quality: {
    passed: boolean;
    score: number;
    issues: { message: string }[];
  };
  model_metadata: {
    provider?: string;
    model?: string;
  };
  coverage_matrix: Record<string, unknown>[];
  source_refs: SourceRefDto[];
};

export type GenerationQuestion = {
  id: string;
  question: string;
  impact: string;
  blocking: boolean;
};

export type GenerationJobDetail = GenerationCompleted & {
  id: string;
  status:
    | "queued"
    | "running"
    | "awaiting_input"
    | "completed"
    | "failed"
    | "cancelled";
  stage: string;
  space_id: string;
  progress: number;
  error_code: string | null;
  questions: GenerationQuestion[];
  stages: {
    stage: string;
    attempt: number;
    status: string;
    model: string;
    latency_ms: number;
  }[];
};

export type KnowledgeDocumentDto = {
  id: string;
  source_id: string;
  original_name: string;
  mime_type: string;
  size_bytes: number;
  version: number;
  status: string;
  error_code: string | null;
  expires_at: string | null;
  created_at: string;
};

export type KnowledgeSourceDto = {
  id: string;
  space_id: string;
  name: string;
  kind: string;
  persistence: "space" | "temporary";
  status: string;
  error_code: string | null;
  document_count: number;
  documents: KnowledgeDocumentDto[];
  created_at: string;
};

export type GenerationStage = {
  name: string;
  progress: number;
  count?: number;
};

export type ConversationIntent =
  | "CASE_GENERATE"
  | "CASE_MODIFY"
  | "CASE_DELETE"
  | "CASE_QUERY"
  | "KNOWLEDGE_QA"
  | "SMALL_TALK";

export type ConversationMessageDto = {
  id: string;
  role: "user" | "assistant";
  content: string;
  intent: ConversationIntent | null;
  intent_confidence: number | null;
  status:
    | "completed"
    | "running"
    | "failed"
    | "cancelled"
    | "awaiting_intent"
    | "awaiting_clarification"
    | "awaiting_confirmation";
  target_case_ids: string[];
  related_job_id: string | null;
  citations: SourceRefDto[];
  metadata: Record<string, unknown>;
  created_at: string;
};

export type ConversationDto = {
  id: string;
  space_id: string;
  collection_id: string;
  title: string;
  status: string;
  context: Record<string, unknown>;
  messages: ConversationMessageDto[];
  test_briefs: WorkspaceTestBriefDto[];
  candidates: WorkspaceCandidateDto[];
  workflow_runs: ConversationWorkflowRunDto[];
  created_at: string;
  updated_at: string;
};

export type ConversationWorkflowStageDto = {
  stage: string;
  attempt: number;
  status: string;
  progress: number;
  model: string;
  latency_ms: number;
  created_at: string;
};

export type ConversationWorkflowRunDto = {
  job_id: string;
  message_id: string;
  operation: string;
  status: GenerationJobDetail["status"];
  current_stage: string;
  progress: number;
  error_code: string | null;
  stages: ConversationWorkflowStageDto[];
  created_at: string;
  updated_at: string;
};

export type ConversationSummaryDto = {
  id: string;
  collection_id: string;
  title: string;
  collection_name: string;
  phase: string;
  last_message_preview: string;
  created_at: string;
  updated_at: string;
};

export type ConversationHistoryPageDto = {
  items: ConversationSummaryDto[];
  next_cursor: string | null;
};

export type TestBriefContentDto = {
  test_object: string;
  test_objective: string;
  scope: string[];
  roles: string[];
  core_flows: string[];
  business_rules: string[];
  constraints: string[];
  risks: string[];
  coverage_dimensions: string[];
  assumptions: string[];
  open_questions: {
    id?: string;
    question: string;
    impact?: string;
    blocking?: boolean;
  }[];
};

export type WorkspaceTestBriefDto = {
  id: string;
  version: number;
  content: TestBriefContentDto;
  markdown_content: string;
  status: "draft" | "confirmed" | "superseded";
  confirmed_at: string | null;
  created_at: string;
};

export type WorkspaceCandidateDto = {
  id: string;
  generation_job_id: string | null;
  ref: string;
  version: number;
  position: number;
  snapshot: AgentTestCaseDraft;
  included: boolean;
  status: string;
  updated_at: string;
};

export type ConversationTargetSnapshot = {
  ref: string;
  version: number;
  snapshot: Record<string, unknown>;
};

export type ConversationTurnDto = {
  conversation_id: string;
  user_message: ConversationMessageDto;
  assistant_message: ConversationMessageDto | null;
  intent: ConversationIntent;
  intent_confidence: number;
  requires_intent_confirmation: boolean;
  action: {
    type?:
      | "generation"
      | "test_brief"
      | "knowledge_qa"
      | "change_set"
      | "case_query"
      | "small_talk"
      | "clarification";
    job_id?: string;
    change_set_id?: string;
  };
};

export type CaseChangeItemDto = {
  ref: string;
  target_type: "candidate" | "formal";
  test_case_id?: string;
  base_revision_id?: string;
  candidate_revision_id?: string;
  base_version?: number;
  base_snapshot: Record<string, unknown>;
  proposed_snapshot: Record<string, unknown>;
  applied_snapshot?: Record<string, unknown>;
  field_diff: {
    field: string;
    before: unknown;
    after: unknown;
  }[];
  reason: string;
  status: string;
};

export type CaseChangeSetDto = {
  id: string;
  conversation_id: string;
  generation_job_id: string | null;
  instruction: string;
  scope: string;
  status: "generating" | "ready" | "applied" | "rejected" | "conflict" | "failed";
  items: CaseChangeItemDto[];
  created_at: string;
  applied_at: string | null;
};

export type CaseChangeSetApplyDto = {
  change_set: CaseChangeSetDto;
  test_cases: TestCaseDto[];
  candidate_snapshots: ConversationTargetSnapshot[];
};

export type ExecutionRecordDto = {
  id: string;
  test_case: TestCaseDto;
  status: ExecutionStatusApi;
  completed_step_ids: string[];
  actual_result: string;
  defect_ref: string;
  assignee_id: string | null;
  assignee_name: string | null;
  can_edit: boolean;
  updated_by_name: string | null;
  updated_at: string;
};

export type ExecutionRunDto = {
  id: string;
  collection_id: string;
  collection_name: string;
  description: string;
  status: string;
  creator_name: string;
  creator_id: string;
  assignee_ids: string[];
  assignee_names: string[];
  can_manage: boolean;
  contributor_names: string[];
  created_at: string;
  last_activity_at: string;
  completed_at: string | null;
  records: ExecutionRecordDto[];
};

export type SpaceMemberDto = {
  account_id: string;
  email: string;
  display_name: string;
  role: "owner" | "member";
  created_at: string;
};

export type ExecutionRunSummaryDto = Omit<
  ExecutionRunDto,
  "records" | "creator_id" | "can_manage"
> & {
  total_count: number;
  not_run_count: number;
  passed_count: number;
  failed_count: number;
  skipped_count: number;
  blocked_count: number;
};

const publicErrors: Record<string, string> = {
  provider_temporarily_unavailable: "模型服务暂时不可用，请稍后重试。",
  provider_response_invalid: "模型返回内容暂时无法解析，请重试或更换模型。",
  generation_quality_blocked: "生成内容未通过质量检查，请补充需求后重试。",
  generation_failed: "处理暂时未完成，请稍后重试。",
  ProviderResponseError: "模型返回内容暂时无法解析，请重试或更换模型。",
  TimeoutError: "模型响应超时，请稍后重试。",
  ConnectionError: "网络连接中断，请检查网络后重试。",
  test_brief_has_blocking_questions: "仍有阻塞待确认项，请先补充说明。",
  test_brief_version_changed: "测试说明已更新，请确认最新版本。",
  workspace_generation_in_progress: "当前工作区已经在生成，请勿重复提交。",
  generation_job_already_terminal: "当前生成任务已经结束。",
  invalid_history_cursor: "历史对话分页状态已失效，请刷新后重试。",
  invalid_execution_step: "执行步骤状态已变化，请刷新后重试。",
  execution_result_reason_required: "请填写本次执行结果的原因或实际情况。",
  execution_record_changed: "该用例刚被其他成员更新，请确认最新结果后重试。",
  execution_run_has_no_cases: "空用例集合不能创建执行任务。",
  execution_run_assignees_required: "请至少选择一名执行人。",
  execution_record_not_assignee: "只有当前执行人可以修改这条执行结果。",
};

export function publicErrorMessage(code: string): string {
  return (
    publicErrors[code] ??
    (code.startsWith("api_request_failed_")
      ? "服务请求失败，请稍后重试。"
      : /[\u3400-\u9fff]/u.test(code)
        ? code
        : "操作暂时未完成，请稍后重试。")
  );
}

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = init?.body instanceof FormData;
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new Error(
      publicErrorMessage(
        payload?.detail ?? `api_request_failed_${response.status}`,
      ),
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function startGeneration(input: {
  prompt: string;
  fileNames: string[];
  collectionId: string;
  modelId: AgentModelId;
  documentIds?: string[];
  knowledgeSourceIds?: string[];
  useSpaceKnowledge?: boolean;
}): Promise<GenerationJobDetail> {
  return apiRequest("/api/v1/generation-jobs", {
    method: "POST",
    body: JSON.stringify({
      prompt: input.prompt,
      markdown_content: input.prompt,
      file_names: input.fileNames,
      collection_id: input.collectionId,
      model_id: input.modelId,
      document_ids: input.documentIds ?? [],
      knowledge_source_ids: input.knowledgeSourceIds ?? [],
      use_space_knowledge: input.useSpaceKnowledge ?? true,
    }),
  });
}

export function listGenerationModels(): Promise<GenerationModelsDto> {
  return apiRequest("/api/v1/generation-models");
}

export function watchGeneration(
  jobId: string,
  onStage: (stage: GenerationStage) => void,
): Promise<GenerationJobDetail> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const source = new EventSource(
      `${apiBaseUrl}/api/v1/generation-jobs/${jobId}/events`,
      { withCredentials: true },
    );
    const timeout = window.setTimeout(() => {
      finish(() => reject(new Error("AI 生成超时，请稍后重试")));
    }, 900_000);
    const poll = window.setInterval(() => {
      void getGeneration(jobId)
        .then((job) => {
          if (job.status === "completed" || job.status === "awaiting_input") {
            finish(() => resolve(job));
          } else if (job.status === "cancelled") {
            finish(() => resolve(job));
          } else if (job.status === "failed") {
            finish(() =>
              reject(
                new Error(
                  publicErrorMessage(job.error_code ?? "generation_failed"),
                ),
              ),
            );
          }
        })
        .catch(() => {
          // SSE remains the primary channel; transient polling failures are ignored.
        });
    }, 3_000);
    const close = () => {
      window.clearTimeout(timeout);
      window.clearInterval(poll);
      source.close();
    };
    const finish = (callback: () => void) => {
      if (settled) return;
      settled = true;
      close();
      callback();
    };
    const handleStage = (event: Event) => {
      const payload = JSON.parse(
        (event as MessageEvent<string>).data,
      ) as Omit<GenerationStage, "name">;
      onStage({
        name: event.type,
        progress: payload.progress ?? 0,
        count: payload.count,
      });
    };
    [
      "context.prepared",
      "requirement.analyzed",
      "feature.generated",
      "test_point.generated",
      "test_case.generated",
      "enhancement.completed",
      "quality.completed",
    ].forEach((eventName) => source.addEventListener(eventName, handleStage));
    source.addEventListener("generation.completed", () => {
      finish(() => {
        void getGeneration(jobId).then(resolve, reject);
      });
    });
    source.addEventListener("generation.awaiting_input", () => {
      finish(() => {
        void getGeneration(jobId).then(resolve, reject);
      });
    });
    source.addEventListener("generation.failed", (event) => {
      const payload = JSON.parse(
        (event as MessageEvent<string>).data,
      ) as { error_code?: string };
      finish(() =>
        reject(
          new Error(
            publicErrorMessage(payload.error_code ?? "generation_failed"),
          ),
        ),
      );
    });
    source.addEventListener("generation.cancelled", () => {
      finish(() => {
        void getGeneration(jobId).then(resolve, reject);
      });
    });
    source.onerror = () => {
      source.close();
    };
  });
}

export function getGeneration(jobId: string): Promise<GenerationJobDetail> {
  return apiRequest(`/api/v1/generation-jobs/${jobId}`);
}

export function answerGeneration(
  jobId: string,
  answers: { question_id: string; answer: string }[],
): Promise<GenerationJobDetail> {
  return apiRequest(`/api/v1/generation-jobs/${jobId}/answers`, {
    method: "POST",
    body: JSON.stringify({ answers }),
  });
}

export function retryGeneration(jobId: string): Promise<GenerationJobDetail> {
  return apiRequest(`/api/v1/generation-jobs/${jobId}/retry`, {
    method: "POST",
  });
}

export function cancelGeneration(jobId: string): Promise<GenerationJobDetail> {
  return apiRequest(`/api/v1/generation-jobs/${jobId}/cancel`, {
    method: "POST",
  });
}

export function createConversation(input: {
  collectionId: string;
  title?: string;
  knowledgeSourceIds?: string[];
  documentIds?: string[];
  useSpaceKnowledge?: boolean;
}): Promise<ConversationDto> {
  return apiRequest("/api/v1/conversations", {
    method: "POST",
    body: JSON.stringify({
      collection_id: input.collectionId,
      title: input.title ?? "AI 用例工作台对话",
      knowledge_source_ids: input.knowledgeSourceIds ?? [],
      document_ids: input.documentIds ?? [],
      use_space_knowledge: input.useSpaceKnowledge ?? true,
    }),
  });
}

export function getLatestConversation(
  collectionId: string,
): Promise<ConversationDto> {
  return apiRequest(
    `/api/v1/collections/${collectionId}/conversations/latest`,
  );
}

export function getOrCreateWorkspace(
  collectionId: string,
): Promise<ConversationDto> {
  return apiRequest(`/api/v1/collections/${collectionId}/workspace`, {
    method: "PUT",
  });
}

export function listConversationHistory(input?: {
  query?: string;
  cursor?: string;
  limit?: number;
}): Promise<ConversationHistoryPageDto> {
  const parameters = new URLSearchParams();
  if (input?.query) parameters.set("q", input.query);
  if (input?.cursor) parameters.set("cursor", input.cursor);
  parameters.set("limit", String(input?.limit ?? 30));
  return apiRequest(`/api/v1/conversations/history?${parameters.toString()}`);
}

export function updateWorkspaceState(
  conversationId: string,
  input: {
    draft_text?: string;
    selected_case_id?: string | null;
    active_view?: "list" | "map";
    search_query?: string;
    filters?: Record<string, unknown>;
    chat_width?: number;
    inspector_width?: number;
    selected_brief_version?: number;
  },
): Promise<ConversationDto> {
  return apiRequest(`/api/v1/workspaces/${conversationId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export async function downloadTestBrief(
  conversationId: string,
  version: number,
): Promise<Blob> {
  const response = await fetch(
    `${apiBaseUrl}/api/v1/workspaces/${conversationId}/test-briefs/${version}/download`,
    { credentials: "include" },
  );
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new Error(
      publicErrorMessage(
        payload?.detail ?? `api_request_failed_${response.status}`,
      ),
    );
  }
  return response.blob();
}

export function saveTestBrief(
  conversationId: string,
  content: TestBriefContentDto,
): Promise<WorkspaceTestBriefDto> {
  return apiRequest(`/api/v1/workspaces/${conversationId}/test-briefs`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

export function confirmTestBrief(
  conversationId: string,
  version: number,
  modelId: AgentModelId,
): Promise<ConversationTurnDto> {
  return apiRequest(
    `/api/v1/workspaces/${conversationId}/test-briefs/confirm`,
    {
      method: "POST",
      body: JSON.stringify({ version, model_id: modelId }),
    },
  );
}

export function updateWorkspaceCandidate(
  candidateId: string,
  input: {
    snapshot?: Record<string, unknown>;
    included?: boolean;
  },
): Promise<WorkspaceCandidateDto> {
  return apiRequest(`/api/v1/workspace-candidates/${candidateId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function commitWorkspaceCandidates(
  conversationId: string,
  candidateIds: string[] = [],
): Promise<TestCaseDto[]> {
  return apiRequest(
    `/api/v1/workspaces/${conversationId}/candidates/commit`,
    {
      method: "POST",
      body: JSON.stringify({ candidate_ids: candidateIds }),
    },
  );
}

export function getConversation(
  conversationId: string,
): Promise<ConversationDto> {
  return apiRequest(`/api/v1/conversations/${conversationId}`);
}

export function sendConversationMessage(
  conversationId: string,
  input: {
    content: string;
    modelId: AgentModelId;
    scope: "current" | "module";
    targetCaseIds?: string[];
    targetCandidateSnapshots?: ConversationTargetSnapshot[];
    knowledgeSourceIds?: string[];
    documentIds?: string[];
    useSpaceKnowledge?: boolean;
    intentOverride?: ConversationIntent;
  },
): Promise<ConversationTurnDto> {
  return apiRequest(`/api/v1/conversations/${conversationId}/messages`, {
    method: "POST",
    body: JSON.stringify({
      content: input.content,
      model_id: input.modelId,
      scope: input.scope,
      target_case_ids: input.targetCaseIds ?? [],
      target_candidate_snapshots: input.targetCandidateSnapshots ?? [],
      knowledge_source_ids: input.knowledgeSourceIds ?? [],
      document_ids: input.documentIds ?? [],
      use_space_knowledge: input.useSpaceKnowledge ?? true,
      intent_override: input.intentOverride,
    }),
  });
}

export function confirmConversationIntent(
  messageId: string,
  intent: ConversationIntent,
): Promise<ConversationTurnDto> {
  return apiRequest(
    `/api/v1/conversation-messages/${messageId}/confirm-intent`,
    {
      method: "POST",
      body: JSON.stringify({ intent }),
    },
  );
}

export function retryConversationMessage(
  messageId: string,
): Promise<ConversationTurnDto> {
  return apiRequest(`/api/v1/conversation-messages/${messageId}/retry`, {
    method: "POST",
  });
}

export function answerConversationGeneration(
  conversationId: string,
  jobId: string,
  answers: { question_id: string; answer: string }[],
): Promise<ConversationDto> {
  return apiRequest(
    `/api/v1/conversations/${conversationId}/generation-jobs/${jobId}/answers`,
    {
      method: "POST",
      body: JSON.stringify({ answers }),
    },
  );
}

export async function waitForConversationJob(
  conversationId: string,
  jobId: string,
  timeoutMs = 900_000,
): Promise<ConversationMessageDto> {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    const conversation = await getConversation(conversationId);
    const message = conversation.messages.find(
      (item) => item.role === "assistant" && item.related_job_id === jobId,
    );
    if (
      message &&
      [
        "completed",
        "failed",
        "cancelled",
        "awaiting_clarification",
        "awaiting_confirmation",
      ].includes(message.status)
    ) {
      return message;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 1200));
  }
  throw new Error("对话任务超时，请稍后重试");
}

export function getCaseChangeSet(
  changeSetId: string,
): Promise<CaseChangeSetDto> {
  return apiRequest(`/api/v1/case-change-sets/${changeSetId}`);
}

export function applyCaseChangeSet(
  changeSetId: string,
  acceptedFields: Record<string, string[]> = {},
): Promise<CaseChangeSetApplyDto> {
  return apiRequest(`/api/v1/case-change-sets/${changeSetId}/apply`, {
    method: "POST",
    body: JSON.stringify({ accepted_fields: acceptedFields }),
  });
}

export function rejectCaseChangeSet(
  changeSetId: string,
): Promise<CaseChangeSetDto> {
  return apiRequest(`/api/v1/case-change-sets/${changeSetId}/reject`, {
    method: "POST",
  });
}

export function listKnowledgeSources(
  spaceId: string,
): Promise<KnowledgeSourceDto[]> {
  return apiRequest(`/api/v1/spaces/${spaceId}/knowledge-sources`);
}

export function uploadKnowledgeFiles(
  spaceId: string,
  name: string,
  files: File[],
  persistence: "space" | "temporary",
): Promise<{ source: KnowledgeSourceDto; document_ids: string[] }> {
  const form = new FormData();
  form.set("name", name);
  files.forEach((file) => form.append("files", file));
  const path =
    persistence === "space"
      ? `/api/v1/spaces/${spaceId}/knowledge-sources`
      : `/api/v1/spaces/${spaceId}/knowledge-documents`;
  return apiRequest(path, { method: "POST", body: form });
}

export function reindexKnowledgeSource(
  sourceId: string,
): Promise<KnowledgeSourceDto> {
  return apiRequest(`/api/v1/knowledge-sources/${sourceId}/reindex`, {
    method: "POST",
  });
}

export function deleteKnowledgeSource(sourceId: string): Promise<void> {
  return apiRequest(`/api/v1/knowledge-sources/${sourceId}`, {
    method: "DELETE",
  });
}

export async function waitForKnowledgeSource(
  spaceId: string,
  sourceId: string,
  timeoutMs = 120_000,
): Promise<KnowledgeSourceDto> {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    const sources = await listKnowledgeSources(spaceId);
    const source = sources.find((item) => item.id === sourceId);
    if (!source) throw new Error("知识来源不存在或已删除");
    if (source.status === "ready") return source;
    if (source.status === "failed") {
      throw new Error(source.error_code ?? "资料解析失败");
    }
    await new Promise((resolve) => window.setTimeout(resolve, 1200));
  }
  throw new Error("资料解析超时，请稍后在知识库查看状态");
}

export function listCollections(spaceId: string): Promise<CaseCollectionDto[]> {
  return apiRequest(`/api/v1/spaces/${spaceId}/collections`);
}

export function createCollection(
  spaceId: string,
  input: { name: string; description: string },
): Promise<CaseCollectionDto> {
  return apiRequest(`/api/v1/spaces/${spaceId}/collections`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateCollection(
  collectionId: string,
  input: { name?: string; description?: string },
): Promise<CaseCollectionDto> {
  return apiRequest(`/api/v1/collections/${collectionId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function deleteCollection(collectionId: string): Promise<void> {
  return apiRequest(`/api/v1/collections/${collectionId}`, {
    method: "DELETE",
  });
}

export function listTestCases(collectionId: string): Promise<TestCaseDto[]> {
  return apiRequest(`/api/v1/collections/${collectionId}/test-cases`);
}

export function createTestCase(
  collectionId: string,
  input: TestCaseInput,
): Promise<TestCaseDto> {
  return apiRequest(`/api/v1/collections/${collectionId}/test-cases`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function createTestCasesBatch(
  collectionId: string,
  inputs: TestCaseInput[],
): Promise<TestCaseDto[]> {
  return apiRequest(`/api/v1/collections/${collectionId}/test-cases/batch`, {
    method: "POST",
    body: JSON.stringify({ cases: inputs }),
  });
}

export function updateTestCase(
  caseId: string,
  input: TestCaseInput & { base_revision_id: string },
): Promise<TestCaseDto> {
  return apiRequest(`/api/v1/test-cases/${caseId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function deleteTestCase(caseId: string): Promise<void> {
  return apiRequest(`/api/v1/test-cases/${caseId}`, {
    method: "DELETE",
  });
}

export function createExecutionRun(
  collectionId: string,
  input: { description: string; assignee_ids: string[] },
): Promise<ExecutionRunDto> {
  return apiRequest(`/api/v1/collections/${collectionId}/execution-runs`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function listSpaceMembers(spaceId: string): Promise<SpaceMemberDto[]> {
  return apiRequest(`/api/v1/spaces/${spaceId}/members`);
}

export function addSpaceMember(
  spaceId: string,
  email: string,
): Promise<SpaceMemberDto> {
  return apiRequest(`/api/v1/spaces/${spaceId}/members`, {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export function removeSpaceMember(
  spaceId: string,
  accountId: string,
): Promise<void> {
  return apiRequest(`/api/v1/spaces/${spaceId}/members/${accountId}`, {
    method: "DELETE",
  });
}

export function listExecutionRuns(
  collectionId: string,
): Promise<ExecutionRunSummaryDto[]> {
  return apiRequest(`/api/v1/collections/${collectionId}/execution-runs`);
}

export function listSpaceExecutionRuns(
  spaceId: string,
): Promise<ExecutionRunSummaryDto[]> {
  return apiRequest(`/api/v1/spaces/${spaceId}/execution-runs`);
}

export function getExecutionRun(runId: string): Promise<ExecutionRunDto> {
  return apiRequest(`/api/v1/execution-runs/${runId}`);
}

export function closeExecutionRun(
  runId: string,
  status: "completed" | "aborted",
  allowIncomplete = false,
): Promise<ExecutionRunDto> {
  return apiRequest(`/api/v1/execution-runs/${runId}`, {
    method: "PATCH",
    body: JSON.stringify({ status, allow_incomplete: allowIncomplete }),
  });
}

export function updateExecutionRecord(
  recordId: string,
  input: {
    status: ExecutionStatusApi;
    completed_step_ids: string[];
    actual_result: string;
    defect_ref: string;
    base_updated_at: string;
  },
): Promise<ExecutionRecordDto> {
  return apiRequest(`/api/v1/execution-records/${recordId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function reassignExecutionRecord(
  recordId: string,
  assigneeId: string,
): Promise<ExecutionRecordDto> {
  return apiRequest(`/api/v1/execution-records/${recordId}/assignee`, {
    method: "PATCH",
    body: JSON.stringify({ assignee_id: assigneeId }),
  });
}

async function authRequest(
  path: string,
  init?: RequestInit,
): Promise<Account> {
  const response = await fetch(`${apiBaseUrl}/api/v1/auth${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new Error(payload?.detail ?? `auth_request_failed_${response.status}`);
  }
  return response.json() as Promise<Account>;
}

export function getCurrentAccount(): Promise<Account> {
  return authRequest("/me");
}

export function loginAccount(input: {
  email: string;
  password: string;
}): Promise<Account> {
  return authRequest("/login", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function registerAccount(input: {
  display_name: string;
  email: string;
  password: string;
}): Promise<Account> {
  return authRequest("/register", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function logoutAccount(): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/api/v1/auth/logout`, {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok && response.status !== 401) {
    throw new Error(`logout_failed_${response.status}`);
  }
}
