from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field


class CaseStatus(StrEnum):
    PENDING = "pending"


class Priority(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


class SourceRef(BaseModel):
    label: str
    excerpt: str = ""


class OpenQuestion(BaseModel):
    id: str
    question: str
    impact: str
    blocking: bool = False


class RequirementAnalysis(BaseModel):
    summary: str
    actors: list[str] = Field(default_factory=list)
    business_rules: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
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


class GenerationRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    markdown_content: str = Field(default="", max_length=100_000)
    file_names: list[str] = Field(default_factory=list, max_length=10)
    model_id: str = "auto"


class GenerationResult(BaseModel):
    mode: str
    requirement: RequirementAnalysis
    feature_points: list[FeaturePoint]
    test_points: list[TestPoint]
    test_cases: list[TestCaseDraft]
    quality: QualityReport
    model_metadata: dict[str, Any] = Field(default_factory=dict)


class RewriteRequest(BaseModel):
    test_case: TestCaseDraft
    instruction: str = Field(min_length=1, max_length=2000)
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


class AgentProvider(Protocol):
    @property
    def name(self) -> str: ...

    def generate(self, request: GenerationRequest) -> GenerationResult: ...

    def rewrite(self, request: RewriteRequest) -> RewriteCandidate: ...
