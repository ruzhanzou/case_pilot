from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from casepilot_api.auth import CurrentAccount, normalize_email, require_space_membership
from casepilot_api.database import get_db_session
from casepilot_api.models import (
    Account,
    AuditEvent,
    CaseCollection,
    CollectionCaseMembership,
    Conversation,
    ExecutionRecord,
    ExecutionRun,
    ExecutionRunAssignee,
    ExecutionStatus,
    SpaceMembership,
    TestCase,
    TestCaseRevision,
)
from casepilot_api.schemas import (
    CaseCollectionCreate,
    CaseCollectionUpdate,
    CaseCollectionView,
    ExecutionRecordReassign,
    ExecutionRecordUpdate,
    ExecutionRecordView,
    ExecutionRunCreate,
    ExecutionRunSummaryView,
    ExecutionRunUpdate,
    ExecutionRunView,
    SpaceMemberAdd,
    SpaceMemberView,
    TestCaseBatchCreate,
    TestCaseCreate,
    TestCaseUpdate,
    TestCaseView,
)

router = APIRouter(prefix="/api/v1", tags=["case-management"])
DbSession = Annotated[Session, Depends(get_db_session)]


def normalize_tags(tags: list[str]) -> list[str]:
    result: list[str] = []
    for tag in tags:
        normalized = tag.strip()[:32]
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def normalize_steps(steps: list) -> list[dict[str, str]]:
    return [
        {
            "id": step.id or str(uuid4()),
            "action": step.action.strip(),
            "expected": step.expected.strip(),
        }
        for step in steps
    ]


def validate_execution_record_update(
    payload: ExecutionRecordUpdate,
    valid_step_ids: set[str],
) -> None:
    completed_step_ids = set(payload.completed_step_ids)
    status = payload.status.value
    if not completed_step_ids.issubset(valid_step_ids):
        raise HTTPException(status_code=422, detail="invalid_execution_step")
    if (
        status
        in {
            ExecutionStatus.FAILED.value,
            ExecutionStatus.SKIPPED.value,
            ExecutionStatus.BLOCKED.value,
        }
        and not payload.actual_result.strip()
    ):
        raise HTTPException(
            status_code=422,
            detail="execution_result_reason_required",
        )


def create_test_case_record(
    db: Session,
    *,
    collection: CaseCollection,
    payload: TestCaseCreate,
    account: Account,
    case_key: str,
    position: int,
) -> TestCase:
    test_case = TestCase(space_id=collection.space_id, case_key=case_key)
    db.add(test_case)
    db.flush()
    revision = TestCaseRevision(
        test_case_id=test_case.id,
        revision_number=1,
        title=payload.title.strip(),
        module=payload.module.strip(),
        priority=payload.priority,
        case_type=payload.case_type.strip(),
        tags=normalize_tags(payload.tags),
        preconditions=[item.strip() for item in payload.preconditions if item.strip()],
        steps=normalize_steps(payload.steps),
        source_refs=(
            [item.model_dump(mode="json") for item in payload.source_refs]
            or [{"label": payload.source.strip(), "excerpt": ""}]
        ),
    )
    db.add(revision)
    db.flush()
    test_case.current_revision_id = revision.id
    db.add(
        CollectionCaseMembership(
            collection_id=collection.id,
            test_case_id=test_case.id,
            position=position,
        )
    )
    write_audit(
        db,
        space_id=collection.space_id,
        actor_id=account.id,
        action="test_case.created",
        resource_type="test_case",
        resource_id=test_case.id,
        payload={"case_key": case_key},
    )
    return test_case


def write_audit(
    db: Session,
    *,
    space_id: UUID,
    actor_id: UUID,
    action: str,
    resource_type: str,
    resource_id: UUID,
    payload: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            space_id=space_id,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=payload or {},
        )
    )


def ensure_collection(
    db: Session,
    account: Account,
    collection_id: UUID,
) -> CaseCollection:
    collection = db.scalar(
        select(CaseCollection).where(
            CaseCollection.id == collection_id,
            CaseCollection.deleted_at.is_(None),
        )
    )
    if collection is None:
        raise HTTPException(status_code=404, detail="collection_not_found")
    require_space_membership(db, account.id, collection.space_id)
    return collection


