from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field


class CaseStatus(StrEnum):
    PENDING = "pending"


class GenerationRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    file_names: list[str] = Field(default_factory=list, max_length=10)
    model_id: str = "auto"


class Risk(BaseModel):
    id: str
    severity: str
    title: str
    source: str


class TestStep(BaseModel):
    action: str
    expected: str


class TestCase(BaseModel):
    id: str
    title: str
    status: CaseStatus = CaseStatus.PENDING
    preconditions: list[str]
    steps: list[TestStep]


class GenerationResult(BaseModel):
    mode: str
    stages: list[str]
    risks: list[Risk]
    test_cases: list[TestCase]


class AgentProvider(Protocol):
    @property
    def name(self) -> str: ...

    def generate(self, request: GenerationRequest) -> GenerationResult: ...
