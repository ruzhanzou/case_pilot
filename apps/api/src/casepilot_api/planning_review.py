"""One persisted audit/revision budget; human confirmation never generates cases."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from casepilot_agent.planning_review import (
    REVIEW_INSTRUCTION,
    REVISION_INSTRUCTION,
    Review,
    Revision,
    candidate_plan,
    digest,
    phase_schema,
    project_review,
    review_model_input,
    snapshot,
)
from casepilot_agent.planning_review_diagnostics import diagnostic, notify
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from casepilot_api.auth import CurrentAccount, require_space_membership
from casepilot_api.database import get_db_session, get_session_factory
from casepilot_api.models import (
    Account,
    Conversation,
    ConversationMessage,
    ConversationOperation,
    PlanningReview,
    WorkspaceTestBrief,
)
from casepilot_api.task_outbox import enqueue_task

TASK = "casepilot.workbench.planning_review"
router = APIRouter(prefix="/api/v1/workspaces", tags=["planning-review"])
Db = Annotated[Session, Depends(get_db_session)]
ACTIVE = {"audit_pending", "auditing", "revision_pending", "revising", "reviewed", "proposed"}


class Start(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_version: int = Field(ge=1)


class Decide(Start):
    issue_ids: list[str] = Field(default_factory=list, max_length=32)
    proposal_hash: str = ""
    confirm: bool = False
    confirm_count_change: bool = False


def current(db, conversation):
    return db.scalar(
        select(WorkspaceTestBrief)
        .where(WorkspaceTestBrief.conversation_id == conversation.id)
        .order_by(WorkspaceTestBrief.version.desc())
        .limit(1)
        .with_for_update()
    )


def binding(db, conversation, brief):
    data = snapshot(brief.content.get("planning", {}))
    from casepilot_api.collection_references import (
        assert_reference_binding,
        capture_reference_binding,
    )
    from casepilot_api.schemas import ConversationMessageCreate
    from casepilot_api.workbench_skills import assert_bindings

    operation = (
        db.get(ConversationOperation, brief.source_operation_id)
        if brief.source_operation_id
        else None
    )
    if brief.source_operation_id:
        if operation is None or operation.conversation_id != conversation.id:
            raise HTTPException(409, "planning_review_authority_changed")
        assert_bindings(dict(operation.payload).get("skill_bindings"))
    # Collection precedes the COMPLETE ordered source set, including citations
    # and inherited inputs. No new collection lock follows a subset source lock.
    ids = {UUID(ref["source_id"]) for ref in data["sources"] if ref.get("source_id")}
    origin_ids = set()
    for prior in [
        brief.reference_binding or {},
        (dict(operation.payload).get("reference_binding") or {}) if operation is not None else {},
    ]:
        ids.update(UUID(row["source_id"]) for row in prior.get("sources", []))
        origin_ids.update(UUID(row["collection_id"])
                          for row in prior.get("source_collections", []))
    reference_snapshot = capture_reference_binding(
        db,
        conversation,
        ConversationMessageCreate(
            content="Review authority", knowledge_source_ids=sorted(ids, key=str),
            source_collection_ids=sorted(origin_ids, key=str)
        ),
        lock=True,
    )
    assert_reference_binding(
        db,
        db.get(Account, conversation.account_id),
        conversation,
        brief.reference_binding,
        lock=False,
    )
    if operation is not None:
        assert_reference_binding(
            db,
            db.get(Account, conversation.account_id),
            conversation,
            dict(operation.payload).get("reference_binding"),
            lock=False,
        )
    sources = reference_snapshot["sources"]
    return digest(
        {
            "brief": str(brief.id),
            "version": brief.version,
            "status": brief.status,
            "content": brief.content,
            "sources": sources,
            "reference_binding": reference_snapshot,
            "collection": str(conversation.collection_id),
            "selection": (conversation.context or {}).get("workbench_selection"),
        }
    )


def assert_revision_authority(db, conversation, brief):
    """Review-created drafts retain their server-owned ancestry, never client JSON authority."""
    if brief.reference_binding:
        from casepilot_api.collection_references import assert_reference_binding

        assert_reference_binding(
            db, db.get(Account, conversation.account_id), conversation, brief.reference_binding
        )
        return
    seen = set()
    while brief is not None:
        if brief.id in seen:
            raise HTTPException(409, "planning_review_authority_changed")
        seen.add(brief.id)
        review = db.scalar(
            select(PlanningReview).where(
                PlanningReview.applied_brief_id == brief.id,
                PlanningReview.conversation_id == conversation.id,
            )
        )
        if review is None:
            return
        original = db.get(WorkspaceTestBrief, review.brief_id)
        if (
            review.status != "applied"
            or review.account_id != conversation.account_id
            or original is None
            or binding(db, conversation, original) != review.binding
        ):
            raise HTTPException(409, "planning_review_version_changed")
        brief = original


def ensure(db, account, conversation_id):
    from casepilot_api.conversations import _ensure_conversation

    _ensure_conversation(db, account.id, conversation_id)
    return db.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def fresh(db, conversation, row):
    if conversation.account_id != row.account_id:
        raise HTTPException(409, "planning_review_authority_changed")
    require_space_membership(db, row.account_id, conversation.space_id)
    brief = current(db, conversation)
    if brief is None or brief.id != row.brief_id or binding(db, conversation, brief) != row.binding:
        raise HTTPException(409, "planning_review_version_changed")
    assert_revision_authority(db, conversation, brief)
    return brief


def view(row):
    return {
        "id": str(row.id),
        "base_version": row.base_version,
        "status": row.status,
        "requests_used": row.requests_used,
        "request_limit": 2,
        "error_code": row.error_code,
        "diagnostic": row.data.get("diagnostic"),
        "review": row.data.get("review"),
        "selected": row.data.get("selected", []),
        "proposal": row.data.get("proposal"),
        "proposal_hash": row.data.get("proposal_hash"),
        "sources": row.data["snapshot"]["sources"],
        "applied_brief_id": str(row.applied_brief_id) if row.applied_brief_id else None,
    }


def load(db, account, conversation_id, review_id):
    conversation = ensure(db, account, conversation_id)
    row = db.scalar(
        select(PlanningReview)
        .where(
            PlanningReview.id == review_id,
            PlanningReview.conversation_id == conversation_id,
            PlanningReview.account_id == account.id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "planning_review_not_found")
    return conversation, row


@router.get("/{conversation_id}/planning-reviews")
def list_reviews(conversation_id: UUID, account: CurrentAccount, db: Db):
    conversation = ensure(db, account, conversation_id)
    rows = list(
        db.scalars(
            select(PlanningReview)
            .where(PlanningReview.conversation_id == conversation_id)
            .order_by(PlanningReview.created_at)
            # Worker completion also locks review before brief. Refresh cached
            # ORM state under that lock; stale GET snapshots cannot overwrite it.
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    for row in rows:
        if row.status in ACTIVE:
            try:
                fresh(db, conversation, row)
            except HTTPException:
                row.status, row.error_code = "invalidated", "planning_review_version_changed"
            if row.status in {"auditing", "revising"} and row.updated_at < datetime.now(
                UTC
            ) - timedelta(minutes=10):
                row.status, row.error_code = "failed", "planning_review_interrupted"
    db.commit()
    return [view(r) for r in rows]


@router.post("/{conversation_id}/planning-reviews", status_code=202)
def start_review(conversation_id: UUID, payload: Start, account: CurrentAccount, db: Db):
    conversation = ensure(db, account, conversation_id)
    brief = current(db, conversation)
    if brief is None or brief.version != payload.base_version or brief.status != "draft":
        raise HTTPException(409, "planning_review_version_changed")
    assert_revision_authority(db, conversation, brief)
    existing = db.scalar(
        select(PlanningReview)
        .where(PlanningReview.brief_id == brief.id, PlanningReview.account_id == account.id)
        .order_by(PlanningReview.created_at.desc())
        .limit(1)
    )
    # Same-version button retries never create another model budget.
    if existing:
        return view(existing)
    try:
        data = snapshot(brief.content.get("planning", {}))
        stamp = binding(db, conversation, brief)
    except ValueError as error:
        raise HTTPException(422, "planning_review_input_limit") from error
    row = PlanningReview(
        id=uuid4(),
        conversation_id=conversation.id,
        account_id=account.id,
        brief_id=brief.id,
        base_version=brief.version,
        binding=stamp,
        status="audit_pending",
        requests_used=0,
        data={"snapshot": data},
    )
    db.add(row)
    enqueue_task(db, TASK, [str(row.id), "audit"], task_id=uuid4())
    db.add(
        ConversationMessage(
            conversation_id=conversation.id,
            role="assistant",
            content="已开始全计划审核；审核意见不是质量认证，修订需要你明确确认。",
            message_metadata={
                "planning_review_id": str(row.id),
                "artifact_type": "test_brief",
                "brief_version": brief.version,
            },
        )
    )
    db.commit()
    return view(row)


@router.post("/{conversation_id}/planning-reviews/{review_id}/{action}")
def decide(
    conversation_id: UUID,
    review_id: UUID,
    action: str,
    payload: Decide,
    account: CurrentAccount,
    db: Db,
):
    conversation, row = load(db, account, conversation_id, review_id)
    if payload.base_version != row.base_version:
        raise HTTPException(409, "planning_review_version_changed")
    if action == "cancel":
        if row.status != "applied":
            row.status = "cancelled"
        db.commit()
        return view(row)
    if action == "apply" and row.status == "applied":
        if not payload.confirm or payload.proposal_hash != row.data.get("proposal_hash"):
            raise HTTPException(409, "planning_review_confirmation_changed")
        return view(row)
    brief = fresh(db, conversation, row)
    if action == "revise":
        if row.status in {
            "revision_pending",
            "revising",
            "proposed",
        } and payload.issue_ids == row.data.get("selected"):
            return view(row)
        issues = {f["id"] for f in (row.data.get("review") or {}).get("findings", [])}
        if (
            row.status != "reviewed"
            or not payload.issue_ids
            or not set(payload.issue_ids) <= issues
            or len(set(payload.issue_ids)) != len(payload.issue_ids)
        ):
            raise HTTPException(409, "planning_review_selection_invalid")
        row.data = {**row.data, "selected": payload.issue_ids}
        row.status = "revision_pending"
        enqueue_task(db, TASK, [str(row.id), "revision"], task_id=uuid4())
    elif action == "apply":
        if (
            row.status != "proposed"
            or not payload.confirm
            or payload.proposal_hash != row.data["proposal_hash"]
        ):
            raise HTTPException(409, "planning_review_confirmation_changed")
        plan = candidate_plan(
            row.data["snapshot"],
            Review.model_validate(row.data["review"]),
            row.data["selected"],
            Revision.model_validate(row.data["proposal"]),
            row.id.hex[:16],
        )
        from casepilot_agent.store import render_test_brief_markdown

        if (
            len(plan["test_points"]) != len(row.data["snapshot"]["planning"]["test_points"])
            and not payload.confirm_count_change
        ):
            raise HTTPException(409, "planning_revision_count_confirmation_required")
        from casepilot_api.schemas import TestBriefContent

        content = {**deepcopy(brief.content), "planning": plan}
        TestBriefContent.model_validate(content)
        from casepilot_api.collection_references import capture_brief_reference_binding

        reference_snapshot = capture_brief_reference_binding(
            db, conversation, content, inherited=brief.reference_binding
        )
        revised = WorkspaceTestBrief(
            id=uuid4(),
            conversation_id=conversation.id,
            version=brief.version + 1,
            source_operation_id=brief.source_operation_id,
            reference_binding=reference_snapshot,
            content=content,
            status="draft",
            created_by=account.id,
            markdown_content=render_test_brief_markdown(brief.version + 1, content),
        )
        db.add(revised)
        from casepilot_api.case_management import write_audit

        write_audit(
            db,
            space_id=conversation.space_id,
            actor_id=account.id,
            action="planning_revision_applied",
            resource_type="planning_review",
            resource_id=row.id,
            payload={
                "base_version": row.base_version,
                "new_version": revised.version,
                "proposal_hash": row.data["proposal_hash"],
            },
        )
        row.status, row.applied_brief_id = "applied", revised.id
        # A new draft invalidates old brief approvals by version. No generation job is created.
        db.add(
            ConversationMessage(
                conversation_id=conversation.id,
                role="assistant",
                content=(
                    f"已按你的确认应用规划修订 V{revised.version}；"
                    "仍待独立复核，未生成或采纳正式用例。"
                ),
                message_metadata={
                    "planning_review_id": str(row.id),
                    "artifact_type": "test_brief",
                    "brief_version": revised.version,
                },
            )
        )
    else:
        raise HTTPException(422, "planning_review_action_invalid")
    db.commit()
    return view(row)


def _execute(review_id, phase, provider=None):
    """Consume one real outbox delivery. Duplicate/late deliveries cannot re-run a phase."""
    factory = get_session_factory()
    running = "auditing" if phase == "audit" else "revising"
    pending = "audit_pending" if phase == "audit" else "revision_pending"
    if phase not in {"audit", "revision"}:
        return "ignored"
    with factory() as db:
        row = db.scalar(
            select(PlanningReview).where(PlanningReview.id == UUID(review_id)).with_for_update()
        )
        if row is None or row.status != pending:
            return "ignored"
        conversation = db.get(Conversation, row.conversation_id)
        try:
            fresh(db, conversation, row)
        except HTTPException:
            row.status, row.error_code = "invalidated", "planning_review_version_changed"
            db.commit()
            return row.status
        row.status = running
        data = deepcopy(row.data)
        db.commit()
    used_in_phase = 0

    def reserve():
        nonlocal used_in_phase
        with factory() as db:
            row = db.scalar(
                select(PlanningReview).where(PlanningReview.id == UUID(review_id)).with_for_update()
            )
            if row.status != running or row.requests_used >= 2 or used_in_phase:
                raise ValueError("planning_review_budget_or_state")
            fresh(db, db.get(Conversation, row.conversation_id), row)
            row.requests_used += 1
            db.commit()
        used_in_phase += 1

    failure_phase = "provider_setup"
    try:
        if provider is None:
            from casepilot_agent.config import get_settings
            from casepilot_agent.providers import create_provider

            provider = create_provider(get_settings().provider)
        # Every actual HTTP request reserves before sending, including retries.
        provider.request_guard = reserve
        schema = phase_schema(data, phase)
        model_input = review_model_input(data)
        instruction = REVIEW_INSTRUCTION if phase == "audit" else REVISION_INSTRUCTION
        failure_phase = "provider_call"
        result, usage = provider.complete(
            stage="planning_review." + phase,
            instruction=instruction,
            payload=model_input,
            result_type=schema,
            model_id="auto",
        )
        failure_phase = "schema_validation"
        result = schema.model_validate(result)
        if phase == "audit":
            failure_phase = "reference_validation"
            selected_citations = result.model_dump(mode="json")
            result = project_review(result, data["snapshot"])
        else:
            failure_phase = "revision_validation"
            candidate_plan(
                data["snapshot"],
                Review.model_validate(data["review"]),
                data["selected"],
                result,
                UUID(review_id).hex[:16],
            )
        failure_phase = "completion_revalidation"
        with factory() as db:
            row = db.scalar(
                select(PlanningReview).where(PlanningReview.id == UUID(review_id)).with_for_update()
            )
            if row.status != running:
                return "ignored"
            fresh(db, db.get(Conversation, row.conversation_id), row)
            failure_phase = "result_serialization"
            output = result.model_dump(mode="json")
            row.data = {
                **row.data,
                **({"review_selection": selected_citations} if phase == "audit" else {}),
                "review" if phase == "audit" else "proposal": output,
                f"{phase}_usage": usage.model_dump(mode="json"),
            }
            if phase == "revision":
                row.data = {**row.data, "proposal_hash": digest(output)}
            row.status = "reviewed" if phase == "audit" else "proposed"
            failure_phase = "result_persistence"
            db.commit()
            return row.status
    except Exception as error:
        evidence = diagnostic(error, failure_phase)
        notify(evidence)
        try:
            with factory() as db:
                row = db.scalar(
                    select(PlanningReview)
                    .where(PlanningReview.id == UUID(review_id))
                    .with_for_update()
                )
                if row is not None and row.status == running:
                    row.status, row.error_code = "failed", evidence["code"]
                    row.data = {**row.data, "diagnostic": evidence}
                    db.commit()
        except Exception as storage_error:
            notify(diagnostic(storage_error, "failure_persistence"))
            # No exception string/SQL parameters are allowed to escape to task logs.
            raise RuntimeError("planning_review_failure_record_unavailable") from None
        return "failed"


def execute(review_id, phase, provider=None):
    try:
        return _execute(review_id, phase, provider)
    except Exception as error:
        if isinstance(error, RuntimeError) and error.args == (
            "planning_review_failure_record_unavailable",
        ):
            raise
        notify(diagnostic(error, "claim"))
        raise RuntimeError("planning_review_claim_failed") from None
