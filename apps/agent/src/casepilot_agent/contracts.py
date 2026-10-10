from collections.abc import Callable
from enum import StrEnum
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, Field

EMBEDDING_DIMENSIONS = 2048

GENERATION_GROUNDING_INSTRUCTION = (
    "每一条确定预期必须由用户需求或原始证据支持，不能把常见产品习惯当作需求。"
    "尤其不得自行添加页面跳转、停留页面、提示文案、HTTP状态码、响应字段或业务规则。"
    "建立会话不等于跳转首页；拒绝登录不等于停留登录页。只有来源明确规定时才能断言这些行为。"
    "功能点和测试点是派生材料；与原始需求冲突或比原始需求更具体时，以原始需求为准。"
    "输出前逐条核对步骤预期，删除无来源的附加断言；必要但未知的事实仅放入假设或开放问题，不能写成通过条件。"
)

CASE_DESIGN_INSTRUCTION = (
    "module仅为稳定业务分类，不含场景、操作、预期或用例标题；功能名使用简短业务名。"
    "测试主题允许关联多个独立场景，禁止模块、场景、标题连续同义重复。"
    "仅当前置状态、关键输入、业务分支或预期存在实质差异时拆分用例。"
    "连续操作属于同一procedure，多个校验属于同一用例checkpoints，不按步骤或校验数量拆分。"
    "终端规则相同时参数化表达；存在独立流程或风险时才分端拆分。"
    "按业务规则、前置状态、动作、预期判断重复，同一目标只归属一个主要功能。"
    "完整流程已覆盖的校验，只有存在额外风险时才单独成例。"
    "参考全局场景索引，避免跨批同义重复；数量是覆盖目标，禁止凑数。"
    "多端账号一致不等于一端登录后其他端自动登录；冲突或缺失规则列为待确认，不能猜测预期。"
)

SINGLE_CASE_REWRITE_INSTRUCTION = (
    "本次调用只改写 input.test_case（原用例）这一条用例，保留其 id。"
    "批量选择已由服务端完成，服务端会逐条调用；用户原始指令中的两条、多条、全部、"
    "剩余等数量和范围描述仅为背景，不得在本次输出中增加、选择或重建其他用例。"
    "只修改明确要求的字段，未要求修改的内容逐字保留，已有步骤不因生成规范而缩减。"
    "proposed 必须是单个完整用例对象，不能是数组；diff 必须是该用例的字段差异数组，"
    "每项直接包含 field、before、after，不得按 case_id 或 field_diffs 再分组。"
    "返回修改理由和质量报告，不声称已保存。"
)


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
    scenario: str = ""
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
    action: str = Field(
        min_length=0,
        max_length=4000,
        description="test_procedure 中的一项，仅描述可执行操作，不混入预期结果。",
    )
    expected: str = Field(
        min_length=0,
        max_length=4000,
        description="整条用例的一项可观察校验点，不要求与本行操作对应；无对应项时留空。",
    )


class RewriteCaseDraft(BaseModel):
    """Existing assets use the same limits as the case management API."""

    id: str
    title: str = Field(
        min_length=1,
        max_length=300,
        description="四段式用例的 title：单一、明确、可辨识的测试目标。",
    )
    module: str
    case_type: str
    priority: Priority
    tags: list[str] = Field(default_factory=list)
    automated: bool = False
    status: CaseStatus = CaseStatus.PENDING
    preconditions: list[str] = Field(
        min_length=0,
        max_length=50,
        description="test_setup：环境、状态、身份、权限和测试数据前提；无前提时明确写无特殊前置条件。",
    )
    steps: list[TestStep] = Field(
        min_length=1,
        max_length=100,
        description=(
            "兼容存储结构：依次将 steps[].action 作为 test_procedure，"
            "steps[].expected 作为独立的用例级 test_validation，忽略空项，不要求逐步对应。"
        ),
    )
    test_point_ids: list[str]
    source_refs: list[SourceRef] = Field(default_factory=list)


class TestCaseDraft(RewriteCaseDraft):
    """Newly generated cases retain the compact generation contract."""

    preconditions: list[str] = Field(
        min_length=1, max_length=50,
        description=RewriteCaseDraft.model_fields["preconditions"].description,
    )
    steps: list[TestStep] = Field(
        min_length=1, max_length=4,
        description=RewriteCaseDraft.model_fields["steps"].description,
    )


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
    feature_points: list[FeaturePoint] = Field(default_factory=list)
    test_points: list[TestPoint] = Field(default_factory=list)
    test_cases: list[TestCaseDraft] = Field(default_factory=list)
    enhanced_dimensions: list[str] = Field(default_factory=list)


class UsageMetadata(BaseModel):
    model: str
    latency_ms: int = 0
    token_usage: dict[str, int] = Field(default_factory=dict)


class GenerationRequest(BaseModel):
    output_contract: str = "legacy"
    confirmed_plan: dict[str, Any] = Field(default_factory=dict)
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
    context: dict[str, Any] = Field(default_factory=dict)
    test_case: RewriteCaseDraft
    instruction: str = Field(min_length=1, max_length=8000)
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
    proposed: RewriteCaseDraft
    diff: list[FieldDiff]
    reason: str
    quality: QualityReport


class RewriteBatchItem(RewriteCandidate):
    ref: str


class RewriteBatch(BaseModel):
    items: list[RewriteBatchItem]


class RewritePatchItem(BaseModel):
    ref: str
    changes: dict[str, Any] = Field(
        description="仅返回变化字段及新值；未修改字段省略，禁止修改id。数组字段返回完整新数组。"
    )
    reason: str
    quality: QualityReport


class RewritePatchBatch(BaseModel):
    items: list[RewritePatchItem]


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

    def complete_text_stream(
        self,
        *,
        stage: str,
        instruction: str,
        payload: dict[str, Any],
        model_id: str,
        on_delta: Callable[[str], None],
    ) -> tuple[str, UsageMetadata]: ...