def require_space_owner(
    db: Session,
    account_id: UUID,
    space_id: UUID,
) -> SpaceMembership:
    membership = require_space_membership(db, account_id, space_id)
    if membership.role != "owner":
        raise HTTPException(status_code=403, detail="space_owner_required")
    return membership


def space_member_view(
    account: Account,
    membership: SpaceMembership,
) -> SpaceMemberView:
    return SpaceMemberView(
        account_id=account.id,
        email=account.email,
        display_name=account.display_name,
        role=membership.role,
        created_at=membership.created_at,
    )


@router.get("/spaces/{space_id}/members", response_model=list[SpaceMemberView])
def list_space_members(
    space_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> list[SpaceMemberView]:
    require_space_membership(db, account.id, space_id)
    rows = db.execute(
        select(Account, SpaceMembership)
        .join(SpaceMembership, SpaceMembership.account_id == Account.id)
        .where(SpaceMembership.space_id == space_id)
        .order_by(
            SpaceMembership.role.desc(),
            SpaceMembership.created_at,
            Account.display_name,
        )
    ).all()
    return [
        space_member_view(member, membership)
        for member, membership in rows
    ]


@router.post(
    "/spaces/{space_id}/members",
    response_model=SpaceMemberView,
    status_code=201,
)
def add_space_member(
    space_id: UUID,
    payload: SpaceMemberAdd,
    account: CurrentAccount,
    db: DbSession,
) -> SpaceMemberView:
    require_space_owner(db, account.id, space_id)
    member = db.scalar(
        select(Account).where(Account.email == normalize_email(payload.email))
    )
    if member is None or not member.is_active:
        raise HTTPException(status_code=404, detail="registered_account_not_found")
    existing = db.scalar(
        select(SpaceMembership).where(
            SpaceMembership.space_id == space_id,
            SpaceMembership.account_id == member.id,
        )
    )
    if existing is not None:
        return space_member_view(member, existing)
    membership = SpaceMembership(
        space_id=space_id,
        account_id=member.id,
        role="member",
    )
    db.add(membership)
    db.flush()
    write_audit(
        db,
        space_id=space_id,
        actor_id=account.id,
        action="space_member.added",
        resource_type="account",
        resource_id=member.id,
        payload={"email": member.email},
    )
    db.commit()
    db.refresh(membership)
    return space_member_view(member, membership)


@router.delete("/spaces/{space_id}/members/{member_id}", status_code=204)
def remove_space_member(
    space_id: UUID,
    member_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> Response:
    require_space_owner(db, account.id, space_id)
    membership = db.scalar(
        select(SpaceMembership).where(
            SpaceMembership.space_id == space_id,
            SpaceMembership.account_id == member_id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="space_member_not_found")
    if membership.role == "owner":
        raise HTTPException(status_code=409, detail="space_owner_cannot_be_removed")
    active_assignments = db.scalar(
        select(func.count(ExecutionRecord.id))
        .join(ExecutionRun, ExecutionRun.id == ExecutionRecord.run_id)
        .where(
            ExecutionRun.space_id == space_id,
            ExecutionRun.status == "active",
            ExecutionRecord.assignee_id == member_id,
        )
    )
    if active_assignments:
        raise HTTPException(status_code=409, detail="member_has_active_assignments")
    db.delete(membership)
    write_audit(
        db,
        space_id=space_id,
        actor_id=account.id,
        action="space_member.removed",
        resource_type="account",
        resource_id=member_id,
    )
    db.commit()
    return Response(status_code=204)


def ensure_case(db: Session, account: Account, case_id: UUID) -> TestCase:
    test_case = db.scalar(
        select(TestCase).where(
            TestCase.id == case_id,
            TestCase.deleted_at.is_(None),
        )
    )
    if test_case is None:
        raise HTTPException(status_code=404, detail="test_case_not_found")
    require_space_membership(db, account.id, test_case.space_id)
    return test_case


def collection_to_view(db: Session, collection: CaseCollection) -> CaseCollectionView:
    case_count = db.scalar(
        select(func.count(CollectionCaseMembership.id))
        .join(TestCase, TestCase.id == CollectionCaseMembership.test_case_id)
        .where(
            CollectionCaseMembership.collection_id == collection.id,
            TestCase.deleted_at.is_(None),
        )
    )
    return CaseCollectionView(
        id=collection.id,
        space_id=collection.space_id,
        name=collection.name,
        description=collection.description,
        case_count=case_count or 0,
        created_at=collection.created_at,
    )


def case_to_view(
    db: Session,
    test_case: TestCase,
    revision_id: UUID | None = None,
) -> TestCaseView:
    resolved_revision_id = revision_id or test_case.current_revision_id
    if resolved_revision_id is None:
        raise HTTPException(status_code=409, detail="test_case_has_no_revision")
    revision = db.scalar(
        select(TestCaseRevision).where(
            TestCaseRevision.id == resolved_revision_id,
            TestCaseRevision.test_case_id == test_case.id,
        )
    )
    if revision is None:
        raise HTTPException(status_code=409, detail="test_case_revision_not_found")
    collection_ids = list(
        db.scalars(
            select(CollectionCaseMembership.collection_id).where(
                CollectionCaseMembership.test_case_id == test_case.id
            )
        )
    )
    source = ""
    if revision.source_refs:
        source = str(revision.source_refs[0].get("label", ""))
    return TestCaseView(
        id=test_case.id,
        case_key=test_case.case_key,
        collection_ids=collection_ids,
        current_revision_id=revision.id,
        revision_number=revision.revision_number,
        title=revision.title,
        module=revision.module,
        priority=revision.priority,
        case_type=revision.case_type,
        tags=list(revision.tags),
        preconditions=list(revision.preconditions),
        steps=list(revision.steps),
        source=source,
        created_at=test_case.created_at,
    )


@router.get(
    "/spaces/{space_id}/collections",
    response_model=list[CaseCollectionView],
)
def list_collections(
    space_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> list[CaseCollectionView]:
    require_space_membership(db, account.id, space_id)
    collections = list(
        db.scalars(
            select(CaseCollection)
            .where(
                CaseCollection.space_id == space_id,
                CaseCollection.deleted_at.is_(None),
            )
            .order_by(CaseCollection.created_at)
        )
    )
    return [collection_to_view(db, collection) for collection in collections]


@router.post(
    "/spaces/{space_id}/collections",
    response_model=CaseCollectionView,
    status_code=201,
)
def create_collection(
    space_id: UUID,
    payload: CaseCollectionCreate,
    account: CurrentAccount,
    db: DbSession,
) -> CaseCollectionView:
    require_space_membership(db, account.id, space_id)
    collection = CaseCollection(
        space_id=space_id,
        name=payload.name.strip(),
        description=payload.description.strip(),
    )
    db.add(collection)
    db.flush()
    write_audit(
        db,
        space_id=space_id,
        actor_id=account.id,
        action="collection.created",
        resource_type="case_collection",
        resource_id=collection.id,
    )
    db.commit()
    db.refresh(collection)
    return collection_to_view(db, collection)


@router.patch(
    "/collections/{collection_id}",
    response_model=CaseCollectionView,
)
def update_collection(
    collection_id: UUID,
    payload: CaseCollectionUpdate,
    account: CurrentAccount,
    db: DbSession,
) -> CaseCollectionView:
    collection = ensure_collection(db, account, collection_id)
    if payload.name is not None:
        collection.name = payload.name.strip()
    if payload.description is not None:
        collection.description = payload.description.strip()
    write_audit(
        db,
        space_id=collection.space_id,
        actor_id=account.id,
        action="collection.updated",
        resource_type="case_collection",
        resource_id=collection.id,
    )
    db.commit()
    db.refresh(collection)
    return collection_to_view(db, collection)


@router.delete("/collections/{collection_id}", status_code=204)
def delete_collection(
    collection_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> Response:
    collection = ensure_collection(db, account, collection_id)
    collection.deleted_at = datetime.now(UTC)
    db.execute(
        update(Conversation)
        .where(Conversation.collection_id == collection.id)
        .values(collection_id=None, updated_at=datetime.now(UTC))
    )
    write_audit(
        db,
        space_id=collection.space_id,
        actor_id=account.id,
        action="collection.deleted",
        resource_type="case_collection",
        resource_id=collection.id,
    )
    db.commit()
    return Response(status_code=204)


@router.get(
    "/collections/{collection_id}/test-cases",
    response_model=list[TestCaseView],
)
def list_test_cases(
    collection_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> list[TestCaseView]:
    ensure_collection(db, account, collection_id)
    cases = list(
        db.scalars(
            select(TestCase)
            .join(
                CollectionCaseMembership,
                CollectionCaseMembership.test_case_id == TestCase.id,
            )
            .where(
                CollectionCaseMembership.collection_id == collection_id,
                TestCase.deleted_at.is_(None),
            )
            .order_by(CollectionCaseMembership.position, TestCase.created_at)
        )
    )
    return [case_to_view(db, test_case) for test_case in cases]


@router.get("/test-cases/{case_id}", response_model=TestCaseView)
def get_test_case(
    case_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> TestCaseView:
    return case_to_view(db, ensure_case(db, account, case_id))


@router.post(
    "/collections/{collection_id}/test-cases",
    response_model=TestCaseView,
    status_code=201,
)
def create_test_case(
    collection_id: UUID,
    payload: TestCaseCreate,
    account: CurrentAccount,
    db: DbSession,
) -> TestCaseView:
    collection = ensure_collection(db, account, collection_id)
    case_key = (payload.case_key or f"CASE-{uuid4().hex[:6]}").strip().upper()
    existing = db.scalar(
        select(TestCase.id).where(
            TestCase.space_id == collection.space_id,
            TestCase.case_key == case_key,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="case_key_already_exists")

    test_case = create_test_case_record(
        db,
        collection=collection,
        payload=payload,
        account=account,
        case_key=case_key,
        position=collection_to_view(db, collection).case_count,
    )
    db.commit()
    db.refresh(test_case)
    return case_to_view(db, test_case)


@router.post(
    "/collections/{collection_id}/test-cases/batch",
    response_model=list[TestCaseView],
    status_code=201,
)
def create_test_cases_batch(
    collection_id: UUID,
    payload: TestCaseBatchCreate,
    account: CurrentAccount,
    db: DbSession,
) -> list[TestCaseView]:
    collection = ensure_collection(db, account, collection_id)
    case_keys = [
        (item.case_key or f"CASE-{uuid4().hex[:6]}").strip().upper()
        for item in payload.cases
    ]
    if len(case_keys) != len(set(case_keys)):
        raise HTTPException(status_code=409, detail="duplicate_case_key_in_batch")
    existing = db.scalar(
        select(TestCase.id).where(
            TestCase.space_id == collection.space_id,
            TestCase.case_key.in_(case_keys),
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="case_key_already_exists")

    start_position = collection_to_view(db, collection).case_count
    try:
        created = [
            create_test_case_record(
                db,
                collection=collection,
                payload=item,
                account=account,
                case_key=case_keys[index],
                position=start_position + index,
            )
            for index, item in enumerate(payload.cases)
        ]
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="case_key_already_exists",
        ) from error
    for test_case in created:
        db.refresh(test_case)
    return [case_to_view(db, test_case) for test_case in created]


@router.patch("/test-cases/{case_id}", response_model=TestCaseView)
def update_test_case(
    case_id: UUID,
    payload: TestCaseUpdate,
    account: CurrentAccount,
    db: DbSession,
) -> TestCaseView:
    test_case = ensure_case(db, account, case_id)
    if test_case.current_revision_id != payload.base_revision_id:
        raise HTTPException(status_code=409, detail="revision_conflict")
    latest_number = db.scalar(
        select(func.max(TestCaseRevision.revision_number)).where(
            TestCaseRevision.test_case_id == test_case.id
        )
    )
    revision = TestCaseRevision(
        test_case_id=test_case.id,
        revision_number=(latest_number or 0) + 1,
        title=payload.title.strip(),
        module=payload.module.strip(),
        priority=payload.priority,
        case_type=payload.case_type.strip(),
        tags=normalize_tags(payload.tags),
        preconditions=[item.strip() for item in payload.preconditions if item.strip()],
        steps=normalize_steps(payload.steps),
        source_refs=[{"label": payload.source.strip()}],
    )
    db.add(revision)
    db.flush()
    test_case.current_revision_id = revision.id
    write_audit(
        db,
        space_id=test_case.space_id,
        actor_id=account.id,
        action="test_case.revised",
        resource_type="test_case",
        resource_id=test_case.id,
        payload={"revision_number": revision.revision_number},
    )
    db.commit()
    db.refresh(test_case)
    return case_to_view(db, test_case)


@router.delete("/test-cases/{case_id}", status_code=204)
def delete_test_case(
    case_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> Response:
    test_case = ensure_case(db, account, case_id)
    test_case.deleted_at = datetime.now(UTC)
    write_audit(
        db,
        space_id=test_case.space_id,
        actor_id=account.id,
        action="test_case.deleted",
        resource_type="test_case",
        resource_id=test_case.id,
    )
    db.commit()
    return Response(status_code=204)


def execution_run_assignees(
    db: Session,
    run: ExecutionRun,
) -> list[Account]:
    return list(
        db.scalars(
            select(Account)
            .join(
                ExecutionRunAssignee,
                ExecutionRunAssignee.account_id == Account.id,
            )
            .where(ExecutionRunAssignee.run_id == run.id)
            .order_by(ExecutionRunAssignee.created_at, Account.display_name)
        )
    )


def can_manage_execution_run(
    db: Session,
    run: ExecutionRun,
    account_id: UUID,
) -> bool:
    if run.executor_id == account_id:
        return True
    membership = db.scalar(
        select(SpaceMembership).where(
            SpaceMembership.space_id == run.space_id,
            SpaceMembership.account_id == account_id,
        )
    )
    return bool(membership and membership.role == "owner")


def execution_run_to_view(
    db: Session,
    run: ExecutionRun,
    viewer_id: UUID | None = None,
) -> ExecutionRunView:
    collection = db.get(CaseCollection, run.collection_id)
    creator = db.get(Account, run.executor_id)
    records = list(
        db.scalars(
            select(ExecutionRecord)
            .where(ExecutionRecord.run_id == run.id)
            .order_by(ExecutionRecord.created_at)
        )
    )
    record_views: list[ExecutionRecordView] = []
    for record in records:
        test_case = db.get(TestCase, record.test_case_id)
        if test_case is None:
            continue
        updater = (
            db.get(Account, record.updated_by_id) if record.updated_by_id is not None else None
        )
        assignee = (
            db.get(Account, record.assignee_id)
            if record.assignee_id is not None
            else None
        )
        record_views.append(
            ExecutionRecordView(
                id=record.id,
                test_case=case_to_view(db, test_case, record.revision_id),
                status=record.status,
                completed_step_ids=list(record.completed_step_ids),
                actual_result=record.actual_result,
                defect_ref=record.defect_ref,
                assignee_id=record.assignee_id,
                assignee_name=assignee.display_name if assignee else None,
                can_edit=bool(
                    viewer_id is not None
                    and record.assignee_id == viewer_id
                    and run.status == "active"
                ),
                updated_by_name=updater.display_name if updater else None,
                updated_at=record.updated_at,
            )
        )
    contributors = execution_run_contributors(db, run)
    activity_times = [run.created_at, *(record.updated_at for record in records)]
    if run.completed_at is not None:
        activity_times.append(run.completed_at)
    last_activity_at = max(activity_times)
    assignees = execution_run_assignees(db, run)
    return ExecutionRunView(
        id=run.id,
        collection_id=run.collection_id,
        collection_name=collection.name if collection else "已删除集合",
        description=run.description,
        status=run.status,
        creator_name=creator.display_name if creator else "未知成员",
        creator_id=run.executor_id,
        assignee_ids=[item.id for item in assignees],
        assignee_names=[item.display_name for item in assignees],
        can_manage=bool(
            viewer_id is not None
            and can_manage_execution_run(db, run, viewer_id)
        ),
        contributor_names=contributors,
        created_at=run.created_at,
        last_activity_at=last_activity_at,
        completed_at=run.completed_at,
        records=record_views,
    )


def execution_run_contributors(db: Session, run: ExecutionRun) -> list[str]:
    record_ids = list(
        db.scalars(select(ExecutionRecord.id).where(ExecutionRecord.run_id == run.id))
    )
    account_ids = {
        run.executor_id,
        *[
            account_id
            for account_id in db.scalars(
                select(ExecutionRecord.updated_by_id)
                .where(
                    ExecutionRecord.run_id == run.id,
                    ExecutionRecord.updated_by_id.is_not(None),
                )
                .distinct()
            )
            if account_id is not None
        ],
    }
    if record_ids:
        account_ids.update(
            account_id
            for account_id in db.scalars(
                select(AuditEvent.actor_id)
                .where(
                    AuditEvent.action == "execution_record.updated",
                    AuditEvent.resource_id.in_(record_ids),
                    AuditEvent.actor_id.is_not(None),
                )
                .distinct()
            )
            if account_id is not None
        )
    names: list[str] = []
    for account_id in account_ids:
        account = db.get(Account, account_id)
        if account and account.display_name not in names:
            names.append(account.display_name)
    return names


def execution_run_to_summary(
    db: Session,
    run: ExecutionRun,
) -> ExecutionRunSummaryView:
    collection = db.get(CaseCollection, run.collection_id)
    creator = db.get(Account, run.executor_id)
    counts = dict(
        db.execute(
            select(ExecutionRecord.status, func.count(ExecutionRecord.id))
            .where(ExecutionRecord.run_id == run.id)
            .group_by(ExecutionRecord.status)
        ).all()
    )
    last_record_update = db.scalar(
        select(func.max(ExecutionRecord.updated_at)).where(ExecutionRecord.run_id == run.id)
    )
    assignees = execution_run_assignees(db, run)
    return ExecutionRunSummaryView(
        id=run.id,
        collection_id=run.collection_id,
        collection_name=collection.name if collection else "已删除集合",
        description=run.description,
        status=run.status,
        creator_name=creator.display_name if creator else "未知成员",
        assignee_ids=[item.id for item in assignees],
        assignee_names=[item.display_name for item in assignees],
        contributor_names=execution_run_contributors(db, run),
        created_at=run.created_at,
        last_activity_at=max(
            timestamp
            for timestamp in (
                run.created_at,
                last_record_update,
                run.completed_at,
            )
            if timestamp is not None
        ),
        completed_at=run.completed_at,
        total_count=sum(counts.values()),
        not_run_count=counts.get(ExecutionStatus.NOT_RUN, 0),
        passed_count=counts.get(ExecutionStatus.PASSED, 0),
        failed_count=counts.get(ExecutionStatus.FAILED, 0),
        skipped_count=counts.get(ExecutionStatus.SKIPPED, 0),
        blocked_count=counts.get(ExecutionStatus.BLOCKED, 0),
    )


@router.get(
    "/spaces/{space_id}/execution-runs",
    response_model=list[ExecutionRunSummaryView],
)
def list_space_execution_runs(
    space_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> list[ExecutionRunSummaryView]:
    require_space_membership(db, account.id, space_id)
    runs = list(
        db.scalars(
            select(ExecutionRun)
            .where(ExecutionRun.space_id == space_id)
            .order_by(ExecutionRun.created_at.desc())
        )
    )
    return [execution_run_to_summary(db, run) for run in runs]


@router.get(
    "/collections/{collection_id}/execution-runs",
    response_model=list[ExecutionRunSummaryView],
)
def list_execution_runs(
    collection_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> list[ExecutionRunSummaryView]:
    collection = ensure_collection(db, account, collection_id)
    runs = list(
        db.scalars(
            select(ExecutionRun)
            .where(
                ExecutionRun.collection_id == collection.id,
                ExecutionRun.space_id == collection.space_id,
            )
            .order_by(ExecutionRun.created_at.desc())
        )
    )
    return [execution_run_to_summary(db, run) for run in runs]


@router.get(
    "/execution-runs/{run_id}",
    response_model=ExecutionRunView,
)
def get_execution_run(
    run_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> ExecutionRunView:
    run = db.get(ExecutionRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="execution_run_not_found")
    require_space_membership(db, account.id, run.space_id)
    return execution_run_to_view(db, run, account.id)


@router.post(
    "/collections/{collection_id}/execution-runs",
    response_model=ExecutionRunView,
)
def create_execution_run(
    collection_id: UUID,
    payload: ExecutionRunCreate,
    account: CurrentAccount,
    db: DbSession,
) -> ExecutionRunView:
    collection = ensure_collection(db, account, collection_id)
    assignee_ids = list(dict.fromkeys(payload.assignee_ids))
    memberships = list(
        db.scalars(
            select(SpaceMembership).where(
                SpaceMembership.space_id == collection.space_id,
                SpaceMembership.account_id.in_(assignee_ids),
            )
        )
    )
    if len(memberships) != len(assignee_ids):
        raise HTTPException(status_code=422, detail="execution_assignee_not_space_member")
    cases = list(
        db.scalars(
            select(TestCase)
            .join(
                CollectionCaseMembership,
                CollectionCaseMembership.test_case_id == TestCase.id,
            )
            .where(
                CollectionCaseMembership.collection_id == collection.id,
                TestCase.deleted_at.is_(None),
            )
            .order_by(
                CollectionCaseMembership.position,
                TestCase.id,
            )
        )
    )
    cases = [item for item in cases if item.current_revision_id is not None]
    if not cases:
        raise HTTPException(status_code=409, detail="empty_collection_cannot_execute")
    run = ExecutionRun(
        space_id=collection.space_id,
        collection_id=collection.id,
        executor_id=account.id,
        description=payload.description.strip(),
        status="active",
    )
    db.add(run)
    db.flush()
    for assignee_id in assignee_ids:
        db.add(
            ExecutionRunAssignee(
                run_id=run.id,
                account_id=assignee_id,
            )
        )
    write_audit(
        db,
        space_id=collection.space_id,
        actor_id=account.id,
        action="execution_run.started",
        resource_type="execution_run",
        resource_id=run.id,
        payload={
            "description": run.description,
            "assignee_ids": [str(item) for item in assignee_ids],
        },
    )
    for index, test_case in enumerate(cases):
        db.add(
            ExecutionRecord(
                run_id=run.id,
                test_case_id=test_case.id,
                revision_id=test_case.current_revision_id,
                assignee_id=assignee_ids[index % len(assignee_ids)],
                status=ExecutionStatus.NOT_RUN,
                completed_step_ids=[],
                actual_result="",
                defect_ref="",
            )
        )
    db.commit()
    db.refresh(run)
    return execution_run_to_view(db, run, account.id)


@router.patch(
    "/execution-runs/{run_id}",
    response_model=ExecutionRunView,
)
def update_execution_run(
    run_id: UUID,
    payload: ExecutionRunUpdate,
    account: CurrentAccount,
    db: DbSession,
) -> ExecutionRunView:
    run = db.get(ExecutionRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="execution_run_not_found")
    require_space_membership(db, account.id, run.space_id)
    if not can_manage_execution_run(db, run, account.id):
        raise HTTPException(status_code=403, detail="execution_run_manager_required")
    if run.status != "active":
        raise HTTPException(status_code=409, detail="execution_run_already_closed")
    if payload.status == "completed" and not payload.allow_incomplete:
        remaining = db.scalar(
            select(func.count(ExecutionRecord.id)).where(
                ExecutionRecord.run_id == run.id,
                ExecutionRecord.status == ExecutionStatus.NOT_RUN,
            )
        )
        if remaining:
            raise HTTPException(status_code=409, detail="execution_run_incomplete")
    run.status = payload.status
    run.completed_at = datetime.now(UTC)
    write_audit(
        db,
        space_id=run.space_id,
        actor_id=account.id,
        action=f"execution_run.{payload.status}",
        resource_type="execution_run",
        resource_id=run.id,
    )
    db.commit()
    db.refresh(run)
    return execution_run_to_view(db, run, account.id)


@router.patch(
    "/execution-records/{record_id}",
    response_model=ExecutionRecordView,
)
def update_execution_record(
    record_id: UUID,
    payload: ExecutionRecordUpdate,
    account: CurrentAccount,
    db: DbSession,
) -> ExecutionRecordView:
    record = db.get(ExecutionRecord, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="execution_record_not_found")
    run = db.get(ExecutionRun, record.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="execution_run_not_found")
    require_space_membership(db, account.id, run.space_id)
    if record.assignee_id != account.id:
        raise HTTPException(status_code=403, detail="execution_record_assignee_required")
    if run.status != "active":
        raise HTTPException(status_code=409, detail="execution_run_closed")
    if payload.base_updated_at is not None and record.updated_at != payload.base_updated_at:
        raise HTTPException(status_code=409, detail="execution_record_changed")
    revision = db.get(TestCaseRevision, record.revision_id)
    if revision is None:
        raise HTTPException(status_code=409, detail="test_case_revision_not_found")
    valid_step_ids = {
        str(step.get("id", ""))
        for step in revision.steps
        if str(step.get("id", ""))
    }
    validate_execution_record_update(payload, valid_step_ids)
    actual_result = payload.actual_result.strip()
    record.status = ExecutionStatus(payload.status.value)
    record.completed_step_ids = payload.completed_step_ids
    record.actual_result = actual_result
    record.defect_ref = payload.defect_ref.strip()
    record.updated_by_id = account.id
    record.updated_at = datetime.now(UTC)
    write_audit(
        db,
        space_id=run.space_id,
        actor_id=account.id,
        action="execution_record.updated",
        resource_type="execution_record",
        resource_id=record.id,
        payload={"status": record.status.value},
    )
    db.commit()
    db.refresh(record)
    test_case = db.get(TestCase, record.test_case_id)
    if test_case is None:
        raise HTTPException(status_code=409, detail="test_case_not_found")
    return ExecutionRecordView(
        id=record.id,
        test_case=case_to_view(db, test_case, record.revision_id),
        status=record.status,
        completed_step_ids=list(record.completed_step_ids),
        actual_result=record.actual_result,
        defect_ref=record.defect_ref,
        assignee_id=record.assignee_id,
        assignee_name=account.display_name,
        can_edit=True,
        updated_by_name=account.display_name,
        updated_at=record.updated_at,
    )


@router.patch(
    "/execution-records/{record_id}/assignee",
    response_model=ExecutionRecordView,
)
def reassign_execution_record(
    record_id: UUID,
    payload: ExecutionRecordReassign,
    account: CurrentAccount,
    db: DbSession,
) -> ExecutionRecordView:
    record = db.get(ExecutionRecord, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="execution_record_not_found")
    run = db.get(ExecutionRun, record.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="execution_run_not_found")
    require_space_membership(db, account.id, run.space_id)
    if not can_manage_execution_run(db, run, account.id):
        raise HTTPException(status_code=403, detail="execution_run_manager_required")
    if run.status != "active":
        raise HTTPException(status_code=409, detail="execution_run_closed")
    new_membership = db.scalar(
        select(SpaceMembership).where(
            SpaceMembership.space_id == run.space_id,
            SpaceMembership.account_id == payload.assignee_id,
        )
    )
    if new_membership is None:
        raise HTTPException(status_code=422, detail="execution_assignee_not_space_member")
    old_assignee_id = record.assignee_id
    record.assignee_id = payload.assignee_id
    existing = db.scalar(
        select(ExecutionRunAssignee).where(
            ExecutionRunAssignee.run_id == run.id,
            ExecutionRunAssignee.account_id == payload.assignee_id,
        )
    )
    if existing is None:
        db.add(
            ExecutionRunAssignee(
                run_id=run.id,
                account_id=payload.assignee_id,
            )
        )
    write_audit(
        db,
        space_id=run.space_id,
        actor_id=account.id,
        action="execution_record.reassigned",
        resource_type="execution_record",
        resource_id=record.id,
        payload={
            "from": str(old_assignee_id) if old_assignee_id else None,
            "to": str(payload.assignee_id),
            "result_preserved": True,
        },
    )
    db.commit()
    db.refresh(record)
    assignee = db.get(Account, payload.assignee_id)
    updater = db.get(Account, record.updated_by_id) if record.updated_by_id else None
    test_case = db.get(TestCase, record.test_case_id)
    if test_case is None:
        raise HTTPException(status_code=409, detail="test_case_not_found")
    return ExecutionRecordView(
        id=record.id,
        test_case=case_to_view(db, test_case, record.revision_id),
        status=record.status,
        completed_step_ids=list(record.completed_step_ids),
        actual_result=record.actual_result,
        defect_ref=record.defect_ref,
        assignee_id=record.assignee_id,
        assignee_name=assignee.display_name if assignee else None,
        can_edit=record.assignee_id == account.id and run.status == "active",
        updated_by_name=updater.display_name if updater else None,
        updated_at=record.updated_at,
    )
