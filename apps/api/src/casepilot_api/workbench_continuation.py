"""Durable continuation primitives. Every helper uses the caller's transaction.

Claims and budget reservations must be committed in SHORT transactions before a
model call. Domain effects and complete_event belong to a single transaction.
Only the executor holding the advisory run guard may recover a running claim.
"""
import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from casepilot_api.models import (
    Account,
    CaseCollection,
    CollectionCaseMembership,
    Conversation,
    ConversationMessage,
    SpaceMembership,
    TaskOutbox,
    TestCase,
    WorkbenchContinuation,
    WorkbenchReservation,
    WorkbenchRun,
    WorkspaceCandidate,
)
from casepilot_api.task_outbox import enqueue_task
from casepilot_api.workbench_artifact_version import change_set_version as change_set_version

TASK_NAME = "casepilot.workbench.continue"
QUEUE = "workbench"
TERMINAL = {"completed", "cancelled", "invalidated", "failed", "budget_exhausted"}
DEFAULT_BUDGET = {"segments": 8, "model_turns": 32, "tool_calls": 64, "reserved_sdk_requests": 64}


def selection_binding(conversation):
    state = dict(conversation.context or {}).get("workbench_selection") or {}
    return {
        "selection_version": state.get("version", 0),
        "destination_collection_id": str(conversation.collection_id)
        if conversation.collection_id else None,
        "sources": [{"ref": item["ref"], "version": str(item["version"])}
                    for item in state.get("items", [])],
    }


capture_binding = selection_binding


def load_run(db, run_id, account_id=None, *, for_update=False):
    db.flush()
    statement = select(WorkbenchRun).where(WorkbenchRun.id == UUID(str(run_id)))
    if for_update:
        statement = statement.with_for_update()
    run = db.scalar(statement.execution_options(populate_existing=True))
    if run is None or (account_id is not None and str(run.account_id) != str(account_id)):
        raise HTTPException(404, "workbench_run_not_found")
    return run


def create_run(db, account, conversation, root_message_id, request_id, plan=None, budget=None):
    message = db.get(ConversationMessage, UUID(str(root_message_id)))
    if (conversation.account_id != account.id or message is None or message.role != "user"
            or message.conversation_id != conversation.id):
        raise HTTPException(409, "workbench_run_authority_invalid")
    limits = dict(DEFAULT_BUDGET if budget is None else budget)
    if not limits or any(not isinstance(v, int) or isinstance(v, bool) or v < 0
                         for v in limits.values()):
        raise ValueError("invalid_workbench_budget")
    run = WorkbenchRun(
        conversation_id=conversation.id, account_id=account.id, space_id=conversation.space_id,
        root_message_id=message.id, request_id=UUID(str(request_id)), status="active",
        epoch=1, cursor=0, plan=deepcopy(plan or {}), binding=selection_binding(conversation),
        checkpoint={}, budget=limits, used={},
    )
    reservation = db.get(WorkbenchReservation, (account.id, conversation.id, UUID(str(request_id))))
    if reservation is not None:
        run.budget, run.used = dict(reservation.budget), dict(reservation.used)
    db.add(run)
    db.flush()
    return run


def project_run(run):
    reason = ("side_question_in_progress" if run.status == "paused_question" else
              run.checkpoint.get("invalidation_reason") or run.checkpoint.get("pause_reason"))
    if run.checkpoint.get("error_code") == "workbench_scope_requires_selection":
        reason = "scope_requires_selection"
    if (reason is None
            and run.checkpoint.get("completion", {}).get("completion_code") == "goal_unverified"):
        reason = "goal_unverified"
    allowed = {"goal_unverified", "side_question_in_progress", "new_user_instruction",
               "new_mutating_instruction",
               "selection_changed", "continuation_failed", "scope_requires_selection"}
    return {"reason": reason if reason in allowed else None, "id": str(run.id),
            "request_id": str(run.request_id),
            "segment_sequence_base": int(run.checkpoint.get("event_sequence_base", 0)),
            "status": run.status, "epoch": run.epoch,
            "cursor": run.cursor, "plan": deepcopy(run.plan),
            "budget": dict(run.budget), "used": dict(run.used)}


def _empty_canonical_target_projection(conversation, run, request):
    """Recognize only the exact empty canonical representation; never resolve selectors."""
    from casepilot_api.schemas import ConversationTarget

    canonical = dict(conversation.context or {}).get("workbench_selection")
    empty = ConversationTarget(kind="case").model_dump(mode="json")
    return (isinstance(canonical, dict) and canonical.get("items") == []
            and run.checkpoint.get("authorized_scope_canonical") is True
            and request.get("target_scope") == "selected"
            and not request.get("target_case_ids")
            and not request.get("target_candidate_snapshots")
            and request.get("targets") == [empty])


