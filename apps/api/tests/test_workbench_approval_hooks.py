"""Real ASGI/PG exact human-review transactions; no model calls."""
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_workbench_bridge_integration import setup
from test_workbench_reuse_journey import create_case

from casepilot_api import workbench_continuation
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import (
    Account,
    CaseChangeSet,
    Conversation,
    ConversationMessage,
    ConversationOperation,
    TaskOutbox,
    WorkbenchContinuation,
    WorkbenchRun,
)
from casepilot_api.models import TestCase as CaseRecord
from casepilot_api.workbench_artifact_version import change_set_version
from casepilot_api.workbench_continuation import TASK_NAME, create_run


async def review_fixture(client):
    owner, collection, workspace = await setup(client)
    cases = [await create_case(client, collection["id"], f"Review {index}") for index in range(2)]
    selected = await client.patch(f"/api/v1/workspaces/{workspace['id']}/selection", json={
        "base_version": 0, "action": "replace", "active_collection_id": collection["id"],
        "sources": [{"ref": f"asset:{case['id']}", "version": case["current_revision_id"]}
                    for case in cases]})
    assert selected.status_code == 200, selected.text
    state = selected.json()["context"]["workbench_selection"]
    with get_session_factory()() as db:
        conversation = db.get(Conversation, UUID(workspace["id"]))
        user = ConversationMessage(conversation_id=conversation.id, role="user",
                                   content="改为P2后查询",
                                   status="completed", target_case_ids=[], citations=[],
                                   message_metadata={})
        db.add(user)
        db.flush()
        items = [{"ref": case["id"], "test_case_id": case["id"], "target_type": "formal",
                  "base_revision_id": case["current_revision_id"], "operation": "modify",
                  "base_snapshot": case, "proposed_snapshot": {**case, "priority": "P2"},
                  "field_diff": [{"field": "priority", "before": "P1", "after": "P2"}],
                  "status": "ready"} for case in cases]
        change = CaseChangeSet(conversation_id=conversation.id, status="ready", instruction="P2",
                               items=items, created_by=UUID(owner["id"]))
        db.add(change)
        db.flush()
        operation = ConversationOperation(conversation_id=conversation.id, message_id=user.id,
            sequence=1, intent="CASE_MODIFY", status="awaiting_confirmation", target={},
            payload={"selection_version": state["version"],
                     "destination_collection_id": collection["id"]},
            result={}, related_change_set_id=change.id)
        db.add(operation)
        db.flush()
        run = create_run(db, db.get(Account, UUID(owner["id"])), conversation, user.id, uuid4())
        run.status = "waiting_approval"
        run.checkpoint = {"waiting_artifact_kind": "change_set",
                          "waiting_artifact_id": str(change.id),
                          "waiting_artifact_version": change_set_version(change),
                          "waiting_operation_id": str(operation.id)}
        ids = (run.id, change.id, operation.id)
        db.commit()
    return ids, cases


@pytest.mark.asyncio
async def test_partial_exact_review_rebases_then_final_enqueues_once():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        (run_id, change_id, _), cases = await review_fixture(client)
        url = f"/api/v1/case-change-sets/{change_id}/apply"
        response = await client.post(url, json={"review_refs": [cases[0]["id"]]})
        assert response.status_code == 200, response.text
        with get_session_factory()() as db:
            run = db.get(WorkbenchRun, run_id)
            change = db.get(CaseChangeSet, change_id)
            assert run.status == "waiting_approval" and run.cursor == 0
            assert run.checkpoint["waiting_artifact_version"] == change_set_version(change)
            partial = db.scalar(select(WorkbenchContinuation).where(
                WorkbenchContinuation.run_id == run_id))
            assert partial.event_kind == "approval_partial" and partial.status == "completed"
            assert db.scalar(select(TaskOutbox).where(
                TaskOutbox.task_name == TASK_NAME,
                TaskOutbox.task_id == str(partial.id))).status == (
                    "cancelled")
            assert db.get(CaseRecord, UUID(cases[1]["id"])).current_revision_id == UUID(
                cases[1]["current_revision_id"])
        response = await client.post(url, json={"review_refs": [cases[1]["id"]]})
        assert response.status_code == 200, response.text
        assert (await client.post(url, json={})).status_code == 200
        with get_session_factory()() as db:
            events = list(db.scalars(select(WorkbenchContinuation).where(
                WorkbenchContinuation.run_id == run_id)))
            assert sorted(event.event_kind for event in events) == [
                "approval_completed", "approval_partial"]
            assert sum(event.status == "pending" for event in events) == 1
            assert db.get(WorkbenchRun, run_id).cursor == 0  # Executor, not approval, advances.


