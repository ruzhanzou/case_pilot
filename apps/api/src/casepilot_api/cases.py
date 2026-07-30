from typing import Annotated
from uuid import UUID, uuid4

from celery import Celery
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from casepilot_api.auth import CurrentAccount, require_space_membership
from casepilot_api.case_management import case_to_view, ensure_case, write_audit
from casepilot_api.config import get_settings
from casepilot_api.database import get_db_session
from casepilot_api.models import (
    CandidateRevision,
    GenerationJob,
    TestCase,
    TestCaseRevision,
)
from casepilot_api.schemas import (
    CandidateCreate,
    CandidateJobView,
    CandidateView,
    TestCaseView,
)

router = APIRouter(prefix="/api/v1", tags=["candidate-revisions"])
DbSession = Annotated[Session, Depends(get_db_session)]
settings = get_settings()
task_client = Celery(
    "casepilot-api-candidates",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)


def get_current_revision(db: Session, test_case: TestCase) -> TestCaseRevision:
    if test_case.current_revision_id is None:
        raise HTTPException(status_code=409, detail="test_case_has_no_revision")
    revision = db.scalar(
        select(TestCaseRevision).where(
            TestCaseRevision.id == test_case.current_revision_id,
            TestCaseRevision.test_case_id == test_case.id,
        )
    )
    if revision is None:
        raise HTTPException(status_code=409, detail="test_case_revision_not_found")
    return revision


@router.post(
    "/test-cases/{case_id}/candidate-revisions",
    response_model=CandidateJobView,
    status_code=202,
)
def create_candidate(
    case_id: UUID,
    payload: CandidateCreate,
    account: CurrentAccount,
    db: DbSession,
) -> CandidateJobView:
    if not settings.is_agent_model_allowed(payload.model_id):
        raise HTTPException(status_code=422, detail="generation_model_not_configured")
    test_case = ensure_case(db, account, case_id)
    revision = get_current_revision(db, test_case)
    if revision.id != payload.base_revision_id:
        raise HTTPException(status_code=409, detail="revision_conflict")
    job = GenerationJob(
        space_id=test_case.space_id,
        account_id=account.id,
        operation="rewrite",
        status="queued",
        stage="queued",
        input_payload={
            "case_id": str(test_case.id),
            "base_revision_id": str(revision.id),
            "instruction": payload.instruction,
            "model_id": payload.model_id,
        },
        output_payload={},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    task_client.send_task("casepilot.agent.rewrite", args=[str(job.id)])
    return CandidateJobView(job_id=job.id)


def get_candidate_access(
    db: Session,
    account_id: UUID,
    candidate_id: UUID,
) -> tuple[CandidateRevision, TestCase]:
    row = db.execute(
        select(CandidateRevision, TestCase)
        .join(TestCase, TestCase.id == CandidateRevision.test_case_id)
        .where(CandidateRevision.id == candidate_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="candidate_not_found")
    candidate, test_case = row
    require_space_membership(db, account_id, test_case.space_id)
    return candidate, test_case


@router.get(
    "/candidate-revisions/{candidate_id}",
    response_model=CandidateView,
)
def get_candidate(
    candidate_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> CandidateView:
    candidate, _ = get_candidate_access(db, account.id, candidate_id)
    return CandidateView.model_validate(candidate, from_attributes=True)


@router.post(
    "/candidate-revisions/{candidate_id}/apply",
    response_model=TestCaseView,
)
def apply_candidate(
    candidate_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> TestCaseView:
    candidate, test_case = get_candidate_access(db, account.id, candidate_id)
    if candidate.status == "applied":
        return case_to_view(db, test_case)
    if candidate.status != "pending":
        raise HTTPException(status_code=409, detail="candidate_not_pending")
    db.refresh(test_case, with_for_update=True)
    if test_case.current_revision_id != candidate.base_revision_id:
        raise HTTPException(status_code=409, detail="revision_conflict")

    snapshot = candidate.proposed_snapshot
    latest_number = db.scalar(
        select(func.max(TestCaseRevision.revision_number)).where(
            TestCaseRevision.test_case_id == test_case.id
        )
    ) or 0
    revision = TestCaseRevision(
        test_case_id=test_case.id,
        revision_number=latest_number + 1,
        title=str(snapshot["title"]).strip(),
        module=str(snapshot.get("module", "")).strip(),
        priority=str(snapshot.get("priority", "P1")),
        case_type=str(snapshot.get("case_type", "功能")).strip(),
        tags=list(snapshot.get("tags", [])),
        preconditions=list(snapshot.get("preconditions", [])),
        steps=[
            {
                "id": str(step.get("id") or uuid4()),
                "action": str(step["action"]).strip(),
                "expected": str(step["expected"]).strip(),
            }
            for step in snapshot.get("steps", [])
        ],
        source_refs=list(snapshot.get("source_refs", [])),
    )
    db.add(revision)
    db.flush()
    test_case.current_revision_id = revision.id
    candidate.status = "applied"
    write_audit(
        db,
        space_id=test_case.space_id,
        actor_id=account.id,
        action="candidate_revision.applied",
        resource_type="test_case",
        resource_id=test_case.id,
        payload={
            "candidate_id": str(candidate.id),
            "revision_id": str(revision.id),
        },
    )
    db.commit()
    db.refresh(test_case)
    return case_to_view(db, test_case)


@router.post(
    "/candidate-revisions/{candidate_id}/reject",
    response_model=CandidateView,
)
def reject_candidate(
    candidate_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> CandidateView:
    candidate, test_case = get_candidate_access(db, account.id, candidate_id)
    if candidate.status == "pending":
        candidate.status = "rejected"
        write_audit(
            db,
            space_id=test_case.space_id,
            actor_id=account.id,
            action="candidate_revision.rejected",
            resource_type="test_case",
            resource_id=test_case.id,
            payload={"candidate_id": str(candidate.id)},
        )
        db.commit()
    return CandidateView.model_validate(candidate, from_attributes=True)