def validate_binding(db, run, conversation=None, *, allow_legacy=False):
    conversation = conversation or db.get(Conversation, run.conversation_id)
    member = db.scalar(select(SpaceMembership.id).where(
        SpaceMembership.space_id == run.space_id, SpaceMembership.account_id == run.account_id))
    if (conversation is None or conversation.account_id != run.account_id
            or conversation.space_id != run.space_id or member is None
            or db.get(Account, run.account_id) is None):
        raise HTTPException(409, "workbench_run_authority_changed")
    if selection_binding(conversation) != run.binding:
        raise HTTPException(409, "workbench_run_binding_changed")
    request = dict(run.checkpoint.get("original_request") or {})
    if (not allow_legacy and not run.binding.get("sources")
            and not _empty_canonical_target_projection(conversation, run, request)
            and any(request.get(key) for key in (
        "targets", "target_case_ids", "target_candidate_snapshots",
    ))):
        # Legacy selectors may expand dynamically. Until a dispatcher persists
        # their exact resolved snapshot, do not broaden a background resume.
        raise HTTPException(409, "workbench_legacy_scope_requires_reselection")
    if conversation.collection_id:
        collection = db.get(CaseCollection, conversation.collection_id)
        if (collection is None or collection.deleted_at is not None
                or collection.space_id != run.space_id):
            raise HTTPException(409, "workbench_run_binding_changed")
    for source in run.binding.get("sources", []):
        kind, _, identifier = source["ref"].partition(":")
        if kind == "asset":
            case = db.get(TestCase, UUID(identifier), populate_existing=True)
            available = db.scalar(select(CollectionCaseMembership.test_case_id).join(
                CaseCollection, CaseCollection.id == CollectionCaseMembership.collection_id
            ).where(CollectionCaseMembership.test_case_id == UUID(identifier),
                    CaseCollection.space_id == run.space_id, CaseCollection.deleted_at.is_(None)))
            if (case is None or case.deleted_at is not None or case.space_id != run.space_id
                    or str(case.current_revision_id) != source["version"] or available is None):
                raise HTTPException(409, "workbench_run_source_changed")
        elif kind == "candidate":
            candidate = db.scalar(select(WorkspaceCandidate).where(
                WorkspaceCandidate.conversation_id == run.conversation_id,
                WorkspaceCandidate.ref == identifier).execution_options(populate_existing=True))
            if (candidate is None or candidate.status != "candidate"
                    or str(candidate.version) != source["version"]):
                raise HTTPException(409, "workbench_run_source_changed")
        else:
            raise HTTPException(409, "workbench_run_source_changed")
    return True


def enqueue_event(db, run, event_kind, source_id, source_version, payload=None):
    """Insert the source receipt and its broker delivery atomically, exactly once."""
    if not str(source_version) or not str(source_id):
        raise ValueError("continuation_requires_business_identity")
    event_id = uuid4()
    inserted = db.scalar(insert(WorkbenchContinuation).values(
        id=event_id, run_id=run.id, event_kind=event_kind, source_id=str(source_id),
        source_version=str(source_version), status="pending", expected_epoch=run.epoch,
        cursor=run.cursor, payload=deepcopy(payload or {}), receipt={}, attempts=0,
        created_at=datetime.now(UTC),
    ).on_conflict_do_nothing(constraint="uq_workbench_continuation_source")
      .returning(WorkbenchContinuation.id))
    if inserted:
        enqueue_task(db, TASK_NAME, [str(event_id)], task_id=event_id)
        db.flush()
        return db.get(WorkbenchContinuation, event_id)
    return db.scalar(select(WorkbenchContinuation).where(
        WorkbenchContinuation.run_id == run.id, WorkbenchContinuation.event_kind == event_kind,
        WorkbenchContinuation.source_id == str(source_id),
        WorkbenchContinuation.source_version == str(source_version)))


def _verified_collection_delete_completion(db, run, event):
    """Recognize a committed effect, never authorize a new operation or scope."""
    proof = run.checkpoint.get("applied_collection_delete") or {}
    steps = run.plan.get("steps") or []
    if not (0 <= run.cursor < len(steps)
            and steps[run.cursor].get("action") == "COLLECTION_DELETE"):
        return False
    conversation = db.get(Conversation, run.conversation_id)
    if conversation is None:
        return False
    proposal = (conversation.context or {}).get("workbench_collection_proposal") or {}
    expected = {
        "event_id": str(event.id), "run_id": str(run.id),
        "root_message_id": str(run.root_message_id), "request_id": str(run.request_id),
        "epoch": run.epoch, "cursor": run.cursor,
        "proposal_id": event.source_id, "proposal_version": event.source_version,
        "collection_id": proposal.get("collection_id"), "binding": run.binding,
    }
    if (proof != expected or event.payload.get("outcome") != "approved"
            or event.payload.get("source_kind") != "collection_proposal"
            or event.payload.get("next_job_id") is not None
            or event.payload.get("binding") != run.binding
            or proposal.get("id") != event.source_id or event.source_id != event.source_version
            or proposal.get("action") != "delete" or proposal.get("status") != "confirmed"
            or run.checkpoint.get("waiting_artifact_kind") != "collection_proposal"
            or run.checkpoint.get("waiting_artifact_id") != event.source_id
            or run.checkpoint.get("waiting_artifact_version") != event.source_version):
        return False
    result = proposal.get("result") or {}
    try:
        collection = db.get(CaseCollection, UUID(proposal["collection_id"]))
    except (KeyError, ValueError, TypeError):
        return False
    return (collection is not None and collection.space_id == run.space_id
            and collection.deleted_at is not None and result.get("action") == "delete"
            and result.get("collection_id") == str(collection.id)
            and result.get("deleted") is True and result.get("preserved_assets") is True)


