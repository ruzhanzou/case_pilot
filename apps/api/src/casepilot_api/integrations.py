"""TestWeb and TestTool integration APIs.

The public contract deliberately uses stable external IDs while retaining UUIDs
inside CasePilot.  TestWeb writes targets and requests work; TestTool only sees
confirmed work assigned to the authenticated external user.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from casepilot_api.auth import CurrentAccount, require_space_membership
from casepilot_api.case_management import (
    available_playlist_name,
    create_execution_run_from_cases,
    replace_playlist_memberships,
)
from casepilot_api.config import get_settings
from casepilot_api.database import get_db_session, get_session_factory
from casepilot_api.models import (
    Account,
    CallbackDelivery,
    CaseCollection,
    CaseGenerationCase,
    CaseGenerationSession,
    CaseProject,
    CollectionCaseMembership,
    ExecutionRecord,
    ExecutionRun,
    ExecutionStatus,
    GenerationJob,
    IntegrationTask,
    IntegrationUpdate,
    Playlist,
    PlaylistCaseMembership,
    PlaylistCreationSession,
    PlaylistSourceCollection,
    SpaceMembership,
    TestCase,
    TestCaseRevision,
    TestToolLease,
)
from casepilot_api.schemas import ExecutionRunCreate
from casepilot_api.task_outbox import enqueue_task

router = APIRouter(tags=["service-integrations"])
settings = get_settings()
DbSession = Annotated[Session, Depends(get_db_session)]
ExecutionLevel = Literal["L0", "L2", "L4"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TestTarget(StrictModel):
    target_type: str = Field(min_length=1, max_length=40)
    target_id: int = Field(ge=1)
    target_key: str = Field(default="", max_length=120)
    title: str = Field(min_length=1, max_length=300)
    linked_fr_ids: list[int | str] = Field(default_factory=list, max_length=500)
    linked_qpm_ids: list[int | str] = Field(default_factory=list, max_length=500)


class CaseProjectCreate(StrictModel):
    source_system: str = Field(default="test_web", min_length=1, max_length=40)
    space_id: UUID | None = None
    test_target: TestTarget
    test_context: dict = Field(default_factory=dict)


class GenerationStart(StrictModel):
    test_target: TestTarget | dict = Field(default_factory=dict)
    test_context: dict = Field(default_factory=dict)
    model_id: str = Field(
        default="auto",
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    callback_url: AnyHttpUrl | None = None
    callback_events: list[Literal["generation-status", "case-summary"]] = Field(
        default_factory=lambda: ["generation-status", "case-summary"]
    )
    callback_correlation_id: str | None = Field(default=None, min_length=1, max_length=200)


class TaskContext(StrictModel):
    tester: str = Field(min_length=1, max_length=320)
    execution_notes: str = Field(default="", max_length=10_000)
    execution_level: ExecutionLevel = "L4"


class TaskCreate(StrictModel):
    test_target: TestTarget
    test_context: dict = Field(default_factory=dict)
    task_context: TaskContext
    task_request_id: UUID
    case_generation_id: str = Field(min_length=1, max_length=32)
    callback_url: AnyHttpUrl | None = None
    callback_events: list[Literal["task-status", "case-execution-status"]] = Field(
        default_factory=lambda: ["task-status", "case-execution-status"]
    )
    callback_correlation_id: str | None = Field(default=None, min_length=1, max_length=200)


class CollectionSeed(StrictModel):
    collection_id: UUID | None = None
    case_project_id: str | None = Field(default=None, max_length=24)
    case_generation_id: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def require_collection_reference(self) -> CollectionSeed:
        if self.collection_id is None and not self.case_project_id:
            raise ValueError("collection_id_or_case_project_id_required")
        return self


class PlaylistDraft(StrictModel):
    name: str = Field(default="", max_length=160)
    description: str = Field(default="", max_length=2_000)
    execution_notes: str = Field(default="", max_length=10_000)
    case_ids: list[str] = Field(default_factory=list, max_length=500)


class PlaylistCreationStart(StrictModel):
    creator: str = Field(min_length=1, max_length=320)
    test_target: TestTarget
    case_collections: list[CollectionSeed] = Field(min_length=1, max_length=100)
    playlist: PlaylistDraft = Field(default_factory=PlaylistDraft)
    callback_url: AnyHttpUrl
    callback_events: list[
        Literal["playlist-created", "playlist-creation-cancelled", "playlist-creation-expired"]
    ] = Field(default_factory=lambda: ["playlist-created"])
    callback_correlation_id: str | None = Field(default=None, min_length=1, max_length=200)
    callback_context: dict = Field(default_factory=dict)
    expires_in_seconds: int = Field(default=3600, ge=300, le=86_400)


class PlaylistCreationComplete(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2_000)
    case_ids: list[str] = Field(min_length=1, max_length=500)
    execution_notes: str = Field(default="", max_length=10_000)


class TaskConfirm(StrictModel):
    execution_level: ExecutionLevel | None = None


class ClaimRequest(StrictModel):
    worker_id: str = Field(min_length=1, max_length=160)
    lease_seconds: int | None = Field(default=None, ge=30, le=3600)


class CaseExecutionUpdate(StrictModel):
    status: Literal["not_run", "running", "passed", "failed", "blocked", "skipped", "pass", "fail"]
    updated_at: datetime
    actual_result: str = Field(default="", max_length=50_000)
    completed_step_ids: list[str] = Field(default_factory=list)
    jira: str = Field(default="", max_length=160)
    cr: str = Field(default="", max_length=160)
    logs: list[dict] = Field(default_factory=list)
    artifacts: list[dict] = Field(default_factory=list)


class TaskExecutionUpdate(StrictModel):
    update_id: UUID
    lease_token: str = Field(min_length=20)
    status: Literal["confirmed", "running", "completed", "failed", "cancelled"]
    updated_at: datetime
    cases_complete: bool = True
    cases: dict[str, CaseExecutionUpdate]
    logs: list[dict] = Field(default_factory=list)
    artifacts: list[dict] = Field(default_factory=list)


class CaseProjectResponse(BaseModel):
    case_project_id: str
    case_platform_url: str


class CaseProjectNavigationResponse(BaseModel):
    case_project_id: str
    space_id: UUID
    collection_id: UUID
    title: str
    test_target: dict


class GenerationResponse(BaseModel):
    case_generation_id: str
    case_generation_status: str
    case_platform_url: str
    callback_correlation_id: str | None = None


class PlaylistCreationResponse(BaseModel):
    playlist_creation_id: UUID
    creation_status: str
    case_platform_url: str
    expires_at: datetime


class PlaylistCreationSessionView(BaseModel):
    playlist_creation_id: UUID
    space_id: UUID
    creation_status: str
    creator: dict
    test_target: dict
    case_collections: list[dict]
    playlist: dict
    callback_url: str
    callback_events: list[str]
    callback_correlation_id: str | None
    callback_context: dict
    expires_at: datetime


class PlaylistCreationCompleteResponse(BaseModel):
    playlist: dict
    creation_status: str
    created_at: datetime
    case_platform_url: str


class PlaylistTaskListResponse(BaseModel):
    items: list[dict]
    next_cursor: str | None


class CaseSummaryItem(BaseModel):
    stage: ExecutionLevel
    test_domain: list[str]
    title: str
    automation_type: Literal["manual", "automated"]


class CaseSummaryResponse(BaseModel):
    target_type: str
    target_id: int
    case_project_id: str
    case_platform_url: str
    case_generation_id: str
    generation_status: str
    generation_updated_at: datetime
    cases: dict[str, CaseSummaryItem]


class TaskAckResponse(BaseModel):
    task_request_id: UUID
    test_task_id: str
    execution_status: str
    case_platform_url: str


class TaskCaseResponse(BaseModel):
    case_id: str
    title: str
    stage: ExecutionLevel
    test_domain: list[str]
    automation_type: Literal["manual", "automated"]
    preconditions: list[str]
    steps: list[dict]
    status: str
    actual_result: str
    completed_step_ids: list[str]
    defect_ref: str
    logs: list[dict]
    artifacts: list[dict]
    updated_at: datetime


class TaskDetailResponse(BaseModel):
    test_task_id: str
    task_request_id: UUID
    case_project_id: str
    case_generation_id: str
    target_type: str
    target_id: int
    target_key: str
    task_name: str
    tester: str
    execution_notes: str
    execution_level: ExecutionLevel
    execution_status: str
    updated_at: datetime
    cases_complete: bool
    cases: dict[str, TaskCaseResponse]
    logs: list[dict]
    artifacts: list[dict]
    case_platform_url: str
    lease_expires_at: datetime | None = None


class ClaimResponse(TaskDetailResponse):
    lease_token: str


class TaskListResponse(BaseModel):
    items: list[TaskDetailResponse]
    next_cursor: str | None


class HeartbeatResponse(BaseModel):
    test_task_id: str
    lease_expires_at: datetime


def now() -> datetime:
    return datetime.now(UTC)


def require_bearer(authorization: str | None, expected: str) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="bearer_token_required")
    if not secrets.compare_digest(authorization[7:], expected):
        raise HTTPException(status_code=401, detail="invalid_api_token")


def require_case_service(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    require_bearer(authorization, settings.case_service_api_token)


def require_test_tool_user(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
    x_testtool_user_id: Annotated[str | None, Header()] = None,
) -> Account:
    require_bearer(authorization, settings.test_tool_api_token)
    if not x_testtool_user_id:
        raise HTTPException(status_code=401, detail="testtool_user_id_required")
    try:
        account = db.get(Account, UUID(x_testtool_user_id))
    except ValueError:
        account = db.scalar(
            select(Account).where(func.lower(Account.email) == x_testtool_user_id.strip().lower())
        )
    if account is None or not account.is_active:
        raise HTTPException(status_code=403, detail="testtool_user_not_bound")
    return account


TestToolAccount = Annotated[Account, Depends(require_test_tool_user)]
CaseServiceAuth = Annotated[None, Depends(require_case_service)]


def next_public_id(db: Session, sequence: str, prefix: str, width: int = 5) -> str:
    value = db.scalar(select(func.nextval(sequence)))
    return f"{prefix}{int(value):0{width}d}"


def platform_url(path: str) -> str:
    return f"{settings.case_platform_base_url.rstrip('/')}{path}"


def case_project_access_token(project: CaseProject) -> str:
    expires_at = int(
        (datetime.now(UTC) + timedelta(seconds=settings.case_platform_link_ttl_seconds))
        .timestamp()
    )
    message = f"{project.public_id}:{project.space_id}:{expires_at}".encode()
    signature = hmac.new(
        settings.case_service_api_token.encode(), message, hashlib.sha256
    ).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{expires_at}.{encoded_signature}"


def validate_case_project_access_token(project: CaseProject, token: str) -> bool:
    try:
        expires_at_text, provided_signature = token.split(".", 1)
        expires_at = int(expires_at_text)
    except (TypeError, ValueError):
        return False
    if expires_at < int(datetime.now(UTC).timestamp()):
        return False
    message = f"{project.public_id}:{project.space_id}:{expires_at}".encode()
    expected_signature = (
        base64.urlsafe_b64encode(
            hmac.new(settings.case_service_api_token.encode(), message, hashlib.sha256).digest()
        )
        .decode()
        .rstrip("=")
    )
    return hmac.compare_digest(provided_signature, expected_signature)


def case_project_platform_url(project: CaseProject) -> str:
    return platform_url(
        f"/case-projects/{project.public_id}?access_token={case_project_access_token(project)}"
    )


def choose_service_identity(db: Session, requested_space_id: UUID | None) -> tuple[UUID, UUID]:
    space_id = requested_space_id
    if space_id is None and settings.integration_default_space_id:
        try:
            space_id = UUID(settings.integration_default_space_id)
        except ValueError as error:
            raise HTTPException(status_code=500, detail="invalid_default_space_id") from error
    query = select(SpaceMembership).order_by(
        (SpaceMembership.role == "owner").desc(), SpaceMembership.created_at
    )
    if space_id is not None:
        query = query.where(SpaceMembership.space_id == space_id)
    membership = db.scalar(query)
    if membership is None:
        raise HTTPException(status_code=422, detail="integration_space_not_found")
    return membership.space_id, membership.account_id


def get_project(db: Session, public_id: str) -> CaseProject:
    project = db.scalar(select(CaseProject).where(CaseProject.public_id == public_id))
    if project is None:
        raise HTTPException(status_code=404, detail="case_project_not_found")
    return project


def get_generation(db: Session, project: CaseProject, public_id: str) -> CaseGenerationSession:
    generation = db.scalar(
        select(CaseGenerationSession).where(
            CaseGenerationSession.case_project_id == project.id,
            CaseGenerationSession.public_id == public_id,
        )
    )
    if generation is None:
        raise HTTPException(status_code=422, detail="case_generation_not_found")
    return generation


def assert_target(project: CaseProject, target: TestTarget) -> None:
    if target.target_type != project.target_type or target.target_id != project.target_id:
        raise HTTPException(status_code=422, detail="test_target_mismatch")


def account_ref(account: Account) -> dict:
    return {
        "id": str(account.id),
        "username": account.email.split("@", 1)[0],
        "email": account.email,
        "display_name": account.display_name,
    }


def project_target(project: CaseProject) -> dict:
    return {
        "target_type": project.target_type,
        "target_id": project.target_id,
        "target_key": project.target_key,
        "title": project.title,
        "linked_fr_ids": project.linked_fr_ids,
        "linked_qpm_ids": project.linked_qpm_ids,
    }


def get_playlist_creation_session(db: Session, session_id: UUID) -> PlaylistCreationSession:
    creation = db.get(PlaylistCreationSession, session_id)
    if creation is None:
        raise HTTPException(status_code=404, detail="playlist_creation_session_not_found")
    return creation


def resolve_collection_seeds(
    db: Session, project: CaseProject, seeds: list[CollectionSeed]
) -> list[dict]:
    resolved: list[dict] = []
    seen: set[UUID] = set()
    for seed in seeds:
        seed_project = get_project(db, seed.case_project_id) if seed.case_project_id else None
        if seed_project is not None and seed_project.space_id != project.space_id:
            raise HTTPException(status_code=422, detail="playlist_collection_space_mismatch")
        collection_id = seed.collection_id or (seed_project.collection_id if seed_project else None)
        if collection_id is None:
            raise HTTPException(status_code=422, detail="playlist_collection_not_found")
        collection = db.get(CaseCollection, collection_id)
        if (
            collection is None
            or collection.space_id != project.space_id
            or collection.deleted_at is not None
        ):
            raise HTTPException(status_code=422, detail="playlist_collection_not_found")
        if seed_project is not None and seed_project.collection_id != collection.id:
            raise HTTPException(status_code=422, detail="playlist_collection_project_mismatch")
        generation: CaseGenerationSession | None = None
        if seed.case_generation_id:
            generation = db.scalar(
                select(CaseGenerationSession)
                .join(CaseProject, CaseProject.id == CaseGenerationSession.case_project_id)
                .where(
                    CaseGenerationSession.public_id == seed.case_generation_id,
                    CaseProject.collection_id == collection.id,
                )
            )
            if generation is None or generation.status != "approved":
                raise HTTPException(status_code=422, detail="playlist_generation_not_approved")
        if collection.id in seen:
            continue
        seen.add(collection.id)
        resolved.append(
            {
                "collection_id": str(collection.id),
                "name": collection.name,
                "case_project_id": seed_project.public_id if seed_project else None,
                "case_generation_id": generation.public_id if generation else None,
            }
        )
    return resolved


def default_callback_url(name: str) -> str:
    return f"{settings.test_web_base_url.rstrip('/')}/api/case-service/callbacks/{name}"


def enqueue_callback(
    db: Session,
    event_type: str,
    aggregate_id: str,
    payload: dict,
    *,
    destination_url: str | None = None,
    subscribed_events: list[str] | None = None,
    correlation_id: str | None = None,
) -> UUID | None:
    if subscribed_events is not None and event_type not in subscribed_events:
        return None
    event_id = uuid4()
    callback_payload = {**payload, "event_id": str(event_id)}
    if correlation_id is not None:
        callback_payload["callback_correlation_id"] = correlation_id
    db.add(
        CallbackDelivery(
            event_id=event_id,
            event_type=event_type,
            aggregate_id=aggregate_id,
            callback_url=destination_url or default_callback_url(event_type),
            payload=callback_payload,
            status="pending",
            attempts=0,
            next_attempt_at=now(),
        )
    )
    return event_id


def case_rows(db: Session, project: CaseProject) -> list[tuple[TestCase, TestCaseRevision]]:
    return list(
        db.execute(
            select(TestCase, TestCaseRevision)
            .join(CollectionCaseMembership, CollectionCaseMembership.test_case_id == TestCase.id)
            .join(TestCaseRevision, TestCaseRevision.id == TestCase.current_revision_id)
            .where(
                CollectionCaseMembership.collection_id == project.collection_id,
                TestCase.deleted_at.is_(None),
            )
            .order_by(CollectionCaseMembership.position, TestCase.case_key)
        ).all()
    )


def generation_case_rows(
    db: Session, generation: CaseGenerationSession
) -> list[tuple[TestCase, TestCaseRevision]]:
    return list(
        db.execute(
            select(TestCase, TestCaseRevision)
            .join(CaseGenerationCase, CaseGenerationCase.test_case_id == TestCase.id)
            .join(TestCaseRevision, TestCaseRevision.id == CaseGenerationCase.revision_id)
            .where(CaseGenerationCase.case_generation_id == generation.id)
            .order_by(CaseGenerationCase.position, TestCase.case_key)
        ).all()
    )


def playlist_contract_detail(
    db: Session, playlist: Playlist, project: CaseProject, *, include_task: bool = True
) -> dict:
    creator = db.get(Account, playlist.creator_id)
    source_links = list(
        db.scalars(
            select(PlaylistSourceCollection)
            .where(PlaylistSourceCollection.playlist_id == playlist.id)
            .order_by(PlaylistSourceCollection.position)
        )
    )
    collections = [db.get(CaseCollection, link.collection_id) for link in source_links]
    case_rows_for_playlist = list(
        db.execute(
            select(TestCase, TestCaseRevision)
            .join(PlaylistCaseMembership, PlaylistCaseMembership.test_case_id == TestCase.id)
            .join(TestCaseRevision, TestCaseRevision.id == TestCase.current_revision_id)
            .where(PlaylistCaseMembership.playlist_id == playlist.id)
            .order_by(PlaylistCaseMembership.position)
        ).all()
    )
    task = None
    if include_task:
        task = db.scalar(
            select(IntegrationTask)
            .where(
                IntegrationTask.case_project_id == project.id,
                IntegrationTask.playlist_id == playlist.id,
            )
            .order_by(IntegrationTask.updated_at.desc())
        )
    task_summary = None
    if task is not None:
        detail = task_detail(db, task)
        completed = sum(
            item["status"] not in {"not_run", "running"} for item in detail["cases"].values()
        )
        total = len(detail["cases"])
        task_summary = {
            "test_task_id": task.public_id,
            "assignee": task.tester,
            "execution_status": task.status,
            "updated_at": task.updated_at.isoformat(),
            "progress": round(completed * 100 / total) if total else 0,
        }
    return {
        "playlist_id": str(playlist.id),
        "name": playlist.name,
        "creator": account_ref(creator) if creator else {},
        "test_target": project_target(project),
        "case_collections": [
            {
                "collection_id": str(link.collection_id),
                "name": collection.name if collection else "",
                "case_project_id": project.public_id
                if link.collection_id == project.collection_id
                else None,
                "case_generation_id": None,
            }
            for link, collection in zip(source_links, collections, strict=True)
        ],
        "cases": [
            {
                "case_id": test_case.case_key,
                "title": revision.title,
                "stage": revision.execution_level,
                "test_domain": revision.test_domains,
                "automation_type": revision.automation_type,
                "revision_id": str(revision.id),
            }
            for test_case, revision in case_rows_for_playlist
        ],
        "case_count": len(case_rows_for_playlist),
        "task": task_summary,
        "created_at": playlist.created_at.isoformat(),
        "updated_at": playlist.updated_at.isoformat(),
        "case_platform_url": platform_url(f"/playlists/{playlist.id}"),
    }


def case_snapshot(db: Session, project: CaseProject, generation: CaseGenerationSession) -> dict:
    cases = {
        test_case.case_key: {
            "stage": revision.execution_level,
            "test_domain": revision.test_domains,
            "title": revision.title,
            "automation_type": revision.automation_type,
        }
        for test_case, revision in generation_case_rows(db, generation)
    }
    return {
        "target_type": project.target_type,
        "target_id": project.target_id,
        "case_project_id": project.public_id,
        "case_platform_url": case_project_platform_url(project),
        "case_generation_id": generation.public_id,
        "generation_status": generation.status,
        "generation_updated_at": generation.updated_at.isoformat(),
        "cases": cases,
    }


MOCK_CASES = (
    ("L0", "验证核心成功路径", "Function", "manual"),
    ("L2", "验证异常输入与恢复路径", "Reliability", "automated"),
    ("L4", "验证长时间运行与跨系统回归", "Stability", "automated"),
)


def complete_mock_generation(generation_id: UUID) -> None:
    """Deterministic mock generation used by the documented integration contract."""
    with get_session_factory()() as db:
        generation = db.get(CaseGenerationSession, generation_id)
        if generation is None or generation.status != "generating":
            return
        project = db.get(CaseProject, generation.case_project_id)
        if project is None:
            return
        existing_cases = list(
            db.scalars(
                select(TestCase)
                .join(
                    CollectionCaseMembership,
                    CollectionCaseMembership.test_case_id == TestCase.id,
                )
                .where(CollectionCaseMembership.collection_id == project.collection_id)
            )
        )
        cases_by_key = {item.case_key: item for item in existing_cases}
        for test_case in existing_cases:
            test_case.deleted_at = now()
        for position, (level, title, domain, automation_type) in enumerate(MOCK_CASES, 1):
            case_key = f"{project.public_id}-CASE-{position:03d}"
            test_case = cases_by_key.get(case_key)
            if test_case is None:
                test_case = TestCase(space_id=project.space_id, case_key=case_key)
                db.add(test_case)
                db.flush()
                db.add(
                    CollectionCaseMembership(
                        collection_id=project.collection_id,
                        test_case_id=test_case.id,
                        position=position - 1,
                    )
                )
                revision_number = 1
            else:
                test_case.deleted_at = None
                revision_number = (
                    db.scalar(
                        select(func.max(TestCaseRevision.revision_number)).where(
                            TestCaseRevision.test_case_id == test_case.id
                        )
                    )
                    or 0
                ) + 1
            revision = TestCaseRevision(
                test_case_id=test_case.id,
                revision_number=revision_number,
                title=f"{project.target_key or project.title}：{title}",
                module=project.title,
                priority="P0" if level == "L0" else "P1",
                case_type="功能" if level != "L4" else "稳定性",
                tags=["integration-mock", level],
                preconditions=["目标环境可用", "TestTool 已完成用户绑定"],
                steps=[
                    {
                        "id": str(uuid4()),
                        "action": f"执行 {level} 阶段场景",
                        "expected": "结果符合需求",
                    }
                ],
                source_refs=[
                    {
                        "label": project.target_key or project.title,
                        "locator": f"{project.target_type}:{project.target_id}",
                        "excerpt": "Fixed integration mock prompt",
                    }
                ],
                execution_level=level,
                test_domains=[domain],
                automation_type=automation_type,
            )
            db.add(revision)
            db.flush()
            test_case.current_revision_id = revision.id
            db.add(
                CaseGenerationCase(
                    case_generation_id=generation.id,
                    test_case_id=test_case.id,
                    revision_id=revision.id,
                    position=position - 1,
                )
            )
        generation.status = "approved"
        generation.updated_at = now()
        db.flush()
        snapshot = case_snapshot(db, project, generation)
        enqueue_callback(
            db,
            "generation-status",
            generation.public_id,
            {
                "target_type": project.target_type,
                "target_id": project.target_id,
                "case_project_id": project.public_id,
                "case_generation_id": generation.public_id,
                "generation_status": "approved",
                "generation_updated_at": generation.updated_at.isoformat(),
                "case_platform_url": snapshot["case_platform_url"],
            },
            destination_url=generation.callback_url,
            subscribed_events=generation.callback_events,
            correlation_id=generation.callback_correlation_id,
        )
        enqueue_callback(
            db,
            "case-summary",
            generation.public_id,
            snapshot,
            destination_url=generation.callback_url,
            subscribed_events=generation.callback_events,
            correlation_id=generation.callback_correlation_id,
        )
        db.commit()


@router.post("/case-projects", status_code=201, response_model=CaseProjectResponse)
def create_case_project(
    payload: CaseProjectCreate,
    _: CaseServiceAuth,
    db: DbSession,
) -> dict:
    if payload.test_target.target_type not in {
        "fr_test",
        "qpm_test",
        "release_test",
        "regression_test",
        "sanity_test",
        "ad_hoc",
        "debug",
    }:
        raise HTTPException(status_code=422, detail="unsupported_target_type")
    space_id, account_id = choose_service_identity(db, payload.space_id)
    existing = db.scalar(
        select(CaseProject).where(
            CaseProject.space_id == space_id,
            CaseProject.source_system == payload.source_system,
            CaseProject.target_type == payload.test_target.target_type,
            CaseProject.target_id == payload.test_target.target_id,
        )
    )
    if existing is not None:
        return {
            "case_project_id": existing.public_id,
            "case_platform_url": case_project_platform_url(existing),
        }
    public_id = next_public_id(db, "case_project_public_id_seq", "CP-")
    collection = CaseCollection(
        space_id=space_id,
        name=payload.test_target.title,
        description=f"{payload.source_system}:{payload.test_target.target_type}:{payload.test_target.target_id}",
    )
    db.add(collection)
    db.flush()
    project = CaseProject(
        public_id=public_id,
        space_id=space_id,
        account_id=account_id,
        collection_id=collection.id,
        source_system=payload.source_system,
        target_type=payload.test_target.target_type,
        target_id=payload.test_target.target_id,
        target_key=payload.test_target.target_key,
        title=payload.test_target.title,
        linked_fr_ids=payload.test_target.linked_fr_ids,
        linked_qpm_ids=payload.test_target.linked_qpm_ids,
        test_context=payload.test_context,
    )
    db.add(project)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="case_project_conflict") from error
    return {
        "case_project_id": public_id,
        "case_platform_url": case_project_platform_url(project),
    }


@router.get(
    "/api/v1/case-projects/{case_project_id}",
    response_model=CaseProjectNavigationResponse,
)
def get_case_project_navigation(
    case_project_id: str,
    account: CurrentAccount,
    db: DbSession,
    access_token: str | None = Query(default=None, max_length=200),
) -> dict:
    project = get_project(db, case_project_id)
    membership = db.scalar(
        select(SpaceMembership).where(
            SpaceMembership.account_id == account.id,
            SpaceMembership.space_id == project.space_id,
        )
    )
    if membership is None:
        if not access_token or not validate_case_project_access_token(project, access_token):
            raise HTTPException(status_code=403, detail="space_access_denied")
        db.add(
            SpaceMembership(
                account_id=account.id,
                space_id=project.space_id,
                role="member",
            )
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    collection = db.get(CaseCollection, project.collection_id)
    if collection is None or collection.deleted_at is not None:
        raise HTTPException(status_code=404, detail="case_project_collection_not_found")
    return {
        "case_project_id": project.public_id,
        "space_id": project.space_id,
        "collection_id": project.collection_id,
        "title": project.title,
        "test_target": project_target(project),
    }


@router.post(
    "/case-projects/{case_project_id}/case-generation-jobs",
    status_code=202,
    response_model=GenerationResponse,
)
def start_case_generation(
    case_project_id: str,
    payload: GenerationStart,
    background_tasks: BackgroundTasks,
    _: CaseServiceAuth,
    db: DbSession,
) -> dict:
    project = get_project(db, case_project_id)
    if isinstance(payload.test_target, TestTarget):
        assert_target(project, payload.test_target)
    public_id = next_public_id(db, "generation_session_public_id_seq", "CASE-SESSION-")
    generation = CaseGenerationSession(
        public_id=public_id,
        case_project_id=project.id,
        status="generating",
        callback_url=str(payload.callback_url) if payload.callback_url else None,
        callback_events=list(payload.callback_events),
        callback_correlation_id=payload.callback_correlation_id,
        updated_at=now(),
    )
    db.add(generation)
    db.flush()
    project.test_context = {**project.test_context, **payload.test_context}
    if not settings.case_service_mock_mode:
        if not settings.is_agent_model_allowed(payload.model_id):
            raise HTTPException(status_code=422, detail="generation_model_not_configured")
        prompt = "\n".join(
            (
                settings.case_service_generation_prompt,
                "测试目标："
                + json.dumps(
                    {
                        "target_type": project.target_type,
                        "target_id": project.target_id,
                        "target_key": project.target_key,
                        "title": project.title,
                    },
                    ensure_ascii=False,
                ),
                "测试上下文：" + json.dumps(project.test_context, ensure_ascii=False),
            )
        )
        job = GenerationJob(
            space_id=project.space_id,
            account_id=project.account_id,
            operation="generate",
            collection_id=project.collection_id,
            status="queued",
            stage="queued",
            input_payload={
                "prompt": prompt,
                "markdown_content": "",
                "file_names": [],
                "mode": settings.ai_mode,
                "model_id": payload.model_id,
                "document_ids": [],
                "knowledge_source_ids": [],
                "use_space_knowledge": False,
                "answers": {},
                "persist_cases": False,
                "integration_generation_id": str(generation.id),
                "integration_case_project_id": str(project.id),
                "integration_project_public_id": project.public_id,
                "integration_callback_url": generation.callback_url,
                "integration_callback_events": generation.callback_events,
                "integration_callback_correlation_id": generation.callback_correlation_id,
                "integration_case_platform_url": platform_url(
                    f"/case-projects/{project.public_id}"
                ),
            },
            output_payload={},
        )
        db.add(job)
        db.flush()
        generation.generation_job_id = job.id
        enqueue_task(db, "casepilot.agent.generate", [str(job.id)], task_id=job.id)
    enqueue_callback(
        db,
        "generation-status",
        public_id,
        {
            "target_type": project.target_type,
            "target_id": project.target_id,
            "case_project_id": project.public_id,
            "case_generation_id": public_id,
            "generation_status": "generating",
            "generation_updated_at": generation.updated_at.isoformat(),
            "case_platform_url": case_project_platform_url(project),
        },
        destination_url=generation.callback_url,
        subscribed_events=generation.callback_events,
        correlation_id=generation.callback_correlation_id,
    )
    db.commit()
    if settings.case_service_mock_mode:
        background_tasks.add_task(complete_mock_generation, generation.id)
    return {
        "case_generation_id": public_id,
        "case_generation_status": "generating",
        "case_platform_url": case_project_platform_url(project),
        "callback_correlation_id": generation.callback_correlation_id,
    }


@router.get(
    "/case-projects/{case_project_id}/case-summary",
    response_model=CaseSummaryResponse,
)
def get_case_summary(case_project_id: str, _: CaseServiceAuth, db: DbSession) -> dict:
    project = get_project(db, case_project_id)
    generation = db.scalar(
        select(CaseGenerationSession)
        .where(CaseGenerationSession.case_project_id == project.id)
        .order_by(CaseGenerationSession.created_at.desc())
    )
    if generation is None:
        raise HTTPException(status_code=404, detail="case_generation_not_found")
    return case_snapshot(db, project, generation)


@router.post(
    "/case-projects/{case_project_id}/case-summary",
    response_model=CaseSummaryResponse,
)
def post_case_summary(case_project_id: str, _: CaseServiceAuth, db: DbSession) -> dict:
    return get_case_summary(case_project_id, None, db)


@router.get(
    "/case-projects/{case_project_id}/playlist-tasks",
    response_model=PlaylistTaskListResponse,
)
def list_playlist_tasks(
    case_project_id: str,
    _: CaseServiceAuth,
    db: DbSession,
    creator: str | None = None,
    target_type: str | None = None,
    target_id: int | None = Query(default=None, ge=1),
    collection_ids: Annotated[list[UUID] | None, Query(alias="collection_id")] = None,
    playlist_id: UUID | None = None,
    status_filter: Annotated[list[str] | None, Query(alias="status")] = None,
    cursor: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict:
    project = get_project(db, case_project_id)
    if target_type and target_type != project.target_type:
        return {"items": [], "next_cursor": None}
    if target_id is not None and target_id != project.target_id:
        return {"items": [], "next_cursor": None}
    query = (
        select(Playlist)
        .join(PlaylistSourceCollection, PlaylistSourceCollection.playlist_id == Playlist.id)
        .where(
            PlaylistSourceCollection.collection_id == project.collection_id,
            Playlist.deleted_at.is_(None),
        )
        .order_by(Playlist.updated_at.desc(), Playlist.id.desc())
    )
    if playlist_id:
        query = query.where(Playlist.id == playlist_id)
    if cursor:
        query = query.where(Playlist.id < cursor)
    if creator:
        try:
            creator_id = UUID(creator)
            query = query.where(Playlist.creator_id == creator_id)
        except ValueError:
            normalized_creator = creator.strip().lower()
            matching_creators = select(Account.id).where(
                or_(
                    func.lower(Account.email) == normalized_creator,
                    func.lower(Account.display_name) == normalized_creator,
                    func.lower(func.split_part(Account.email, "@", 1))
                    == normalized_creator,
                )
            )
            query = query.where(Playlist.creator_id.in_(matching_creators))
    if collection_ids:
        matching_playlist_ids = select(PlaylistSourceCollection.playlist_id).where(
            PlaylistSourceCollection.collection_id.in_(collection_ids)
        )
        query = query.where(Playlist.id.in_(matching_playlist_ids))
    if status_filter:
        latest_task_status = (
            select(IntegrationTask.status)
            .where(IntegrationTask.playlist_id == Playlist.id)
            .order_by(IntegrationTask.updated_at.desc(), IntegrationTask.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        status_conditions = []
        requested_statuses = [status for status in status_filter if status != "ready"]
        if requested_statuses:
            status_conditions.append(latest_task_status.in_(requested_statuses))
        if "ready" in status_filter:
            status_conditions.append(latest_task_status.is_(None))
        query = query.where(or_(*status_conditions))
    playlists = list(db.scalars(query.limit(limit + 1)).unique())
    details = [playlist_contract_detail(db, playlist, project) for playlist in playlists]
    has_more = len(details) > limit
    details = details[:limit]
    return {
        "items": details,
        "next_cursor": details[-1]["playlist_id"] if has_more and details else None,
    }


@router.post(
    "/case-projects/{case_project_id}/playlist-creation-sessions",
    status_code=201,
    response_model=PlaylistCreationResponse,
)
def start_playlist_creation(
    case_project_id: str,
    payload: PlaylistCreationStart,
    _: CaseServiceAuth,
    db: DbSession,
) -> dict:
    project = get_project(db, case_project_id)
    assert_target(project, payload.test_target)
    creator = resolve_tester(db, payload.creator, project.space_id)
    creation = PlaylistCreationSession(
        case_project_id=project.id,
        creator_id=creator.id,
        test_target=payload.test_target.model_dump(mode="json"),
        case_collections=resolve_collection_seeds(db, project, payload.case_collections),
        playlist_draft=payload.playlist.model_dump(mode="json"),
        callback_url=str(payload.callback_url),
        callback_events=list(payload.callback_events),
        callback_correlation_id=payload.callback_correlation_id,
        callback_context=payload.callback_context,
        status="pending_user_action",
        expires_at=now() + timedelta(seconds=payload.expires_in_seconds),
        updated_at=now(),
    )
    db.add(creation)
    db.commit()
    return {
        "playlist_creation_id": creation.id,
        "creation_status": creation.status,
        "case_platform_url": platform_url(f"/?playlist_creation_id={creation.id}"),
        "expires_at": creation.expires_at,
    }


def playlist_creation_view(
    db: Session, creation: PlaylistCreationSession
) -> dict:
    creator = db.get(Account, creation.creator_id)
    project = db.get(CaseProject, creation.case_project_id)
    return {
        "playlist_creation_id": creation.id,
        "space_id": project.space_id,
        "creation_status": creation.status,
        "creator": account_ref(creator) if creator else {},
        "test_target": creation.test_target,
        "case_collections": creation.case_collections,
        "playlist": creation.playlist_draft,
        "callback_url": creation.callback_url,
        "callback_events": creation.callback_events,
        "callback_correlation_id": creation.callback_correlation_id,
        "callback_context": creation.callback_context,
        "expires_at": creation.expires_at,
    }


@router.get(
    "/api/v1/playlist-creation-sessions/{playlist_creation_id}",
    response_model=PlaylistCreationSessionView,
)
def read_playlist_creation(
    playlist_creation_id: UUID, account: CurrentAccount, db: DbSession
) -> dict:
    creation = get_playlist_creation_session(db, playlist_creation_id)
    project = db.get(CaseProject, creation.case_project_id)
    require_space_membership(db, account.id, project.space_id)
    if creation.creator_id != account.id:
        raise HTTPException(status_code=403, detail="playlist_creator_mismatch")
    if creation.status == "pending_user_action" and creation.expires_at <= now():
        creation.status = "expired"
        creation.updated_at = now()
        enqueue_callback(
            db,
            "playlist-creation-expired",
            str(creation.id),
            {
                "playlist_creation_id": str(creation.id),
                "case_project_id": project.public_id,
                "test_target": creation.test_target,
                "expired_at": creation.updated_at.isoformat(),
                "callback_context": creation.callback_context,
            },
            destination_url=creation.callback_url,
            subscribed_events=creation.callback_events,
            correlation_id=creation.callback_correlation_id,
        )
        db.commit()
        raise HTTPException(status_code=410, detail="playlist_creation_session_expired")
    return playlist_creation_view(db, creation)


def resolve_playlist_case_ids(
    db: Session, creation: PlaylistCreationSession, case_ids: list[str]
) -> list[UUID]:
    source_collection_ids = {
        UUID(item["collection_id"]) for item in creation.case_collections
    }
    generation_ids = {
        item["case_generation_id"]
        for item in creation.case_collections
        if item.get("case_generation_id")
    }
    resolved: list[UUID] = []
    for case_id in dict.fromkeys(case_ids):
        try:
            test_case = db.get(TestCase, UUID(case_id))
        except ValueError:
            test_case = db.scalar(select(TestCase).where(TestCase.case_key == case_id))
        if (
            test_case is None
            or test_case.deleted_at is not None
            or test_case.current_revision_id is None
        ):
            raise HTTPException(status_code=422, detail=f"playlist_case_not_available:{case_id}")
        belongs_to_collection = db.scalar(
            select(CollectionCaseMembership.id).where(
                CollectionCaseMembership.test_case_id == test_case.id,
                CollectionCaseMembership.collection_id.in_(source_collection_ids),
            )
        )
        if belongs_to_collection is None:
            raise HTTPException(status_code=422, detail=f"playlist_case_out_of_scope:{case_id}")
        if generation_ids:
            in_snapshot = db.scalar(
                select(CaseGenerationCase.id)
                .join(
                    CaseGenerationSession,
                    CaseGenerationSession.id == CaseGenerationCase.case_generation_id,
                )
                .where(
                    CaseGenerationCase.test_case_id == test_case.id,
                    CaseGenerationSession.public_id.in_(generation_ids),
                )
            )
            if in_snapshot is None:
                raise HTTPException(
                    status_code=422, detail=f"playlist_case_outside_approved_snapshot:{case_id}"
                )
        resolved.append(test_case.id)
    return resolved


@router.post(
    "/api/v1/playlist-creation-sessions/{playlist_creation_id}/complete",
    status_code=201,
    response_model=PlaylistCreationCompleteResponse,
)
def complete_playlist_creation(
    playlist_creation_id: UUID,
    payload: PlaylistCreationComplete,
    account: CurrentAccount,
    db: DbSession,
) -> dict:
    creation = get_playlist_creation_session(db, playlist_creation_id)
    project = db.get(CaseProject, creation.case_project_id)
    require_space_membership(db, account.id, project.space_id)
    if creation.creator_id != account.id:
        raise HTTPException(status_code=403, detail="playlist_creator_mismatch")
    if creation.playlist_id is not None:
        playlist = db.get(Playlist, creation.playlist_id)
        detail = playlist_contract_detail(db, playlist, project, include_task=False)
        return {
            "playlist": detail,
            "creation_status": "created",
            "created_at": playlist.created_at,
            "case_platform_url": detail["case_platform_url"],
        }
    if creation.expires_at <= now():
        creation.status = "expired"
        creation.updated_at = now()
        db.commit()
        raise HTTPException(status_code=410, detail="playlist_creation_session_expired")
    case_ids = resolve_playlist_case_ids(db, creation, payload.case_ids)
    source_collection_ids = [
        UUID(item["collection_id"]) for item in creation.case_collections
    ]
    playlist = Playlist(
        space_id=project.space_id,
        creator_id=account.id,
        name=available_playlist_name(db, project.space_id, payload.name),
    )
    db.add(playlist)
    db.flush()
    replace_playlist_memberships(
        db,
        playlist=playlist,
        case_ids=case_ids,
        source_collection_ids=source_collection_ids,
    )
    creation.playlist_id = playlist.id
    creation.status = "created"
    creation.updated_at = now()
    creation.playlist_draft = {
        "name": playlist.name,
        "description": payload.description,
        "execution_notes": payload.execution_notes,
        "case_ids": payload.case_ids,
    }
    db.flush()
    detail = playlist_contract_detail(db, playlist, project, include_task=False)
    callback_payload = {
        "playlist_creation_id": str(creation.id),
        "case_project_id": project.public_id,
        "test_target": creation.test_target,
        "playlist": detail,
        "created_at": playlist.created_at.isoformat(),
        "case_platform_url": detail["case_platform_url"],
        "callback_context": creation.callback_context,
    }
    enqueue_callback(
        db,
        "playlist-created",
        str(creation.id),
        callback_payload,
        destination_url=creation.callback_url,
        subscribed_events=creation.callback_events,
        correlation_id=creation.callback_correlation_id,
    )
    db.commit()
    return {
        "playlist": detail,
        "creation_status": "created",
        "created_at": playlist.created_at,
        "case_platform_url": detail["case_platform_url"],
    }


@router.post(
    "/case-projects/{case_project_id}/tasks",
    status_code=202,
    response_model=TaskAckResponse,
)
def create_task_request(
    case_project_id: str,
    payload: TaskCreate,
    _: CaseServiceAuth,
    db: DbSession,
) -> dict:
    project = get_project(db, case_project_id)
    assert_target(project, payload.test_target)
    generation = get_generation(db, project, payload.case_generation_id)
    if generation.status != "approved":
        raise HTTPException(status_code=409, detail="case_generation_not_approved")
    existing = db.scalar(
        select(IntegrationTask).where(IntegrationTask.task_request_id == payload.task_request_id)
    )
    if existing is not None:
        if existing.case_project_id != project.id:
            raise HTTPException(status_code=409, detail="task_request_id_conflict")
        return task_ack(existing, project)
    rows = generation_case_rows(db, generation)
    if not rows:
        raise HTTPException(status_code=409, detail="approved_snapshot_empty")
    playlist = Playlist(
        space_id=project.space_id,
        creator_id=project.account_id,
        name=f"{project.target_key or project.title} execution",
    )
    db.add(playlist)
    db.flush()
    db.add(
        PlaylistSourceCollection(
            playlist_id=playlist.id, collection_id=project.collection_id, position=0
        )
    )
    for position, (test_case, _revision) in enumerate(rows):
        db.add(
            PlaylistCaseMembership(
                playlist_id=playlist.id, test_case_id=test_case.id, position=position
            )
        )
    task = IntegrationTask(
        public_id=next_public_id(db, "integration_task_public_id_seq", "TASK-"),
        task_request_id=payload.task_request_id,
        case_project_id=project.id,
        case_generation_id=generation.id,
        playlist_id=playlist.id,
        tester=payload.task_context.tester.strip().lower(),
        execution_notes=payload.task_context.execution_notes,
        task_context={**payload.test_context},
        callback_url=str(payload.callback_url) if payload.callback_url else None,
        callback_events=list(payload.callback_events),
        callback_correlation_id=payload.callback_correlation_id,
        selected_level=payload.task_context.execution_level,
        status="pending_confirmation",
        updated_at=now(),
    )
    db.add(task)
    db.commit()
    return task_ack(task, project)


def task_ack(task: IntegrationTask, project: CaseProject) -> dict:
    return {
        "task_request_id": str(task.task_request_id),
        "test_task_id": task.public_id,
        "execution_status": task.status,
        "case_platform_url": platform_url(
            f"/playlists/{task.playlist_id}?task_request_id={task.task_request_id}&case_project_id={project.public_id}"
        ),
    }


def get_task_by_request(db: Session, task_request_id: UUID) -> IntegrationTask:
    task = db.scalar(
        select(IntegrationTask).where(IntegrationTask.task_request_id == task_request_id)
    )
    if task is None:
        raise HTTPException(status_code=404, detail="task_request_not_found")
    return task


def task_detail(db: Session, task: IntegrationTask, *, include_lease: bool = False) -> dict:
    project = db.get(CaseProject, task.case_project_id)
    generation = db.get(CaseGenerationSession, task.case_generation_id)
    records: list[tuple[ExecutionRecord, TestCase, TestCaseRevision]] = []
    if task.execution_run_id:
        records = list(
            db.execute(
                select(ExecutionRecord, TestCase, TestCaseRevision)
                .join(TestCase, TestCase.id == ExecutionRecord.test_case_id)
                .join(TestCaseRevision, TestCaseRevision.id == ExecutionRecord.revision_id)
                .where(ExecutionRecord.run_id == task.execution_run_id)
                .order_by(TestCase.case_key)
            ).all()
        )
    cases = {
        case.case_key: {
            "case_id": case.case_key,
            "title": revision.title,
            "stage": revision.execution_level,
            "test_domain": revision.test_domains,
            "automation_type": revision.automation_type,
            "preconditions": revision.preconditions,
            "steps": revision.steps,
            "status": record.status.value,
            "actual_result": record.actual_result,
            "completed_step_ids": record.completed_step_ids,
            "defect_ref": record.defect_ref,
            "logs": record.logs,
            "artifacts": record.artifacts,
            "updated_at": record.updated_at.isoformat(),
        }
        for record, case, revision in records
    }
    result = {
        "test_task_id": task.public_id,
        "task_request_id": str(task.task_request_id),
        "case_project_id": project.public_id,
        "case_generation_id": generation.public_id,
        "target_type": project.target_type,
        "target_id": project.target_id,
        "target_key": project.target_key,
        "task_name": f"{project.target_key or project.title} execution",
        "tester": task.tester,
        "execution_notes": task.execution_notes,
        "execution_level": task.selected_level,
        "execution_status": task.status,
        "updated_at": task.updated_at.isoformat(),
        "cases_complete": task.execution_run_id is not None,
        "cases": cases,
        "logs": task.logs,
        "artifacts": task.artifacts,
        "case_platform_url": platform_url(f"/playlists/{task.playlist_id}"),
    }
    if include_lease:
        lease = db.scalar(select(TestToolLease).where(TestToolLease.integration_task_id == task.id))
        result["lease_expires_at"] = lease.expires_at.isoformat() if lease else None
    return result


@router.get(
    "/api/v1/integration-task-requests/{task_request_id}",
    response_model=TaskDetailResponse,
)
def get_integration_task_request(
    task_request_id: UUID, account: CurrentAccount, db: DbSession
) -> dict:
    task = get_task_by_request(db, task_request_id)
    project = db.get(CaseProject, task.case_project_id)
    require_space_membership(db, account.id, project.space_id)
    return task_detail(db, task)


LEVELS = {"L0": {"L0"}, "L2": {"L0", "L2"}, "L4": {"L0", "L2", "L4"}}


def resolve_tester(db: Session, tester: str, space_id: UUID) -> Account:
    try:
        account = db.get(Account, UUID(tester))
    except ValueError:
        normalized_tester = tester.strip().lower()
        account = db.scalar(
            select(Account)
            .join(SpaceMembership, SpaceMembership.account_id == Account.id)
            .where(
                SpaceMembership.space_id == space_id,
                or_(
                    func.lower(Account.email) == normalized_tester,
                    func.lower(Account.display_name) == normalized_tester,
                    func.lower(func.split_part(Account.email, "@", 1)) == normalized_tester,
                ),
            )
            .order_by(Account.email)
            .limit(1)
        )
    if account is None:
        raise HTTPException(status_code=422, detail="tester_not_bound")
    require_space_membership(db, account.id, space_id)
    return account


@router.post(
    "/api/v1/integration-task-requests/{task_request_id}/confirm",
    response_model=TaskDetailResponse,
)
def confirm_integration_task(
    task_request_id: UUID,
    payload: TaskConfirm,
    account: CurrentAccount,
    db: DbSession,
) -> dict:
    task = get_task_by_request(db, task_request_id)
    project = db.get(CaseProject, task.case_project_id)
    require_space_membership(db, account.id, project.space_id)
    if task.execution_run_id:
        return task_detail(db, task)
    level = payload.execution_level or task.selected_level
    tester = resolve_tester(db, task.tester, project.space_id)
    generation = db.get(CaseGenerationSession, task.case_generation_id)
    selected_rows = [
        (case, revision)
        for case, revision in generation_case_rows(db, generation)
        if revision.execution_level in LEVELS[level]
    ]
    cases = [case for case, _revision in selected_rows]
    if not cases:
        raise HTTPException(status_code=409, detail="selected_execution_level_empty")
    existing_run = db.scalar(
        select(ExecutionRun)
        .where(ExecutionRun.playlist_id == task.playlist_id)
        .order_by(ExecutionRun.created_at.desc())
    )
    if existing_run is None:
        run_view = create_execution_run_from_cases(
            db,
            account=account,
            payload=ExecutionRunCreate(
                description=task.execution_notes or "TestWeb integration task",
                assignee_ids=[tester.id],
            ),
            space_id=project.space_id,
            cases=cases,
            collection_id=project.collection_id,
            playlist_id=task.playlist_id,
            source_type="playlist",
            source_name=f"{project.target_key or project.title} execution",
            source_collection_count=1,
            revision_ids={case.id: revision.id for case, revision in selected_rows},
        )
        execution_run_id = run_view.id
    else:
        execution_run_id = existing_run.id
    task = get_task_by_request(db, task_request_id)
    task.execution_run_id = execution_run_id
    task.selected_level = level
    task.status = "confirmed"
    task.updated_at = now()
    db.flush()
    callback_payload = task_callback_payload(db, task)
    enqueue_callback(
        db,
        "task-status",
        task.public_id,
        callback_payload,
        destination_url=task.callback_url,
        subscribed_events=task.callback_events,
        correlation_id=task.callback_correlation_id,
    )
    enqueue_callback(
        db,
        "case-execution-status",
        task.public_id,
        callback_payload,
        destination_url=task.callback_url,
        subscribed_events=task.callback_events,
        correlation_id=task.callback_correlation_id,
    )
    db.commit()
    return task_detail(db, task)


def task_callback_payload(db: Session, task: IntegrationTask) -> dict:
    detail = task_detail(db, task)
    return {
        "target_type": detail["target_type"],
        "target_id": detail["target_id"],
        "task": {
            "task_id": detail["test_task_id"],
            "task_request_id": detail["task_request_id"],
            "task_name": detail["task_name"],
            "tester": detail["tester"],
            "status": detail["execution_status"],
            "updated_at": detail["updated_at"],
            "cases_complete": True,
            "cases": {
                case_id: {
                    "status": item["status"],
                    "updated_at": item["updated_at"],
                    "jira": item["defect_ref"]
                    if not item["defect_ref"].upper().startswith("CR")
                    else "",
                    "cr": item["defect_ref"] if item["defect_ref"].upper().startswith("CR") else "",
                }
                for case_id, item in detail["cases"].items()
            },
        },
    }


def assert_task_owner(task: IntegrationTask, account: Account) -> None:
    if task.tester not in {account.email.lower(), str(account.id).lower()}:
        raise HTTPException(status_code=403, detail="task_not_assigned_to_current_user")


@router.get("/api/test-tool/v1/tasks", response_model=TaskListResponse)
def list_test_tool_tasks(
    account: TestToolAccount,
    db: DbSession,
    status_filter: Annotated[list[str] | None, Query(alias="status")] = None,
    target_type: str | None = None,
    target_id: int | None = None,
    case_project_id: str | None = None,
    case_generation_id: str | None = None,
    case_id: str | None = None,
    task_request_id: UUID | None = None,
    updated_after: datetime | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict:
    query = (
        select(IntegrationTask)
        .join(CaseProject, CaseProject.id == IntegrationTask.case_project_id)
        .join(CaseGenerationSession, CaseGenerationSession.id == IntegrationTask.case_generation_id)
        .where(
            IntegrationTask.execution_run_id.is_not(None),
            IntegrationTask.tester.in_([account.email.lower(), str(account.id).lower()]),
        )
        .order_by(IntegrationTask.updated_at.desc(), IntegrationTask.public_id.desc())
    )
    if status_filter:
        query = query.where(IntegrationTask.status.in_(status_filter))
    if target_type:
        query = query.where(CaseProject.target_type == target_type)
    if target_id is not None:
        query = query.where(CaseProject.target_id == target_id)
    if case_project_id:
        query = query.where(CaseProject.public_id == case_project_id)
    if case_generation_id:
        query = query.where(CaseGenerationSession.public_id == case_generation_id)
    if task_request_id:
        query = query.where(IntegrationTask.task_request_id == task_request_id)
    if updated_after:
        query = query.where(IntegrationTask.updated_at > updated_after)
    if cursor:
        query = query.where(IntegrationTask.public_id < cursor)
    if case_id:
        query = (
            query.join(ExecutionRecord, ExecutionRecord.run_id == IntegrationTask.execution_run_id)
            .join(TestCase, TestCase.id == ExecutionRecord.test_case_id)
            .where(TestCase.case_key == case_id)
        )
    tasks = list(db.scalars(query.limit(limit + 1)).unique())
    has_more = len(tasks) > limit
    tasks = tasks[:limit]
    return {
        "items": [task_detail(db, task, include_lease=True) for task in tasks],
        "next_cursor": tasks[-1].public_id if has_more else None,
    }


def get_test_tool_task(db: Session, test_task_id: str, account: Account) -> IntegrationTask:
    task = db.scalar(select(IntegrationTask).where(IntegrationTask.public_id == test_task_id))
    if task is None or task.execution_run_id is None:
        raise HTTPException(status_code=404, detail="test_task_not_found")
    assert_task_owner(task, account)
    return task


@router.get("/api/test-tool/v1/tasks/{test_task_id}", response_model=TaskDetailResponse)
def get_test_tool_task_detail(test_task_id: str, account: TestToolAccount, db: DbSession) -> dict:
    return task_detail(db, get_test_tool_task(db, test_task_id, account), include_lease=True)


@router.get(
    "/api/test-tool/v1/tasks/{test_task_id}/cases/{case_id}",
    response_model=TaskCaseResponse,
)
def get_test_tool_case(
    test_task_id: str, case_id: str, account: TestToolAccount, db: DbSession
) -> dict:
    task = get_test_tool_task(db, test_task_id, account)
    case = task_detail(db, task)["cases"].get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="task_case_not_found")
    return case


def claim_task(db: Session, task: IntegrationTask, account: Account, payload: ClaimRequest) -> dict:
    current = now()
    lease = db.scalar(
        select(TestToolLease).where(TestToolLease.integration_task_id == task.id).with_for_update()
    )
    if lease is not None and lease.expires_at > current and lease.account_id != account.id:
        raise HTTPException(status_code=409, detail="task_already_claimed")
    token = secrets.token_urlsafe(32)
    expires_at = current + timedelta(
        seconds=payload.lease_seconds or settings.test_tool_lease_seconds
    )
    if lease is None:
        lease = TestToolLease(
            integration_task_id=task.id,
            account_id=account.id,
            worker_id=payload.worker_id,
            lease_token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=expires_at,
            updated_at=current,
        )
        db.add(lease)
    else:
        lease.account_id = account.id
        lease.worker_id = payload.worker_id
        lease.lease_token_hash = hashlib.sha256(token.encode()).hexdigest()
        lease.expires_at = expires_at
        lease.updated_at = current
    task.status = "running"
    task.updated_at = current
    db.flush()
    enqueue_callback(
        db,
        "task-status",
        task.public_id,
        task_callback_payload(db, task),
        destination_url=task.callback_url,
        subscribed_events=task.callback_events,
        correlation_id=task.callback_correlation_id,
    )
    db.commit()
    return {**task_detail(db, task, include_lease=True), "lease_token": token}


@router.post("/api/test-tool/v1/tasks/claim", response_model=ClaimResponse)
def claim_next_task(payload: ClaimRequest, account: TestToolAccount, db: DbSession) -> dict:
    current = now()
    task = db.scalar(
        select(IntegrationTask)
        .outerjoin(TestToolLease, TestToolLease.integration_task_id == IntegrationTask.id)
        .where(
            IntegrationTask.execution_run_id.is_not(None),
            IntegrationTask.status.in_(["confirmed", "running"]),
            IntegrationTask.tester.in_([account.email.lower(), str(account.id).lower()]),
            or_(TestToolLease.id.is_(None), TestToolLease.expires_at <= current),
        )
        .order_by(IntegrationTask.created_at)
        .with_for_update(skip_locked=True)
    )
    if task is None:
        raise HTTPException(status_code=404, detail="no_claimable_task")
    return claim_task(db, task, account, payload)


@router.post("/api/test-tool/v1/tasks/{test_task_id}/claim", response_model=ClaimResponse)
def claim_named_task(
    test_task_id: str, payload: ClaimRequest, account: TestToolAccount, db: DbSession
) -> dict:
    return claim_task(db, get_test_tool_task(db, test_task_id, account), account, payload)


def validate_lease(
    db: Session, task: IntegrationTask, account: Account, token: str
) -> TestToolLease:
    lease = db.scalar(select(TestToolLease).where(TestToolLease.integration_task_id == task.id))
    digest = hashlib.sha256(token.encode()).hexdigest()
    if (
        lease is None
        or lease.account_id != account.id
        or lease.expires_at <= now()
        or not secrets.compare_digest(lease.lease_token_hash, digest)
    ):
        raise HTTPException(status_code=409, detail="invalid_or_expired_lease")
    return lease


@router.post(
    "/api/test-tool/v1/tasks/{test_task_id}/heartbeat",
    response_model=HeartbeatResponse,
)
def heartbeat_task(
    test_task_id: str,
    payload: ClaimRequest,
    account: TestToolAccount,
    db: DbSession,
    x_lease_token: Annotated[str | None, Header()] = None,
) -> dict:
    task = get_test_tool_task(db, test_task_id, account)
    lease = validate_lease(db, task, account, x_lease_token or "")
    lease.worker_id = payload.worker_id
    lease.expires_at = now() + timedelta(
        seconds=payload.lease_seconds or settings.test_tool_lease_seconds
    )
    lease.updated_at = now()
    db.commit()
    return {"test_task_id": task.public_id, "lease_expires_at": lease.expires_at.isoformat()}


@router.patch("/api/test-tool/v1/tasks/{test_task_id}", response_model=TaskDetailResponse)
def update_test_tool_task(
    test_task_id: str,
    payload: TaskExecutionUpdate,
    account: TestToolAccount,
    db: DbSession,
) -> dict:
    task = get_test_tool_task(db, test_task_id, account)
    previous = db.get(IntegrationUpdate, payload.update_id)
    if previous is not None:
        return previous.response_payload
    validate_lease(db, task, account, payload.lease_token)
    if payload.updated_at <= task.updated_at:
        raise HTTPException(status_code=409, detail="stale_task_update")
    rows = list(
        db.execute(
            select(ExecutionRecord, TestCase)
            .join(TestCase, TestCase.id == ExecutionRecord.test_case_id)
            .where(ExecutionRecord.run_id == task.execution_run_id)
        ).all()
    )
    records = {case.case_key: record for record, case in rows}
    if payload.cases_complete and set(payload.cases) != set(records):
        raise HTTPException(status_code=422, detail="cases_must_be_complete_snapshot")
    aliases = {"pass": "passed", "fail": "failed"}
    for case_id, update in payload.cases.items():
        record = records.get(case_id)
        if record is None:
            raise HTTPException(status_code=422, detail=f"unknown_case_id:{case_id}")
        if update.updated_at <= record.updated_at:
            continue
        record.status = ExecutionStatus(aliases.get(update.status, update.status))
        record.updated_at = update.updated_at
        record.actual_result = update.actual_result
        record.completed_step_ids = update.completed_step_ids
        record.defect_ref = update.cr or update.jira
        record.logs = update.logs
        record.artifacts = update.artifacts
        record.updated_by_id = account.id
    task.status = payload.status
    task.updated_at = payload.updated_at
    task.logs = payload.logs
    task.artifacts = payload.artifacts
    run = db.get(ExecutionRun, task.execution_run_id)
    if payload.status in {"completed", "failed", "cancelled"}:
        run.status = payload.status
        run.completed_at = payload.updated_at
    db.flush()
    callback_payload = task_callback_payload(db, task)
    enqueue_callback(
        db,
        "task-status",
        task.public_id,
        callback_payload,
        destination_url=task.callback_url,
        subscribed_events=task.callback_events,
        correlation_id=task.callback_correlation_id,
    )
    enqueue_callback(
        db,
        "case-execution-status",
        task.public_id,
        callback_payload,
        destination_url=task.callback_url,
        subscribed_events=task.callback_events,
        correlation_id=task.callback_correlation_id,
    )
    response = task_detail(db, task, include_lease=True)
    db.add(
        IntegrationUpdate(
            update_id=payload.update_id, integration_task_id=task.id, response_payload=response
        )
    )
    db.commit()
    return response
