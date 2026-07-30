from enum import StrEnum
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, Field

EMBEDDING_DIMENSIONS = 2048


class CaseStatus(StrEnum):
    PENDING = "pending"


class Priority(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


class SourceRef(BaseModel):
    source_id: str | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    label: str
    locator: str = ""
    excerpt: str = ""


class OpenQuestion(BaseModel):
    id: str
    question: str
    impact: str
    blocking: bool = False


class RequirementAnalysis(BaseModel):
    test_object: str = Field(
        default="",
        description="用户明确指定的被测功能、流程、接口、页面、系统或用例范围。",
    )
    test_object_specified: bool = Field(
        default=False,
        description="测试对象是否已由用户输入、最近对话或用户提供的资料明确给出。",
    )
    summary: str
    actors: list[str] = Field(default_factory=list)
    flows: list[str] = Field(default_factory=list)
    business_rules: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)


class FeaturePoint(BaseModel):
    id: str
    name: str
    description: str
    module: str
    requirement_refs: list[str]
    source_refs: list[SourceRef] = Field(default_factory=list)


class TestPoint(BaseModel):
    id: str
    title: str
    objective: str
    category: str
    priority: Priority
    priority_reason: str
    executable: bool = True
    executable_analysis: str = ""
    feature_point_ids: list[str]
    source_refs: list[SourceRef] = Field(default_factory=list)


class TestStep(BaseModel):
    action: str
    expected: str


class TestCaseDraft(BaseModel):
    id: str
    title: str
    module: str
    case_type: str
    priority: Priority
    tags: list[str] = Field(default_factory=list)
    automated: bool = False
    status: CaseStatus = CaseStatus.PENDING
    preconditions: list[str]
    steps: list[TestStep]
    test_point_ids: list[str]
    source_refs: list[SourceRef] = Field(default_factory=list)


class QualityIssue(BaseModel):
    code: str
    message: str
    object_id: str | None = None
    severity: str = "warning"


class QualityReport(BaseModel):
    passed: bool
    score: int = Field(ge=0, le=100)
    issues: list[QualityIssue] = Field(default_factory=list)
    repair_rounds: int = 0


class ContextEvidence(BaseModel):
    source_id: str
    document_id: str
    chunk_id: str
    label: str
    locator: str = ""
    excerpt: str
    rank: int
    scores: dict[str, float] = Field(default_factory=dict)


class ContextBundle(BaseModel):
    query: str
    evidence: list[ContextEvidence] = Field(default_factory=list)
    retrieval_mode: str = "hybrid"
    warnings: list[QualityIssue] = Field(default_factory=list)


class FeaturePlan(BaseModel):
    feature_points: list[FeaturePoint]


class TestPointPlan(BaseModel):
    test_points: list[TestPoint]
    coverage_matrix: list[dict[str, Any]] = Field(default_factory=list)


class TestCaseBatch(BaseModel):
    test_cases: list[TestCaseDraft]


class EnhancementResult(BaseModel):
    test_points: list[TestPoint]
    test_cases: list[TestCaseDraft]
    enhanced_dimensions: list[str] = Field(default_factory=list)


class UsageMetadata(BaseModel):
    model: str
    latency_ms: int = 0
    token_usage: dict[str, int] = Field(default_factory=dict)


class GenerationRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    markdown_content: str = Field(default="", max_length=100_000)
    file_names: list[str] = Field(default_factory=list, max_length=10)
    conversation_memory: list[dict[str, str]] = Field(
        default_factory=list,
        max_length=100,
    )
    model_id: str = "auto"


class GenerationResult(BaseModel):
    mode: str
    requirement: RequirementAnalysis
    feature_points: list[FeaturePoint]
    test_points: list[TestPoint]
    test_cases: list[TestCaseDraft]
    coverage_matrix: list[dict[str, Any]] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)
    quality: QualityReport
    model_metadata: dict[str, Any] = Field(default_factory=dict)


class RewriteRequest(BaseModel):
    test_case: TestCaseDraft
    instruction: str = Field(min_length=1, max_length=2000)
    conversation_memory: list[dict[str, str]] = Field(
        default_factory=list,
        max_length=100,
    )
    model_id: str = "auto"


class FieldDiff(BaseModel):
    field: str
    before: Any
    after: Any


class RewriteCandidate(BaseModel):
    proposed: TestCaseDraft
    diff: list[FieldDiff]
    reason: str
    quality: QualityReport


class KnowledgeAnswer(BaseModel):
    answer: str
    citations: list[SourceRef] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


StructuredResultT = TypeVar("StructuredResultT", bound=BaseModel)


class EmbeddingProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class AgentProvider(Protocol):
    def generate(self, request: GenerationRequest) -> GenerationResult: ...

    def rewrite(self, request: RewriteRequest) -> RewriteCandidate: ...

    def complete(
        self,
        *,
        stage: str,
        instruction: str,
        payload: dict[str, Any],
        result_type: type[StructuredResultT],
        model_id: str,
    ) -> tuple[StructuredResultT, UsageMetadata]: ...