def _case_delete_effect(db, run, change):
    """Validate the persisted exact soft-delete effect, never grant new authority."""
    from casepilot_api.models import AuditEvent, ConversationOperation
    from casepilot_api.workbench_artifact_version import operation_review_version

    if (change is None or change.conversation_id != run.conversation_id
            or change.status != "applied" or change.applied_at is None or not change.items):
        return None
    try:
        operation = db.get(ConversationOperation, UUID(str(
            run.checkpoint.get("waiting_operation_id"))))
    except (ValueError, TypeError):
        return None
    if (operation is None or operation.intent != "CASE_DELETE"
            or operation.conversation_id != run.conversation_id
            or operation.message_id != run.root_message_id
            or operation.related_change_set_id != change.id
            or operation.status != "completed" or operation.completed_at is None):
        return None
    refs = []
    for item in change.items:
        if item.get("operation") != "delete" or item.get("status") != "applied":
            return None
        if item.get("target_type") == "formal":
            try:
                identifier = UUID(str(item.get("test_case_id")))
            except (ValueError, TypeError):
                return None
            case = db.get(TestCase, identifier, populate_existing=True)
            audit = db.scalar(select(AuditEvent.id).where(
                AuditEvent.resource_id == identifier, AuditEvent.action == "test_case.deleted",
                AuditEvent.space_id == run.space_id, AuditEvent.actor_id == run.account_id,
                AuditEvent.payload["change_set_id"].astext == str(change.id),
                AuditEvent.payload["soft_delete"].as_boolean().is_(True)))
            if (case is None or case.space_id != run.space_id or case.deleted_at is None
                    or item.get("ref") != str(case.id)
                    or str(case.current_revision_id) != item.get("base_revision_id")
                    or audit is None):
                return None
            refs.append(f"asset:{case.id}")
        elif item.get("target_type") == "candidate":
            candidate = db.scalar(select(WorkspaceCandidate).where(
                WorkspaceCandidate.conversation_id == run.conversation_id,
                WorkspaceCandidate.ref == item.get("ref")).order_by(
                    WorkspaceCandidate.version.desc()).limit(1))
            base = item.get("base_version")
            if (type(base) is not int or candidate is None or candidate.status != "discarded"
                    or candidate.version != base + 1 or item.get("accepted_fields") != ["delete"]):
                return None
            refs.append(f"candidate:{candidate.ref}")
        else:
            return None
    if len(set(refs)) != len(refs):
        return None
    return {"operation_id": str(operation.id),
            "operation_version": operation_review_version(operation),
            "applied_version": change_set_version(change), "removed_refs": sorted(refs)}


def _verified_case_delete_completion(db, run, event):
    from casepilot_api.models import CaseChangeSet

    steps = run.plan.get("steps") or []
    if not (0 <= run.cursor < len(steps) and steps[run.cursor].get("action") == "CASE_DELETE"):
        return False
    try:
        change = db.get(CaseChangeSet, UUID(event.source_id))
    except (ValueError, TypeError):
        return False
    effect = _case_delete_effect(db, run, change)
    if effect is None:
        return False
    expected = {"event_id": str(event.id), "run_id": str(run.id),
                "root_message_id": str(run.root_message_id), "request_id": str(run.request_id),
                "epoch": run.epoch, "cursor": run.cursor,
                "change_set_id": event.source_id, "reviewed_version": event.source_version,
                "binding": run.binding, **effect}
    return (run.checkpoint.get("applied_case_delete") == expected
            and event.payload.get("outcome") == "approved"
            and event.payload.get("source_kind") == "change_set"
            and event.payload.get("next_job_id") is None
            and event.payload.get("source_operation_id") == effect["operation_id"]
            and event.payload.get("binding") == run.binding
            and run.checkpoint.get("waiting_artifact_kind") == "change_set"
            and run.checkpoint.get("waiting_artifact_id") == event.source_id
            and run.checkpoint.get("waiting_artifact_version") == event.source_version)


def claim_event(db, event_id):
    event = db.get(WorkbenchContinuation, UUID(str(event_id)))
    if event is None:
        return None
    run = load_run(db, event.run_id, for_update=True)
    db.refresh(event, with_for_update=True)
    if event.status != "pending" or run.status == "paused_question":
        return None
    if (run.status in TERMINAL or run.cancelled_at is not None
            or run.epoch != event.expected_epoch or run.cursor != event.cursor):
        event.status = "invalidated"
        return None
    try:
        steps = run.plan.get("steps") or []
        delete_completion = (event.event_kind == "approval_completed"
                             and ((0 <= run.cursor < len(steps)
                                   and steps[run.cursor].get("action") == "COLLECTION_DELETE")
                                  or (run.checkpoint.get("applied_collection_delete") or {}).get(
                                      "event_id") == str(event.id)))
        if delete_completion and not _verified_collection_delete_completion(db, run, event):
            raise HTTPException(409, "workbench_approval_completion_invalid")
        case_delete_completion = (event.event_kind == "approval_completed" and (
            (0 <= run.cursor < len(steps) and steps[run.cursor].get("action") == "CASE_DELETE")
            or (run.checkpoint.get("applied_case_delete") or {}).get("event_id") == str(event.id)))
        if case_delete_completion and not _verified_case_delete_completion(db, run, event):
            raise HTTPException(409, "workbench_approval_completion_invalid")
        # Only the exact already-applied human approval may acknowledge removal
        # of its original sources. Subsequent next_step claims remain strict.
        validate_binding(db, run, allow_legacy=delete_completion or case_delete_completion)
    except HTTPException as error:
        run.status, event.status = "invalidated", "invalidated"
        event.receipt = {"error_code": error.detail}
        return None
    token = uuid4()
    event.status, event.claim_token = "running", token
    event.attempts += 1
    run.status = "running"
    db.flush()
    return run, event, token


