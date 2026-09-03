from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class ExecutionStatus(StrEnum):
    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class ConversationOperationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_INTENT = "awaiting_intent"
    AWAITING_COLLECTION = "awaiting_collection"
    AWAITING_TARGET = "awaiting_target"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class AccountRegistration(BaseModel):
    email: str = Field(min_length=5, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    display_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=10, max_length=128)


class AccountLogin(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class SpaceView(BaseModel):
    id: UUID
    name: str
    description: str
    role: str


class SpaceMemberView(BaseModel):
    account_id: UUID
    email: str
    display_name: str
    role: str
    created_at: datetime


class SpaceMemberAdd(BaseModel):
    email: str = Field(
        min_length=5,
        max_length=320,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )


class AccountView(BaseModel):
    id: UUID
    email: str
    display_name: str
    spaces: list[SpaceView]


class CaseCollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)


class CaseCollectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)


class CaseCollectionView(BaseModel):
    id: UUID
    space_id: UUID
    name: str
    description: str
    case_count: int
    created_at: datetime


class CaseStepInput(BaseModel):
    id: str | None = Field(default=None, max_length=80)
    action: str = Field(min_length=1, max_length=4000)
    expected: str = Field(min_length=1, max_length=4000)


class SourceRefInput(BaseModel):
    source_id: UUID | None = None
    document_id: UUID | None = None
    chunk_id: UUID | None = None
    label: str = Field(min_length=1, max_length=300)
    locator: str = Field(default="", max_length=500)
    excerpt: str = Field(default="", max_length=4000)


class TestCaseCreate(BaseModel):
    case_key: str | None = Field(default=None, max_length=40)
    title: str = Field(min_length=1, max_length=300)
    module: str = Field(default="", max_length=160)
    priority: str = Field(default="P1", pattern=r"^P[0-2]$")
    case_type: str = Field(default="功能", max_length=40)
    tags: list[str] = Field(default_factory=list, max_length=20)
    preconditions: list[str] = Field(default_factory=list, max_length=50)
    steps: list[CaseStepInput] = Field(min_length=1, max_length=100)
    source: str = Field(default="人工创建", max_length=500)
    source_refs: list[SourceRefInput] = Field(default_factory=list, max_length=30)


class TestCaseBatchCreate(BaseModel):
    cases: list[TestCaseCreate] = Field(min_length=1, max_length=100)


class TestCaseUpdate(BaseModel):
    base_revision_id: UUID
    title: str = Field(min_length=1, max_length=300)
    module: str = Field(default="", max_length=160)
    priority: str = Field(default="P1", pattern=r"^P[0-2]$")
    case_type: str = Field(default="功能", max_length=40)
    tags: list[str] = Field(default_factory=list, max_length=20)
    preconditions: list[str] = Field(default_factory=list, max_length=50)
    steps: list[CaseStepInput] = Field(min_length=1, max_length=100)
    source: str = Field(default="人工编辑", max_length=500)
    source_refs: list[SourceRefInput] | None = Field(default=None, max_length=30)


class TestCaseView(BaseModel):
    id: UUID
    case_key: str
    collection_ids: list[UUID]
    current_revision_id: UUID
    revision_number: int
    title: str
    module: str
    priority: str
    case_type: str
    tags: list[str]
    preconditions: list[str]
    steps: list[CaseStepInput]
    source: str
    source_refs: list[SourceRefInput] = Field(default_factory=list)
    created_at: datetime


class GenerationStartRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    markdown_content: str = Field(default="", max_length=100_000)
    file_names: list[str] = Field(default_factory=list, max_length=10)
    collection_id: UUID
    model_id: str = Field(
        default="auto",
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    document_ids: list[UUID] = Field(default_factory=list, max_length=6)
    knowledge_source_ids: list[UUID] = Field(default_factory=list, max_length=50)
    use_space_knowledge: bool = True


class GenerationJobView(BaseModel):
    id: UUID
    status: str
    stage: str
    space_id: UUID
    progress: int = 0
    error_code: str | None = None
    questions: list[dict] = Field(default_factory=list)
    stages: list[dict] = Field(default_factory=list)
    requirement: dict = Field(default_factory=dict)
    feature_points: list[dict] = Field(default_factory=list)
    test_points: list[dict] = Field(default_factory=list)
    test_cases: list[dict] = Field(default_factory=list)
    coverage_matrix: list[dict] = Field(default_factory=list)
    quality: dict = Field(default_factory=dict)
    source_refs: list[dict] = Field(default_factory=list)


class GenerationAnswerInput(BaseModel):
    question_id: str = Field(min_length=1, max_length=120)
    answer: str = Field(min_length=1, max_length=8000)


class GenerationAnswersRequest(BaseModel):
    answers: list[GenerationAnswerInput] = Field(min_length=1, max_length=30)


class ConversationCreate(BaseModel):
    space_id: UUID | None = None
    collection_id: UUID | None = None
    title: str = Field(default="新对话", min_length=1, max_length=240)
    knowledge_source_ids: list[UUID] = Field(default_factory=list, max_length=50)
    document_ids: list[UUID] = Field(default_factory=list, max_length=6)
    use_space_knowledge: bool = True


class ConversationTargetSnapshot(BaseModel):
    ref: str = Field(min_length=1, max_length=160)
    version: int = Field(default=1, ge=1)
    snapshot: dict


class ConversationTarget(BaseModel):
    kind: str = Field(pattern=r"^(case|module|condition|previous_result)$")
    collection_id: UUID | None = None
    case_ids: list[UUID] = Field(default_factory=list, max_length=100)
    candidate_refs: list[str] = Field(default_factory=list, max_length=100)
    module: str = Field(default="", max_length=160)
    condition: str = Field(default="", max_length=1000)
    source_operation_id: UUID | None = None


class ConversationMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    model_id: str = Field(
        default="auto",
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    scope: str = Field(
        default="current",
        pattern=r"^(current|module)$",
    )
    target_case_ids: list[UUID] = Field(default_factory=list, max_length=100)
    target_candidate_snapshots: list[ConversationTargetSnapshot] = Field(
        default_factory=list,
        max_length=100,
    )
    targets: list[ConversationTarget] = Field(default_factory=list, max_length=100)
    knowledge_source_ids: list[UUID] = Field(default_factory=list, max_length=50)
    document_ids: list[UUID] = Field(default_factory=list, max_length=6)
    use_space_knowledge: bool = True
    intent_override: str | None = Field(
        default=None,
        pattern=r"^(CASE_GENERATE|CASE_MODIFY|CASE_DELETE|CASE_QUERY|KNOWLEDGE_QA|SMALL_TALK|UNRESOLVED)$",
    )


class IntentConfirmationRequest(BaseModel):
    intent: str = Field(
        pattern=r"^(CASE_GENERATE|CASE_MODIFY|CASE_DELETE|CASE_QUERY|KNOWLEDGE_QA|SMALL_TALK|UNRESOLVED)$"
    )


class ConversationBindingUpdate(BaseModel):
    collection_id: UUID


class ConversationOperationCollectionConfirmRequest(BaseModel):
    collection_id: UUID | None = None
    create_collection_name: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def require_exactly_one_collection_choice(
        self,
    ) -> "ConversationOperationCollectionConfirmRequest":
        if (self.collection_id is None) == (self.create_collection_name is None):
            raise ValueError("exactly_one_collection_choice_required")
        if self.create_collection_name is not None:
            self.create_collection_name = self.create_collection_name.strip()
        return self


class ConversationOperationContinueRequest(BaseModel):
    collection_id: UUID


class ConversationOperationResumeRequest(BaseModel):
    intent: str | None = Field(
        default=None,
        pattern=r"^(CASE_GENERATE|CASE_MODIFY|CASE_DELETE|CASE_QUERY|KNOWLEDGE_QA|SMALL_TALK|UNRESOLVED)$",
    )
    targets: list[ConversationTarget] = Field(default_factory=list, max_length=100)
    target_case_ids: list[UUID] = Field(default_factory=list, max_length=100)
    target_candidate_snapshots: list[ConversationTargetSnapshot] = Field(
        default_factory=list,
        max_length=100,
    )


class ConversationOperationView(BaseModel):
    id: UUID
    sequence: int
    intent: str
    confidence: float
    status: ConversationOperationStatus
    target: dict
    payload: dict
    result: dict
    requires_confirmation: bool
    related_job_id: UUID | None
    related_change_set_id: UUID | None
    error_code: str | None
    created_at: datetime


class ConversationOperationPlanView(BaseModel):
    status: str
    source_message_id: UUID | None = None
    current_operation_id: UUID | None = None
    operations: list[ConversationOperationView] = Field(default_factory=list)


class TestBriefContent(BaseModel):
    test_object: str = Field(default="", max_length=1000)
    test_objective: str = Field(default="", max_length=8000)
    scope: list[str] = Field(default_factory=list, max_length=100)
    roles: list[str] = Field(default_factory=list, max_length=100)
    core_flows: list[str] = Field(default_factory=list, max_length=100)
    business_rules: list[str] = Field(default_factory=list, max_length=100)
    constraints: list[str] = Field(default_factory=list, max_length=100)
    risks: list[str] = Field(default_factory=list, max_length=100)
    coverage_dimensions: list[str] = Field(default_factory=list, max_length=100)
    assumptions: list[str] = Field(default_factory=list, max_length=100)
    open_questions: list[dict] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def keep_only_test_object_clarification(self) -> "TestBriefContent":
        self.test_object = self.test_object.strip()
        self.open_questions = (
            []
            if self.test_object
            else [
                {
                    "id": "Q-TEST-OBJECT",
                    "question": "请明确本次需要生成测试用例的测试对象。",
                    "impact": "未指定测试对象，无法确定用例生成范围。",
                    "blocking": True,
                }
            ]
        )
        return self


class WorkspaceTestBriefView(BaseModel):
    id: UUID
    source_operation_id: UUID | None = None
    version: int
    content: TestBriefContent
    markdown_content: str
    status: str
    confirmed_at: datetime | None
    created_at: datetime


class WorkspaceCandidateView(BaseModel):
    id: UUID
    generation_job_id: UUID | None
    ref: str
    version: int
    position: int
    snapshot: dict
    included: bool
    status: str
    updated_at: datetime


class WorkspaceStateUpdate(BaseModel):
    draft_text: str | None = Field(default=None, max_length=8000)
    model_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    selected_case_id: str | None = Field(default=None, max_length=160)
    selected_targets: list[dict] | None = Field(default=None, max_length=100)
    active_view: str | None = Field(default=None, pattern=r"^(list|map)$")
    search_query: str | None = Field(default=None, max_length=500)
    filters: dict | None = None
    chat_width: int | None = Field(default=None, ge=280, le=520)
    inspector_width: int | None = Field(default=None, ge=280, le=520)
    selected_brief_version: int | None = Field(default=None, ge=1)


class TestBriefCreate(BaseModel):
    content: TestBriefContent


class TestBriefConfirmRequest(BaseModel):
    version: int = Field(ge=1)
    model_id: str = Field(
        default="auto",
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )


class WorkspaceCandidateUpdate(BaseModel):
    base_version: int = Field(ge=1)
    snapshot: dict | None = None
    included: bool | None = None

    @model_validator(mode="after")
    def require_candidate_change(self) -> "WorkspaceCandidateUpdate":
        if self.snapshot is None and self.included is None:
            raise ValueError("candidate_update_required")
        return self


class WorkspaceCandidateCommitRequest(BaseModel):
    candidate_ids: list[UUID] = Field(default_factory=list, max_length=100)


class ConversationMessageView(BaseModel):
    id: UUID
    role: str
    content: str
    intent: str | None
    intent_confidence: float | None
    status: str
    target_case_ids: list[str]
    related_job_id: UUID | None
    citations: list[dict]
    metadata: dict
    created_at: datetime


class ConversationWorkflowStageView(BaseModel):
    stage: str
    attempt: int
    status: str
    progress: int
    model: str
    latency_ms: int
    created_at: datetime


class ConversationWorkflowRunView(BaseModel):
    job_id: UUID
    message_id: UUID
    operation: str
    status: str
    current_stage: str
    progress: int
    error_code: str | None = None
    stages: list[ConversationWorkflowStageView] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ConversationView(BaseModel):
    id: UUID
    space_id: UUID
    collection_id: UUID | None
    title: str
    status: str
    context: dict
    messages: list[ConversationMessageView]
    test_briefs: list[WorkspaceTestBriefView] = Field(default_factory=list)
    candidates: list[WorkspaceCandidateView] = Field(default_factory=list)
    workflow_runs: list[ConversationWorkflowRunView] = Field(default_factory=list)
    operation_plan: ConversationOperationPlanView | None = None
    created_at: datetime
    updated_at: datetime


class ConversationSummaryView(BaseModel):
    id: UUID
    collection_id: UUID | None
    title: str
    collection_name: str | None
    phase: str
    last_message_preview: str
    created_at: datetime
    updated_at: datetime


class ConversationHistoryPage(BaseModel):
    items: list[ConversationSummaryView] = Field(default_factory=list)
    next_cursor: str | None = None


class ConversationTurnView(BaseModel):
    conversation_id: UUID
    user_message: ConversationMessageView
    assistant_message: ConversationMessageView | None = None
    intent: str
    intent_confidence: float
    requires_intent_confirmation: bool = False
    action: dict = Field(default_factory=dict)
    operation_plan: ConversationOperationPlanView | None = None


class ChangeSetApplyRequest(BaseModel):
    accepted_fields: dict[str, list[str]] = Field(default_factory=dict)


class CaseChangeSetView(BaseModel):
    id: UUID
    conversation_id: UUID
    generation_job_id: UUID | None
    instruction: str
    scope: str
    status: str
    items: list[dict]
    created_at: datetime
    applied_at: datetime | None


class CaseChangeSetApplyView(BaseModel):
    change_set: CaseChangeSetView
    test_cases: list[TestCaseView] = Field(default_factory=list)
    candidate_snapshots: list[dict] = Field(default_factory=list)


class KnowledgeDocumentView(BaseModel):
    id: UUID
    source_id: UUID
    original_name: str
    mime_type: str
    size_bytes: int
    version: int
    status: str
    error_code: str | None
    expires_at: datetime | None
    created_at: datetime


class KnowledgeSourceView(BaseModel):
    id: UUID
    space_id: UUID
    name: str
    kind: str
    persistence: str
    status: str
    error_code: str | None
    document_count: int
    documents: list[KnowledgeDocumentView]
    created_at: datetime


class KnowledgeUploadView(BaseModel):
    source: KnowledgeSourceView
    document_ids: list[UUID]


class CandidateCreate(BaseModel):
    base_revision_id: UUID
    instruction: str = Field(min_length=1, max_length=2000)
    model_id: str = Field(
        default="auto",
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )


class CandidateView(BaseModel):
    id: UUID
    test_case_id: UUID
    base_revision_id: UUID
    status: str
    proposed_snapshot: dict
    field_diff: list[dict]
    reason: str


class CandidateJobView(BaseModel):
    job_id: UUID


class ExecutionRecordUpdate(BaseModel):
    status: ExecutionStatus
    completed_step_ids: list[str] = Field(default_factory=list, max_length=100)
    actual_result: str = Field(default="", max_length=8000)
    defect_ref: str = Field(default="", max_length=160)
    base_updated_at: datetime | None = None


class ExecutionRecordReassign(BaseModel):
    assignee_id: UUID


class ExecutionRunCreate(BaseModel):
    description: str = Field(min_length=1, max_length=2000)
    assignee_ids: list[UUID] = Field(min_length=1, max_length=100)


class ExecutionRunUpdate(BaseModel):
    status: str = Field(pattern=r"^(completed|aborted)$")
    allow_incomplete: bool = False


class ExecutionRecordView(BaseModel):
    id: UUID
    test_case: TestCaseView
    status: ExecutionStatus
    completed_step_ids: list[str]
    actual_result: str
    defect_ref: str
    assignee_id: UUID | None
    assignee_name: str | None
    can_edit: bool = False
    updated_by_name: str | None
    updated_at: datetime


class ExecutionRunSummaryView(BaseModel):
    id: UUID
    collection_id: UUID
    collection_name: str
    description: str
    status: str
    creator_name: str
    assignee_ids: list[UUID] = Field(default_factory=list)
    assignee_names: list[str] = Field(default_factory=list)
    contributor_names: list[str]
    created_at: datetime
    last_activity_at: datetime
    completed_at: datetime | None
    total_count: int
    not_run_count: int
    passed_count: int
    failed_count: int
    skipped_count: int
    blocked_count: int


class ExecutionRunView(BaseModel):
    id: UUID
    collection_id: UUID
    collection_name: str
    description: str
    status: str
    creator_name: str
    creator_id: UUID
    assignee_ids: list[UUID] = Field(default_factory=list)
    assignee_names: list[str] = Field(default_factory=list)
    can_manage: bool = False
    contributor_names: list[str]
    created_at: datetime
    last_activity_at: datetime
    completed_at: datetime | None
    records: list[ExecutionRecordView]
