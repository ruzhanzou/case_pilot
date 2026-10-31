"""Compute progress is authoritative job/diff state, not agent-loop completion."""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from casepilot_api.models import CaseChangeSet, GenerationJob
from casepilot_api.workbench_tools import WorkbenchTools, refresh_agent_domain_state


def fixture(job_status="queued", diff_status="generating", intent="CASE_MODIFY"):
    conversation = SimpleNamespace(id=uuid4())
    job_id, diff_id = uuid4(), uuid4()
    job = SimpleNamespace(
        status=job_status, input_payload={"conversation_id": str(conversation.id)},
    )
    diff = SimpleNamespace(status=diff_status, conversation_id=conversation.id,
                           generation_job_id=job_id)
    rows = {(GenerationJob, job_id): job, (CaseChangeSet, diff_id): diff}
    db = SimpleNamespace(get=lambda model, identifier: rows.get((model, identifier)))
    action = {"type": "change_set", "job_id": str(job_id), "change_set_id": str(diff_id)}
    bridge = WorkbenchTools(db, None, conversation, None)
    bridge.prepared_turn = SimpleNamespace(action=action, intent=intent, operation_plan=None,
                                           assistant_message=SimpleNamespace(
                                               content="Draft is computing", metadata={}))
    return bridge, job, diff


@pytest.mark.parametrize("job_status", ["queued", "running"])
def test_prepared_job_is_computing_not_waiting_for_scope_approval(job_status):
    bridge, _, _ = fixture(job_status)
    result = bridge.prepared_result()
    assert result["status"] == job_status
    assert result["domain_status"] == job_status
    assert result["requires_human_review"] is False
    assert result["applied"] is False
    assert result["job_id"] == bridge.prepared_turn.action["job_id"]


def test_completed_agent_turn_refreshes_actual_worker_and_diff_states():
    bridge, job, diff = fixture()
    state = {"status": "queued", "agent_turn_status": "completed",
             "domain_action": bridge.prepared_turn.action, "domain_intent": "CASE_MODIFY"}
    for job_status, diff_status, expected, needs_review in [
        ("running", "generating", "running", False),
        ("completed", "ready", "awaiting_input", True),
        ("completed", "no_changes", "completed", False),
        ("completed", "applied", "completed", False),
        ("failed", "generating", "failed", False),
        ("cancelled", "generating", "cancelled", False),
    ]:
        job.status, diff.status = job_status, diff_status
        updated = refresh_agent_domain_state(bridge.db, bridge.conversation, state)
        assert updated["status"] == updated["domain_status"] == expected
        assert updated["requires_human_review"] is needs_review
        assert updated["agent_turn_status"] == "completed"
    assert state["status"] == "queued"  # Projection does not mutate source or jobs.


def test_legitimate_clarification_and_legacy_scope_confirmation_stay_distinct():
    bridge, _, _ = fixture()
    bridge.prepared_turn.action = {"type": "clarification"}
    result = bridge.prepared_result()
    assert result["status"] == "clarification"
    assert not result["requires_human_review"]
    bridge.prepared_turn.assistant_message.metadata = {"modification_confirmation": True}
    result = bridge.prepared_result()
    assert result["status"] == "awaiting_input"
    assert result["requires_human_review"]


def test_collection_pending_projection_is_not_changed_by_job_refresh():
    bridge, _, _ = fixture()
    state = {"status": "awaiting_input", "agent_turn_status": "awaiting_input"}
    assert refresh_agent_domain_state(bridge.db, bridge.conversation, state) == state


def test_projection_rechecks_job_and_diff_binding():
    from fastapi import HTTPException

    bridge, job, diff = fixture()
    job.input_payload["conversation_id"] = str(uuid4())
    with pytest.raises(HTTPException) as error:
        bridge.prepared_result()
    assert error.value.detail == "job_conversation_mismatch"
    job.input_payload["conversation_id"] = str(bridge.conversation.id)
    diff.generation_job_id = uuid4()
    with pytest.raises(HTTPException) as error:
        bridge.prepared_result()
    assert error.value.detail == "change_set_job_mismatch"