def reserve_budget(db, run_id, amounts):
    run = load_run(db, run_id, for_update=True)
    if run.status in TERMINAL | {"paused_question"} or run.cancelled_at is not None:
        return False
    if any(key not in run.budget or not isinstance(value, int) or isinstance(value, bool)
           or value < 0 for key, value in amounts.items()):
        raise ValueError("invalid_workbench_budget_reservation")
    used = dict(run.used)
    if any(used.get(key, 0) + value > run.budget[key] for key, value in amounts.items()):
        run.status = "budget_exhausted"
        return False
    run.used = {**used, **{key: used.get(key, 0) + value for key, value in amounts.items()}}
    db.flush()
    return True


def complete_event(db, event_id, claim_token, receipt, status="waiting", checkpoint=None,
                   advance_cursor=True):
    event = db.get(WorkbenchContinuation, UUID(str(event_id)))
    if event is None:
        raise HTTPException(404, "workbench_event_not_found")
    run = load_run(db, event.run_id, for_update=True)
    db.refresh(event, with_for_update=True)
    if event.status == "completed" and str(event.claim_token) == str(claim_token):
        return event
    if run.status == "paused_question":
        raise HTTPException(409, "workbench_run_paused")
    if (event.status != "running" or str(event.claim_token) != str(claim_token)
            or run.epoch != event.expected_epoch or run.cursor != event.cursor
            or run.cancelled_at is not None or run.status in TERMINAL):
        raise HTTPException(409, "workbench_continuation_obsolete")
    event.status, event.receipt = "completed", deepcopy(receipt)
    run.status = status
    if checkpoint is not None:
        run.checkpoint = deepcopy(checkpoint)
    if advance_cursor:
        run.cursor += 1
    db.flush()
    return event


def cancel_run(db, run_id):
    run = load_run(db, run_id, for_update=True)
    if run.status == "cancelled":
        return run
    if run.status == "completed":
        raise HTTPException(409, "workbench_run_already_completed")
    run.status, run.cancelled_at = "cancelled", datetime.now(UTC)
    run.epoch += 1
    _invalidate_events(db, run, "cancelled")
    return run


def _invalidate_events(db, run, status):
    ids = list(db.scalars(select(WorkbenchContinuation.id).where(
        WorkbenchContinuation.run_id == run.id,
        WorkbenchContinuation.status.in_(["pending", "running"]))))
    db.execute(update(WorkbenchContinuation).where(WorkbenchContinuation.id.in_(ids))
               .values(status=status))
    db.execute(update(TaskOutbox).where(TaskOutbox.task_name == TASK_NAME,
               TaskOutbox.task_id.in_([str(value) for value in ids]),
               TaskOutbox.status == "pending").values(status="cancelled"))


def invalidate_runs(db, conversation_id, reason="new_user_instruction"):
    runs = list(db.scalars(select(WorkbenchRun).where(
        WorkbenchRun.conversation_id == UUID(str(conversation_id)),
        WorkbenchRun.status.not_in(TERMINAL)).with_for_update()))
    for run in runs:
        run.status, run.epoch = "invalidated", run.epoch + 1
        run.checkpoint = {**run.checkpoint, "invalidation_reason": reason}
        _invalidate_events(db, run, "invalidated")
    return len(runs)


def recover_claim(db, event_id):
    """Only call while holding the executor's transaction advisory RUN guard.

    That guard's disappearance proves the previous executor is gone; a clock or
    Redis lease expiring is never sufficient evidence to steal a slow model call.
    Reserved budgets intentionally remain spent after a crash.
    """
    event = db.get(WorkbenchContinuation, UUID(str(event_id)))
    if event is None:
        return False
    run = load_run(db, event.run_id, for_update=True)
    db.refresh(event, with_for_update=True)
    if (event.status != "running" or event.receipt or run.status in TERMINAL | {"paused_question"}
            or event.expected_epoch != run.epoch or event.cursor != run.cursor):
        return False
    event.status, event.claim_token = "pending", None
    db.flush()
    return True


_APPROVAL_ISSUER = object()


@dataclass(frozen=True)
class ApprovalBinding:
    """Process-local proof captured in this exact approval DB transaction."""
    run_id: UUID
    epoch: int
    cursor: int
    conversation_id: UUID
    source_kind: str
    source_id: str
    source_version: str
    binding_json: str
    eligible_refs: frozenset[str]
    transaction: object = field(repr=False, compare=False)
    issuer: object = field(repr=False, compare=False)
    waiting_job_id: str | None = None
    collection_action: str | None = None
    collection_id: str | None = None
    normalized_binding_json: str | None = None


