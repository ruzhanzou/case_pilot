"""Server preparation survives resume without changing immutable user provenance."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest
from test_rewrite_dialogue import draft  # noqa: F401

from casepilot_api import conversations
from casepilot_api.database import get_session_factory
from casepilot_api.models import ConversationMessage, ConversationOperation


def test_prepared_request_is_authoritative_and_copied():
    original = {"content": "original", "generation_strategy": None, "targets": []}
    prepared = {"content": "prepared", "generation_strategy": "select_and_generate",
                "targets": [{"kind": "case", "case_ids": ["bound"]}]}
    operation = SimpleNamespace(payload={"prepared_request": deepcopy(prepared)})
    user = SimpleNamespace(message_metadata={"request": deepcopy(original)})
    restored = conversations._operation_prepared_request(operation, user)
    assert restored == prepared
    restored["targets"].clear()
    assert operation.payload["prepared_request"] == prepared
    assert user.message_metadata["request"] == original
    assert conversations._operation_prepared_request(None, user) == original
    assert conversations._operation_prepared_request(SimpleNamespace(payload={}), user) == original


@pytest.mark.asyncio
async def test_rewrite_resume_reads_prepared_snapshot_not_original(draft, monkeypatch):  # noqa: F811
    client, _, oid, _, _ = draft
    with get_session_factory()() as db:
        operation = db.get(ConversationOperation, UUID(oid))
        user = db.get(ConversationMessage, operation.message_id)
        original = deepcopy(user.message_metadata)
        request = {**original["request"], "generation_strategy": "select_and_generate"}
        operation.payload = {**operation.payload, "prepared_request": request}
        user_id = user.id
        db.commit()
    captured = []
    resolve = conversations._resolve_turn_attachments

    def inspect(db, conversation, payload, **kwargs):
        captured.append(payload.generation_strategy)
        return resolve(db, conversation, payload, **kwargs)

    monkeypatch.setattr(conversations, "_resolve_turn_attachments", inspect)
    response = await client.post(f"/api/v1/conversation-operations/{oid}/resume", json={})
    assert response.status_code == 202, response.text
    assert captured and set(captured) == {"select_and_generate"}
    with get_session_factory()() as db:
        assert db.get(ConversationMessage, user_id).message_metadata == original


@pytest.mark.asyncio
@pytest.mark.parametrize("stale", [False, True, "refine"])
async def test_legacy_scope_confirmation_binds_only_exact_durable_gate(draft, stale):  # noqa: F811
    from uuid import uuid4

    from sqlalchemy import select

    from casepilot_api.models import (
        Account,
        Conversation,
        GenerationJob,
        WorkbenchContinuation,
        WorkbenchRun,
    )
    from casepilot_api.workbench_artifact_version import operation_review_version
    from casepilot_api.workbench_continuation import create_run

    client, workspace, oid, _, _ = draft
    with get_session_factory()() as db:
        operation = db.get(ConversationOperation, UUID(oid))
        conversation = db.get(Conversation, UUID(workspace))
        account = db.get(Account, conversation.account_id)
        run = create_run(db, account, conversation, operation.message_id, uuid4())
        run.status = "waiting_approval"
        run.checkpoint = {"waiting_operation_id": oid,
                          "waiting_artifact_kind": "operation_confirmation",
                          "waiting_artifact_id": oid,
                          "waiting_artifact_version": ("stale" if stale is True
                                                       else operation_review_version(operation))}
        run_id = run.id
        db.commit()
    if stale == "refine":
        refinement = await client.post(f"/api/v1/conversation-operations/{oid}/resume",
                                       json={"content": "改为P2，步骤保持不变"})
        assert refinement.status_code == 202, refinement.text
        with get_session_factory()() as db:
            run = db.get(WorkbenchRun, run_id)
            assert run.status == "invalidated"
            assert run.checkpoint["invalidation_reason"] == "new_mutating_instruction"
    response = await client.post(f"/api/v1/conversation-operations/{oid}/resume",
                                 json={"confirm_modification": True})
    if stale is True:
        assert response.status_code == 409, response.text
        with get_session_factory()() as db:
            assert not list(db.scalars(select(WorkbenchContinuation).where(
                WorkbenchContinuation.run_id == run_id)))
            assert db.get(ConversationOperation, UUID(oid)).related_job_id is None
        return
    assert response.status_code == 202, response.text
    job_id = UUID(response.json()["action"]["job_id"])
    with get_session_factory()() as db:
        run = db.get(WorkbenchRun, run_id)
        job = db.get(GenerationJob, job_id)
        events = list(db.scalars(select(WorkbenchContinuation).where(
            WorkbenchContinuation.run_id == run_id)))
        if stale == "refine":
            assert run.status == "invalidated"
            assert not events
            assert "workbench_run_id" not in job.input_payload
            return
        assert run.status == "waiting_job"
        assert run.checkpoint["waiting_job_id"] == str(job_id)
        assert job.input_payload["workbench_run_id"] == str(run_id)
        assert len(events) == 1
