from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class CaseStatus(StrEnum):
    PENDING = "pending"
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


class MockGenerationRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    file_names: list[str] = Field(default_factory=list, max_length=10)


class MockRisk(BaseModel):
    id: str
    severity: str
    title: str
    source: str


class MockTestCase(BaseModel):
    id: str
    title: str
    status: CaseStatus = CaseStatus.PENDING
    preconditions: list[str]
    steps: list[dict[str, str]]


class MockGenerationJob(BaseModel):
    id: UUID
    mode: str = "mock"
    status: str
    prompt: str
    file_names: list[str]
    stages: list[str]
    risks: list[MockRisk]
    test_cases: list[MockTestCase]


class GenerationStartRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    file_names: list[str] = Field(default_factory=list, max_length=10)
    space_id: UUID | None = None
    model_id: str = Field(default="auto", pattern=r"^(auto|pro|local)$")


class GenerationJobView(BaseModel):
    id: UUID
    status: str
    stage: str
    space_id: UUID