def _approval_match(db, run, source_kind, source_id, source_version):
    from casepilot_api.models import CaseChangeSet, GenerationJob, WorkspaceTestBrief

    checkpoint = dict(run.checkpoint)
    if (str(checkpoint.get("waiting_artifact_id")) == str(source_id)
            and checkpoint.get("waiting_artifact_kind") == source_kind):
        expected = checkpoint.get("waiting_artifact_version")
        if expected is not None and str(expected) != str(source_version):
            raise HTTPException(409, "workbench_approval_version_changed")
        return True, None
    waiting_job = checkpoint.get("waiting_job_id")
    job = db.get(GenerationJob, UUID(str(waiting_job))) if waiting_job else None
    if (job is None or str(job.input_payload.get("workbench_run_id")) != str(run.id)
            or job.input_payload.get("workbench_epoch") != run.epoch
            or job.input_payload.get("workbench_cursor") != run.cursor
            or str(getattr(job.status, "value", job.status)) != "completed"):
        return False, None
    matches = source_kind == "candidates" and str(source_id) == str(job.id)
    if source_kind == "test_brief":
        brief = db.get(WorkspaceTestBrief, UUID(str(source_id)))
        matches = (brief is not None and brief.conversation_id == run.conversation_id
                   and str(brief.source_operation_id) == str(checkpoint.get("waiting_operation_id"))
                   and str(brief.version) == str(source_version))
    elif source_kind == "change_set":
        change = db.get(CaseChangeSet, UUID(str(source_id)))
        matches = (change is not None and change.conversation_id == run.conversation_id
                   and change.generation_job_id == job.id
                   and change_set_version(change) == str(source_version))
    return matches, str(job.id) if matches else None


def _artifact_refs(db, run, source_kind, source_id, *, binding=None):
    from casepilot_api.models import CaseChangeSet

    if source_kind == "collection_proposal":
        proposal = dict(db.get(Conversation, run.conversation_id).context).get(
            "workbench_collection_proposal") or {}
        if str(proposal.get("id")) != str(source_id) or proposal.get("status") != "pending":
            raise HTTPException(409, "workbench_approval_artifact_changed")
        if proposal.get("action") != "delete":
            return frozenset()
        ids = set(db.scalars(select(CollectionCaseMembership.test_case_id).where(
            CollectionCaseMembership.collection_id == UUID(proposal["collection_id"]))))
        return frozenset(source["ref"] for source in (binding or run.binding)["sources"]
                         if source["ref"].startswith("asset:")
                         and UUID(source["ref"].split(":", 1)[1]) in ids)
    if source_kind not in {"change_set", "candidates"}:
        return frozenset()
    try:
        identifier = UUID(str(source_id))
    except ValueError:
        # No entity => no authorized effect refs; useful for nonmutating state fixtures.
        return frozenset()
    if source_kind == "candidates":
        return frozenset(f"candidate:{item.ref}" for item in db.scalars(
            select(WorkspaceCandidate).where(
                WorkspaceCandidate.conversation_id == run.conversation_id,
                WorkspaceCandidate.generation_job_id == identifier,
                WorkspaceCandidate.status == "candidate")))
    change = db.get(CaseChangeSet, identifier)
    if change is None or change.conversation_id != run.conversation_id:
        raise HTTPException(409, "workbench_approval_artifact_changed")
    return frozenset(
        f"asset:{item.get('test_case_id') or item['ref']}"
        if item.get("target_type") == "formal" else f"candidate:{item['ref']}"
        for item in change.items if item.get("status") not in {"applied", "rejected"}
    )


def capture_approval_binding(db, conversation, source_kind, source_id, source_version):
    """Must run after the conversation lock and BEFORE any approval domain write."""
    from casepilot_api.workbench_scope import validate_authorized_scope

    db.flush()
    runs = list(db.scalars(select(WorkbenchRun).where(
        WorkbenchRun.conversation_id == conversation.id,
        WorkbenchRun.status.not_in(TERMINAL)).with_for_update()))
    for run in runs:
        matches, waiting_job = _approval_match(db, run, source_kind, source_id, source_version)
        if not matches:
            continue
        if run.status == "paused_question":
            raise HTTPException(409, "workbench_run_paused")
        validate_binding(db, run, conversation, allow_legacy=True)
        if "authorized_scope_request" in run.checkpoint or "original_request" in run.checkpoint:
            validate_authorized_scope(db, run, conversation)
        proposal = (dict(conversation.context).get("workbench_collection_proposal") or {}
                    if source_kind == "collection_proposal" else {})
        normalized = None
        if (proposal.get("action") == "delete"
                and (conversation.context or {}).get("workbench_selection") is None):
            # Resolve immutable legacy identities BEFORE the effect, without
            # migrating context or rebinding the run's original CAS snapshot.
            from casepilot_api.workbench_selection import effective_selection

            effective = effective_selection(db, db.get(Account, run.account_id), conversation)
            normalized = {**run.binding, "sources": [
                {"ref": item["ref"], "version": str(item["version"])}
                for item in effective["items"]]}
        return ApprovalBinding(
            run.id, run.epoch, run.cursor, conversation.id, source_kind, str(source_id),
            str(source_version), json.dumps(run.binding, sort_keys=True),
            _artifact_refs(db, run, source_kind, source_id, binding=normalized),
            db.get_transaction(),
            _APPROVAL_ISSUER, waiting_job, proposal.get("action"), proposal.get("collection_id"),
            json.dumps(normalized, sort_keys=True) if normalized is not None else None,
        )
    return None


