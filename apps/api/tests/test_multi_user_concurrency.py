"""Two-account isolation and deterministic overlapping database transactions."""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import delete, text, update
from starlette.datastructures import Headers

from casepilot_api import cases, conversations, generation, knowledge
from casepilot_api.case_management import create_test_case
from casepilot_api.database import get_session_factory
from casepilot_api.models import (
    Account,
    CandidateRevision,
    CaseCollection,
    Conversation,
    ExecutionRun,
    GenerationJob,
    Space,
    SpaceMembership,
)
from casepilot_api.schemas import TestCaseCreate as CaseCreate
from casepilot_api.schemas import WorkspaceStateUpdate


@pytest.fixture
def team():
    factory = get_session_factory()
    with factory() as db:
        accounts = [
            Account(
                email=f"concurrency-{uuid4()}@test.local", display_name=name, password_hash="unused"
            )
            for name in ("A", "B")
        ]
        space = Space(name="Isolated concurrency regression")
        db.add_all([space, *accounts])
        db.flush()
        collection = CaseCollection(space_id=space.id, name="Shared assets")
        db.add_all(
            [collection, *(SpaceMembership(space_id=space.id, account_id=a.id) for a in accounts)]
        )
        db.commit()
    try:
        yield factory, accounts, space, collection
    finally:
        with factory() as db:
            db.execute(delete(ExecutionRun).where(ExecutionRun.space_id == space.id))
            db.execute(delete(Space).where(Space.id == space.id))
            db.execute(delete(Account).where(Account.id.in_([a.id for a in accounts])))
            db.commit()


def workspace(team):
    factory, accounts, _, collection = team
    with factory() as db:
        return conversations.get_or_create_workspace(collection.id, accounts[0], db)


def test_workspace_draft_and_direct_access_are_account_scoped(team):
    factory, (a, b), _, collection = team

    def open_workspace(account):
        with factory() as db:
            return conversations.get_or_create_workspace(collection.id, account, db)

    with ThreadPoolExecutor(max_workers=4) as pool:
        first, second, again, other = list(pool.map(open_workspace, [a, b, a, b]))
    assert first.id == again.id
    assert second.id == other.id
    assert first.id != second.id
    with factory() as db:
        conversations.update_workspace_state(
            first.id, WorkspaceStateUpdate(draft_text="A draft"), a, db
        )
    with factory() as db:
        latest = conversations.get_latest_conversation(collection.id, b, db)
        assert latest.id == second.id
        assert latest.context["draft_text"] == ""
        with pytest.raises(HTTPException) as denied:
            conversations.get_conversation(first.id, b, db)
        assert denied.value.status_code == 404


def test_generation_job_cannot_be_read_or_cancelled_by_other_member(team):
    factory, (a, b), space, collection = team
    with factory() as db:
        job = GenerationJob(
            space_id=space.id,
            account_id=a.id,
            collection_id=collection.id,
            operation="generate",
            status="queued",
            stage="queued",
        )
        db.add(job)
        db.commit()
    with factory() as db:
        assert generation.ensure_job_access(db, a, job.id).id == job.id
        for action in (generation.get_generation, generation.cancel_generation):
            with pytest.raises(HTTPException) as denied:
                action(job.id, b, db)
            assert denied.value.status_code == 404


def test_concurrent_uploads_merge_references_and_keep_new_task(team, monkeypatch, tmp_path):
    factory, (a, _), _, _ = team
    current = workspace(team)
    monkeypatch.setattr(knowledge.settings, "knowledge_storage_path", str(tmp_path))
    monkeypatch.setattr(knowledge, "enqueue_task", lambda *args, **kwargs: None)
    barrier = Barrier(2)
    original_store = conversations._store_uploads
    new_job_id = str(uuid4())

    def store_with_overlap(*args, **kwargs):
        result = original_store(*args, **kwargs)
        # Both requests loaded the old context before either links its uploads.
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(conversations, "_store_uploads", store_with_overlap)

    def upload(number):
        with factory() as db:
            return conversations.upload_conversation_attachments(
                current.id,
                a,
                db,
                [
                    UploadFile(
                        filename=f"{number}.txt",
                        file=BytesIO(b"Login requirement"),
                        headers=Headers({"content-type": "text/plain"}),
                    )
                ],
            )

    # Keep the original context resident in each handler through an upload callback.
    def overlap_with_task(*args, **kwargs):
        result = store_with_overlap(*args, **kwargs)
        with factory() as db:
            db.execute(
                update(Conversation)
                .where(Conversation.id == current.id)
                .values(
                    context=Conversation.context.op("||")(
                        {"phase": "generating", "active_job_id": new_job_id}
                    )
                )
            )
            db.commit()
        return result

    monkeypatch.setattr(conversations, "_store_uploads", overlap_with_task)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(upload, [1, 2]))
    with factory() as db:
        context = db.get(Conversation, current.id).context
        assert set(context["document_ids"]) == {str(doc) for r in results for doc in r.document_ids}
        assert set(context["knowledge_source_ids"]) == {str(r.source.id) for r in results}
        assert context["active_job_id"] == new_job_id
        assert context["phase"] == "generating"


