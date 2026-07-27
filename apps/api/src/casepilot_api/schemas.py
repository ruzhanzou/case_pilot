from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class ExecutionStatus(StrEnum):
    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


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
    created_at: datetime


class ExecutionRecordUpdate(BaseModel):
    status: ExecutionStatus
    completed_step_ids: list[str] = Field(default_factory=list, max_length=100)
    actual_result: str = Field(default="", max_length=8000)
    defect_ref: str = Field(default="", max_length=160)
    base_updated_at: datetime | None = None


class ExecutionRunCreate(BaseModel):
    description: str = Field(min_length=1, max_length=2000)


class ExecutionRunUpdate(BaseModel):
    status: str = Field(pattern=r"^(completed|aborted)$")


class ExecutionRecordView(BaseModel):
    id: UUID
    test_case: TestCaseView
    status: ExecutionStatus
    completed_step_ids: list[str]
    actual_result: str
    defect_ref: str
    updated_by_name: str | None
    updated_at: datetime


class ExecutionRunSummaryView(BaseModel):
    id: UUID
    collection_id: UUID
    collection_name: str
    description: str
    status: str
    creator_name: str
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
    contributor_names: list[str]
    created_at: datetime
    last_activity_at: datetime
    completed_at: datetime | None
    records: list[ExecutionRecordView]