def _approved_binding_delta(db, run, conversation, token, updates, removed, adopted, destination):
    changed = set(updates) | set(removed) | set(adopted)
    collection_delete = False
    if token.source_kind == "collection_proposal" and token.collection_action == "delete":
        deleted = db.get(CaseCollection, UUID(token.collection_id), populate_existing=True)
        collection_delete = (deleted is not None and deleted.space_id == run.space_id
                             and deleted.deleted_at is not None)
        if not collection_delete:
            raise HTTPException(409, "workbench_approval_effect_mismatch")
    if not changed <= token.eligible_refs or set(updates) & (set(removed) | set(adopted)):
        raise HTTPException(409, "workbench_approval_delta_outside_artifact")
    if adopted and token.source_kind != "candidates":
        raise HTTPException(409, "workbench_approval_adoption_invalid")
    for ref, version in updates.items():
        if ref.startswith("asset:"):
            case = db.get(TestCase, UUID(ref.split(":", 1)[1]), populate_existing=True)
            valid = (case is not None and case.space_id == run.space_id and case.deleted_at is None
                     and str(case.current_revision_id) == str(version))
        else:
            candidate = db.scalar(select(WorkspaceCandidate).where(
                WorkspaceCandidate.conversation_id == run.conversation_id,
                WorkspaceCandidate.ref == ref.split(":", 1)[1],
                WorkspaceCandidate.version == int(version),
                WorkspaceCandidate.status == "candidate"))
            valid = candidate is not None
        if not valid:
            raise HTTPException(409, "workbench_approval_effect_mismatch")
    for ref in removed:
        if ref.startswith("asset:"):
            case = db.get(TestCase, UUID(ref.split(":", 1)[1]), populate_existing=True)
            valid = (case is not None and case.space_id == run.space_id
                     and case.deleted_at is not None)
            if collection_delete:
                available = db.scalar(select(CollectionCaseMembership.test_case_id).join(
                    CaseCollection, CaseCollection.id == CollectionCaseMembership.collection_id
                ).where(CollectionCaseMembership.test_case_id == case.id,
                        CaseCollection.space_id == run.space_id,
                        CaseCollection.deleted_at.is_(None))) if case is not None else None
                valid = (case is not None and case.space_id == run.space_id
                         and case.deleted_at is None and available is None)
        else:
            candidate = db.scalar(select(WorkspaceCandidate).where(
                WorkspaceCandidate.conversation_id == run.conversation_id,
                WorkspaceCandidate.ref == ref.split(":", 1)[1]).order_by(
                    WorkspaceCandidate.version.desc()).limit(1))
            valid = candidate is not None and candidate.status in {"incorporated", "discarded"}
        if not valid:
            raise HTTPException(409, "workbench_approval_effect_mismatch")
    for ref, mapped in adopted.items():
        if (not ref.startswith("candidate:") or not isinstance(mapped, dict)
                or set(mapped) != {"ref", "version"} or not mapped["ref"].startswith("asset:")):
            raise HTTPException(409, "workbench_approval_adoption_invalid")
        case = db.get(TestCase, UUID(mapped["ref"].split(":", 1)[1]), populate_existing=True)
        candidate = db.scalar(select(WorkspaceCandidate).where(
            WorkspaceCandidate.conversation_id == run.conversation_id,
            WorkspaceCandidate.ref == ref.split(":", 1)[1],
            WorkspaceCandidate.generation_job_id == UUID(token.source_id),
            WorkspaceCandidate.status == "incorporated"))
        if (case is None or case.space_id != run.space_id or case.deleted_at is not None
                or str(case.current_revision_id) != str(mapped["version"]) or candidate is None):
            raise HTTPException(409, "workbench_approval_effect_mismatch")
    before = json.loads(token.normalized_binding_json or token.binding_json)
    after = selection_binding(conversation)
    actual = {item["ref"]: item["version"] for item in after["sources"]}
    expected = []
    for item in before["sources"]:
        ref = item["ref"]
        if ref in adopted:
            mapped = adopted[ref]
            # Existing adoption may remove canonical drafts or explicitly map
            # them to formal assets. Never add an unrelated canonical member.
            if mapped["ref"] in actual:
                expected.append({"ref": mapped["ref"], "version": str(mapped["version"])})
        elif ref not in removed:
            expected.append({"ref": ref, "version": str(updates.get(ref, item["version"]))})
    if after["sources"] != expected:
        raise HTTPException(409, "workbench_approval_binding_delta_invalid")
    expected_destination = before["destination_collection_id"]
    if destination == "" and collection_delete:
        if before["destination_collection_id"] != token.collection_id:
            raise HTTPException(409, "workbench_approval_destination_invalid")
        expected_destination = None
    elif destination is not None:
        if token.source_kind != "operation_collection":
            raise HTTPException(409, "workbench_approval_destination_invalid")
        collection = db.get(CaseCollection, UUID(str(destination)))
        if collection is None or collection.space_id != run.space_id or collection.deleted_at:
            raise HTTPException(409, "workbench_approval_destination_invalid")
        expected_destination = str(destination)
    if after["destination_collection_id"] != expected_destination:
        raise HTTPException(409, "workbench_approval_destination_invalid")
    if (after["selection_version"] < before["selection_version"] or
            (after["selection_version"] != before["selection_version"]
             and not changed and destination is None and not collection_delete)):
        raise HTTPException(409, "workbench_approval_binding_delta_invalid")
    return after