def test_stale_recovery_preserves_new_generation_and_other_context(team):
    factory, (a, _), space, collection = team
    current = workspace(team)
    with factory() as db:
        old = GenerationJob(
            space_id=space.id,
            account_id=a.id,
            collection_id=collection.id,
            operation="generate",
            status="completed",
            stage="completed",
        )
        new = GenerationJob(
            space_id=space.id,
            account_id=a.id,
            collection_id=collection.id,
            operation="generate",
            status="queued",
            stage="queued",
        )
        db.add_all([old, new])
        db.flush()
        db.get(Conversation, current.id).context = {
            "phase": "generating",
            "active_job_id": str(old.id),
        }
        db.commit()
    with factory() as reader:
        stale = reader.get(Conversation, current.id)
        with factory() as writer:
            writer.execute(
                update(Conversation)
                .where(Conversation.id == current.id)
                .values(
                    context={
                        "phase": "generating",
                        "active_job_id": str(new.id),
                        "draft_text": "keep",
                    }
                )
            )
            writer.commit()
        conversations.recover_terminal_workspace_job(reader, stale)
        assert stale.context == {
            "phase": "generating",
            "active_job_id": str(new.id),
            "draft_text": "keep",
        }
    # Recovery still works for an actually terminal current job.
    with factory() as db:
        db.get(GenerationJob, new.id).status = "completed"
        db.commit()
        conversations.recover_terminal_workspace_job(db, db.get(Conversation, current.id))
        assert db.get(Conversation, current.id).context["active_job_id"] is None
        assert db.get(Conversation, current.id).context["draft_text"] == "keep"


@pytest.mark.parametrize("first_action", ["reject", "apply"])
def test_candidate_decisions_recheck_state_after_overlapping_read(team, first_action):
    factory, (a, b), _, collection = team
    with factory() as db:
        case = create_test_case(
            collection.id,
            CaseCreate(title="Original", steps=[{"action": "Log in", "expected": "Success"}]),
            a,
            db,
        )
        candidate = CandidateRevision(
            test_case_id=case.id,
            base_revision_id=case.current_revision_id,
            instruction="rewrite",
            proposed_snapshot={
                "title": "Updated",
                "steps": [{"action": "Log in", "expected": "Session returned"}],
            },
        )
        db.add(candidate)
        db.commit()
    with factory() as delayed:
        stale, _ = cases.get_candidate_access(delayed, a.id, candidate.id)
        assert stale.status == "pending"
        with factory() as first:
            if first_action == "reject":
                cases.reject_candidate(candidate.id, b, first)
            else:
                cases.apply_candidate(candidate.id, b, first)
        if first_action == "reject":
            with pytest.raises(HTTPException) as conflict:
                cases.apply_candidate(candidate.id, a, delayed)
            assert conflict.value.detail == "candidate_not_pending"
        else:
            assert cases.reject_candidate(candidate.id, a, delayed).status == "applied"


def test_workspace_open_does_not_invert_message_collection_lock_order(team):
    factory, (a, _), _, collection = team
    current = workspace(team)
    both_locked = Barrier(2)

    def message_write():
        with factory() as db:
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            conversation = db.get(Conversation, current.id)
            conversations._require_idle_conversation(db, conversation)
            both_locked.wait(timeout=10)
            shared = db.get(CaseCollection, collection.id)
            db.refresh(shared, with_for_update=True)
            shared.description = "Concurrent message updated collection"
            db.commit()

    def open_workspace():
        with factory() as db:
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            refresh = db.refresh

            def synchronized_refresh(instance, *args, **kwargs):
                refresh(instance, *args, **kwargs)
                if isinstance(instance, CaseCollection) and kwargs.get("with_for_update"):
                    both_locked.wait(timeout=10)

            db.refresh = synchronized_refresh
            return conversations.get_or_create_workspace(collection.id, a, db)

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(message_write)
        reader = pool.submit(open_workspace)
        writer.result(timeout=15)
        assert reader.result(timeout=15).id == current.id


def test_overlapping_execution_saves_reject_stale_version(team):
    from casepilot_api.case_management import (
        create_execution_run_from_cases,
        update_execution_record,
    )
    from casepilot_api.models import ExecutionRecord, TestCase
    from casepilot_api.schemas import ExecutionRecordUpdate, ExecutionRunCreate

    factory, (account, _), space, collection = team
    with factory() as db:
        case = create_test_case(
            collection.id,
            CaseCreate(title="Concurrent result", steps=[{"action": "Act", "expected": "Pass"}]),
            account, db,
        )
        run = create_execution_run_from_cases(
            db, account=account,
            payload=ExecutionRunCreate(description="Race", assignee_ids=[account.id]),
            space_id=space.id, cases=[db.get(TestCase, case.id)], collection_id=collection.id,
            playlist_id=None, source_type="collection", source_name="Race",
            source_collection_count=1,
        )
        record = run.records[0]
    barrier = Barrier(2)

    def save(value):
        with factory() as db:
            original_get = db.get

            def overlapping_get(model, *args, **kwargs):
                row = original_get(model, *args, **kwargs)
                if model is ExecutionRecord:
                    barrier.wait(timeout=10)
                return row

            db.get = overlapping_get
            try:
                result = update_execution_record(
                    record.id,
                    ExecutionRecordUpdate(
                        status="passed", actual_result=value, base_updated_at=record.updated_at,
                    ), account, db,
                )
                return result.actual_result
            except HTTPException as error:
                assert error.status_code == 409
                return error.detail

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ["A", "B"]))
    assert results.count("execution_record_changed") == 1
    with factory() as db:
        assert db.get(ExecutionRecord, record.id).actual_result in results