@pytest.mark.asyncio
async def test_approval_receipt_and_formal_writes_roll_back_together(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        (run_id, change_id, _), cases = await review_fixture(client)
        original = workbench_continuation.record_approval

        def fail_after_record(*args, **kwargs):
            original(*args, **kwargs)
            raise HTTPException(409, "synthetic_transaction_failure")

        monkeypatch.setattr(workbench_continuation, "record_approval", fail_after_record)
        response = await client.post(f"/api/v1/case-change-sets/{change_id}/apply", json={})
        assert response.status_code == 409
        with get_session_factory()() as db:
            assert db.get(CaseChangeSet, change_id).status == "ready"
            assert not list(db.scalars(select(WorkbenchContinuation).where(
                WorkbenchContinuation.run_id == run_id)))
            for case in cases:
                assert db.get(CaseRecord, UUID(case["id"])).current_revision_id == UUID(
                    case["current_revision_id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("via_operation", [False, True])
async def test_rejection_or_operation_cancel_stops_matching_run(via_operation):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        (run_id, change_id, operation_id), _ = await review_fixture(client)
        url = (f"/api/v1/conversation-operations/{operation_id}/cancel" if via_operation
               else f"/api/v1/case-change-sets/{change_id}/reject")
        response = await client.post(url, json={})
        assert response.status_code == 200, response.text
        with get_session_factory()() as db:
            run = db.get(WorkbenchRun, run_id)
            assert run.status == "cancelled" and run.epoch == 2
            assert not list(db.scalars(select(WorkbenchContinuation).where(
                WorkbenchContinuation.run_id == run_id,
                WorkbenchContinuation.status == "pending")))


@pytest.mark.asyncio
async def test_candidate_approval_waits_only_for_its_job_and_partial_does_not_advance():
    from casepilot_api.models import GenerationJob, WorkspaceCandidate

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        owner, collection, workspace = await setup(client)
        cid = UUID(workspace["id"])
        with get_session_factory()() as db:
            conversation = db.get(Conversation, cid)
            user = ConversationMessage(conversation_id=cid, role="user", content="生成后检查",
                                       status="completed", target_case_ids=[], citations=[],
                                       message_metadata={})
            db.add(user)
            db.flush()
            jobs = [GenerationJob(space_id=conversation.space_id,
                                  account_id=conversation.account_id,
                                  collection_id=UUID(collection["id"]), status="completed",
                                  operation="generate", input_payload={"conversation_id": str(cid)},
                                  output_payload={}) for _ in range(2)]
            db.add_all(jobs)
            db.flush()
            operation = ConversationOperation(conversation_id=cid, message_id=user.id, sequence=1,
                intent="CASE_GENERATE", status="awaiting_confirmation", target={}, payload={},
                result={}, related_job_id=jobs[0].id)
            db.add(operation)
            snapshot = {"title": "Generated", "module": "Module", "priority": "P1",
                        "case_type": "功能", "tags": [], "preconditions": [],
                        "steps": [{"action": "Submit", "expected": "Accepted"}]}
            candidates = [WorkspaceCandidate(conversation_id=cid, generation_job_id=job.id,
                ref=f"candidate-{uuid4()}", version=1, snapshot=snapshot, status="candidate",
                position=index, included=True)
                for index, job in enumerate([*([jobs[0]] * 3), jobs[1]])]
            db.add_all(candidates)
            db.flush()
            from casepilot_api.workbench_selection import (
                SelectionUpdate,
                stamp_operation_binding,
                update_selection,
            )
            update_selection(db, db.get(Account, UUID(owner["id"])), conversation,
                SelectionUpdate(base_version=0, sources=[
                    {"ref": f"candidate:{item.ref}", "version": str(item.version)}
                    for item in candidates[:3]], active_collection_id=UUID(collection["id"])))
            stamp_operation_binding(conversation, operation)
            run = create_run(db, db.get(Account, UUID(owner["id"])), conversation, user.id, uuid4())
            run.status = "waiting_approval"
            run.checkpoint = {"waiting_artifact_kind": "candidates",
                              "waiting_artifact_id": str(jobs[0].id),
                              "waiting_artifact_version": str(jobs[0].id),
                              "waiting_operation_id": str(operation.id)}
            run_id = run.id
            candidate_ids = [str(candidate.id) for candidate in candidates]
            db.commit()
        for index, candidate_id in enumerate(candidate_ids[:3]):
            response = await client.post(f"/api/v1/workspaces/{cid}/candidates/commit",
                                         json={"candidate_ids": [candidate_id]})
            assert response.status_code == 200, response.text
            with get_session_factory()() as db:
                run = db.get(WorkbenchRun, run_id)
                assert run.cursor == 0
                events = list(db.scalars(select(WorkbenchContinuation).where(
                    WorkbenchContinuation.run_id == run_id)))
                if index < 2:
                    assert [event.event_kind for event in events] == ["approval_partial"]
                    assert run.status == "waiting_approval"
                else:
                    assert sorted(event.event_kind for event in events) == [
                        "approval_completed", "approval_partial"]
                    assert sum(event.status == "pending" for event in events) == 1
                assert db.get(WorkspaceCandidate, UUID(candidate_ids[-1])).status == "candidate"


@pytest.mark.asyncio
async def test_old_brief_cannot_follow_changed_destination():
    from casepilot_api.models import GenerationJob, WorkspaceTestBrief

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        owner, collection, workspace = await setup(client)
        cid = workspace["id"]
        initial = await client.patch(f"/api/v1/workspaces/{cid}/selection", json={
            "base_version": 0, "action": "replace", "sources": [],
            "active_collection_id": collection["id"]})
        assert initial.status_code == 200, initial.text
        state = initial.json()["context"]["workbench_selection"]
        with get_session_factory()() as db:
            message = ConversationMessage(conversation_id=UUID(cid), role="user", content="生成",
                status="completed", target_case_ids=[], citations=[], message_metadata={})
            db.add(message)
            db.flush()
            operation = ConversationOperation(conversation_id=UUID(cid), message_id=message.id,
                sequence=1, intent="CASE_GENERATE", status="awaiting_confirmation", target={},
                payload={"selection_version": state["version"],
                         "destination_collection_id": collection["id"]}, result={})
            db.add(operation)
            db.flush()
            brief = WorkspaceTestBrief(conversation_id=UUID(cid), source_operation_id=operation.id,
                                       version=1, content={"test_object": "login"}, status="draft")
            db.add(brief)
            db.commit()
        other = (await client.post(f"/api/v1/spaces/{owner['spaces'][0]['id']}/collections",
                                   json={"name": "Other destination"})).json()
        changed = await client.patch(f"/api/v1/workspaces/{cid}/selection", json={
            "base_version": state["version"], "action": "replace", "sources": [],
            "active_collection_id": other["id"]})
        assert changed.status_code == 200, changed.text
        response = await client.post(f"/api/v1/workspaces/{cid}/test-briefs/confirm",
                                     json={"version": 1})
        assert response.status_code == 409, response.text
        with get_session_factory()() as db:
            assert not list(db.scalars(select(GenerationJob).where(
                GenerationJob.input_payload["conversation_id"].astext == cid)))
            assert db.scalar(select(WorkspaceTestBrief).where(
                WorkspaceTestBrief.conversation_id == UUID(cid))).status == "draft"


@pytest.mark.asyncio
async def test_paused_side_question_blocks_approval_and_rolls_back_formal_writes():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        (run_id, change_id, _), cases = await review_fixture(client)
        with get_session_factory()() as db:
            run = db.get(WorkbenchRun, run_id)
            run.status = "paused_question"
            db.commit()
        response = await client.post(f"/api/v1/case-change-sets/{change_id}/apply", json={})
        assert response.status_code == 409, response.text
        assert response.json()["detail"] == "workbench_run_paused"
        with get_session_factory()() as db:
            assert db.get(WorkbenchRun, run_id).status == "paused_question"
            assert db.get(CaseChangeSet, change_id).status == "ready"
            assert not list(db.scalars(select(WorkbenchContinuation).where(
                WorkbenchContinuation.run_id == run_id)))
            for case in cases:
                assert str(db.get(CaseRecord, UUID(case["id"])).current_revision_id) == case[
                    "current_revision_id"]


@pytest.mark.asyncio
async def test_repeated_clarification_cycles_emit_new_events_once(monkeypatch):
    import asyncio

    from casepilot_agent.workbench_events import emit_job_completion

    from casepilot_api import conversations
    from casepilot_api.models import GenerationJob
    from casepilot_api.workbench_run_executor import execute_workbench_continuation

    monkeypatch.setattr(conversations, "enqueue_task", lambda *a, **k: None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        owner, collection, workspace = await setup(client)
        cid = UUID(workspace["id"])
        with get_session_factory()() as db:
            conversation = db.get(Conversation, cid)
            user = ConversationMessage(conversation_id=cid, role="user", content="生成后检查",
                status="completed", target_case_ids=[], citations=[], message_metadata={})
            db.add(user)
            db.flush()
            run = create_run(db, db.get(Account, UUID(owner["id"])), conversation, user.id, uuid4())
            job = GenerationJob(space_id=conversation.space_id, account_id=conversation.account_id,
                collection_id=UUID(collection["id"]), status="awaiting_input", operation="generate",
                input_payload={"conversation_id": str(cid), "task_revision": 1,
                               "workbench_run_id": str(run.id), "workbench_epoch": run.epoch,
                               "workbench_cursor": run.cursor}, output_payload={})
            db.add(job)
            db.flush()
            run.status = "waiting_job"
            run.checkpoint = {"waiting_job_id": str(job.id)}
            job_id, run_id = job.id, run.id
            db.commit()
        for revision in (1, 2):
            with get_session_factory()() as db:
                job = db.get(GenerationJob, job_id)
                job.status = "awaiting_input"
                db.flush()
                snapshot = {"id": job.id, "status": job.status, "operation": job.operation,
                            "input_payload": dict(job.input_payload)}
                event = emit_job_completion(db.connection(), snapshot)
                assert event is not None
                assert emit_job_completion(db.connection(), snapshot) is None
                db.commit()
            await asyncio.to_thread(execute_workbench_continuation, event)
            response = await client.post(
                f"/api/v1/conversations/{cid}/generation-jobs/{job_id}/answers",
                json={"answers": [{"question_id": f"q{revision}", "answer": "明确要求"}]})
            assert response.status_code == 202, response.text
            with get_session_factory()() as db:
                job = db.get(GenerationJob, job_id)
                assert job.input_payload["task_revision"] == revision + 1
                assert db.get(WorkbenchRun, run_id).status == "waiting_job"
        with get_session_factory()() as db:
            versions = set(db.scalars(select(WorkbenchContinuation.source_version).where(
                WorkbenchContinuation.run_id == run_id,
                WorkbenchContinuation.event_kind == "job_completed")))
            assert versions == {"awaiting_input:1", "awaiting_input:2"}