def record_approval(db, conversation, source_kind, source_id, source_version,
                    next_job_id=None, complete=True, rejected=False, *,
                    preapproval_binding=None, approved_updates=None, removed_refs=None,
                    adopted_sources=None, approved_destination_id=None):
    from casepilot_api.models import GenerationJob
    from casepilot_api.workbench_scope import apply_authorized_scope_delta

    db.flush()
    token = preapproval_binding
    if token is None:
        # Legacy calls without a durable waiting run remain unchanged. A caller
        # cannot skip the pre-write guard for an existing durable approval.
        runs = db.scalars(select(WorkbenchRun).where(
            WorkbenchRun.conversation_id == conversation.id,
            WorkbenchRun.status.not_in(TERMINAL)))
        if any(_approval_match(db, run, source_kind, source_id, source_version)[0] for run in runs):
            raise HTTPException(409, "workbench_approval_binding_required")
        return None
    if (not isinstance(token, ApprovalBinding) or token.issuer is not _APPROVAL_ISSUER
            or token.transaction is not db.get_transaction()
            or token.conversation_id != conversation.id or token.source_kind != source_kind
            or token.source_id != str(source_id) or token.source_version != str(source_version)):
        raise HTTPException(409, "workbench_approval_binding_invalid")
    run = load_run(db, token.run_id, for_update=True)
    if run.status == "paused_question":
        raise HTTPException(409, "workbench_run_paused")
    if (run.status in TERMINAL or run.epoch != token.epoch or run.cursor != token.cursor
            or json.dumps(run.binding, sort_keys=True) != token.binding_json):
        raise HTTPException(409, "workbench_approval_binding_changed")
    updates = {str(ref): str(version) for ref, version in (approved_updates or {}).items()}
    removed, adopted = set(removed_refs or ()), deepcopy(adopted_sources or {})
    new_binding = _approved_binding_delta(db, run, conversation, token, updates, removed,
                                          adopted, approved_destination_id)
    apply_authorized_scope_delta(db, run, conversation, approved_updates=updates,
        removed_refs=removed, adopted_sources=adopted,
        approved_destination_id=approved_destination_id)
    checkpoint = dict(run.checkpoint)
    if token.waiting_job_id:
        checkpoint.update(waiting_job_id=None, waiting_artifact_kind=source_kind,
            waiting_artifact_id=str(source_id), waiting_artifact_version=str(source_version))
        run.checkpoint = checkpoint
        stale_ids = list(db.scalars(select(WorkbenchContinuation.id).where(
            WorkbenchContinuation.run_id == run.id,
            WorkbenchContinuation.event_kind == "job_completed",
            WorkbenchContinuation.source_id == token.waiting_job_id,
            WorkbenchContinuation.status.in_(["pending", "running"]))))
        db.execute(update(WorkbenchContinuation).where(
            WorkbenchContinuation.id.in_(stale_ids)).values(status="invalidated"))
        db.execute(update(TaskOutbox).where(TaskOutbox.task_name == TASK_NAME,
            TaskOutbox.task_id.in_([str(value) for value in stale_ids]),
            TaskOutbox.status == "pending").values(status="cancelled"))
    event_kind = ("approval_rejected" if rejected else
                  "approval_completed" if complete else "approval_partial")
    outcome = "rejected" if rejected else "approved" if complete else "partial"
    event = enqueue_event(db, run, event_kind, source_id, source_version, {
        "outcome": outcome, "source_kind": source_kind,
        "source_operation_id": checkpoint.get("waiting_operation_id"),
        "next_job_id": str(next_job_id) if next_job_id else None, "binding": new_binding,
    })
    run.binding = new_binding
    if (complete and not rejected and next_job_id is None
            and token.source_kind == "collection_proposal" and token.collection_action == "delete"):
        run.checkpoint = {**run.checkpoint, "applied_collection_delete": {
            "event_id": str(event.id), "run_id": str(run.id),
            "root_message_id": str(run.root_message_id), "request_id": str(run.request_id),
            "epoch": run.epoch, "cursor": run.cursor,
            "proposal_id": str(source_id), "proposal_version": str(source_version),
            "collection_id": token.collection_id, "binding": deepcopy(new_binding),
        }}
    steps = run.plan.get("steps") or []
    if (complete and not rejected and next_job_id is None and token.source_kind == "change_set"
            and 0 <= run.cursor < len(steps) and steps[run.cursor].get("action") == "CASE_DELETE"):
        from casepilot_api.models import CaseChangeSet
        effect = _case_delete_effect(db, run, db.get(CaseChangeSet, UUID(str(source_id))))
        if effect is not None and set(effect["removed_refs"]) == removed == token.eligible_refs:
            run.checkpoint = {**run.checkpoint, "waiting_artifact_version": str(source_version),
                              "applied_case_delete": {
                "event_id": str(event.id), "run_id": str(run.id),
                "root_message_id": str(run.root_message_id), "request_id": str(run.request_id),
                "epoch": run.epoch, "cursor": run.cursor,
                "change_set_id": str(source_id), "reviewed_version": str(source_version),
                "binding": deepcopy(new_binding), **effect}}
    if next_job_id:
        if not complete or rejected:
            raise HTTPException(409, "workbench_partial_approval_cannot_dispatch")
        job = db.get(GenerationJob, UUID(str(next_job_id)))
        if (job is None or job.account_id != run.account_id or job.space_id != run.space_id
                or str(job.input_payload.get("conversation_id")) != str(conversation.id)):
            raise HTTPException(409, "workbench_approval_job_mismatch")
        job.input_payload = {**job.input_payload, "workbench_run_id": str(run.id),
                             "workbench_epoch": run.epoch, "workbench_cursor": run.cursor}
        run.checkpoint = {**checkpoint, "waiting_job_id": str(job.id),
                          "waiting_artifact_id": None, "waiting_artifact_kind": None,
                          "waiting_artifact_version": None}
        run.status = "waiting_job"
    elif not complete or rejected:
        run.status = "cancelled" if rejected else "waiting_approval"
        if rejected:
            run.cancelled_at = datetime.now(UTC)
            run.epoch += 1
    # A launched job supplies the next observation. Partial/rejected reviews
    # do not authorize automatic further work. Keep a durable event receipt.
    if next_job_id or not complete or rejected:
        event.status = "completed"
        event.receipt = {"outcome": outcome, "next_job_id": str(next_job_id)
                         if next_job_id else None}
        db.execute(update(TaskOutbox).where(TaskOutbox.task_name == TASK_NAME,
            TaskOutbox.task_id == str(event.id), TaskOutbox.status == "pending")
            .values(status="cancelled"))
    if rejected:
        _invalidate_events(db, run, "cancelled")
    db.flush()
    return event

def reserve_initial_segment(session_factory, account_id, conversation_id, request_id,
                            amounts, budget=None):
    """Reserve before first model request without committing the user transaction.

    No FK reads or conversation locks: the caller may own an uncommitted message
    and locked conversation. Failed/uncertain attempts remain charged; same-ID
    retries reserve again, never reset cumulative spend. No provider secrets/text.
    """
    limits = dict(DEFAULT_BUDGET if budget is None else budget)
    if (not limits or any(not isinstance(v, int) or isinstance(v, bool) or v < 0
                          for v in limits.values())
            or any(key not in limits or not isinstance(v, int) or isinstance(v, bool) or v < 0
                   for key, v in amounts.items())):
        raise ValueError("invalid_workbench_budget_reservation")
    identity = tuple(UUID(str(value)) for value in (account_id, conversation_id, request_id))
    with session_factory() as db:
        db.execute(insert(WorkbenchReservation).values(
            account_id=identity[0], conversation_id=identity[1], request_id=identity[2],
            budget=limits, used={}, created_at=datetime.now(UTC),
        ).on_conflict_do_nothing())
        row = db.scalar(select(WorkbenchReservation).where(
            WorkbenchReservation.account_id == identity[0],
            WorkbenchReservation.conversation_id == identity[1],
            WorkbenchReservation.request_id == identity[2]).with_for_update())
        if row.cancelled_at is not None:
            raise HTTPException(409, "workbench_run_cancelled")
        if row.budget != limits:
            raise HTTPException(409, "workbench_budget_policy_changed")
        used = dict(row.used)
        if any(used.get(key, 0) + value > row.budget[key] for key, value in amounts.items()):
            raise HTTPException(409, "workbench_budget_exhausted")
        row.used = {**used, **{key: used.get(key, 0) + value for key, value in amounts.items()}}
        db.commit()
        return {"budget": dict(row.budget), "used": dict(row.used)}



def cancel_initial_reservation(db, account_id, conversation_id, request_id):
    """Persist a cancellation even while the first submission/root is uncommitted."""
    now = datetime.now(UTC)
    db.execute(insert(WorkbenchReservation).values(
        account_id=account_id, conversation_id=conversation_id, request_id=request_id,
        budget=DEFAULT_BUDGET, used={}, cancelled_at=now, created_at=now,
    ).on_conflict_do_update(
        index_elements=[WorkbenchReservation.account_id, WorkbenchReservation.conversation_id,
                        WorkbenchReservation.request_id],
        set_={"cancelled_at": now},
    ))
    db.flush()


def invalidate_run(db, run_id, reason="new_mutating_instruction"):
    run = load_run(db, run_id, for_update=True)
    if run.status in TERMINAL:
        return run
    run.status, run.epoch = "invalidated", run.epoch + 1
    run.checkpoint = {**run.checkpoint, "invalidation_reason": reason}
    _invalidate_events(db, run, "invalidated")
    db.flush()
    return run
