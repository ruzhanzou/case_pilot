from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from casepilot_agent.case_analysis import CaseFinding
from casepilot_agent.store import JobStore


@pytest.mark.parametrize(
    "operation,output,status",
    [
        ("generate", {"workspace_candidate_ids": ["candidate"]}, "awaiting_confirmation"),
        ("knowledge_qa", {"answer": "Done"}, "completed"),
        ("conversation_modify", {}, "awaiting_confirmation"),
        ("conversation_modify", {"no_changes": True}, "completed"),
    ],
)
def test_completed_job_waits_for_asset_confirmation(operation, output, status):
    store = JobStore.__new__(JobStore)
    store.get_job = Mock(
        return_value={
            "operation": operation,
            "input_payload": {"conversation_operation_id": str(uuid4())},
        }
    )
    connection = Mock()
    store.update_job(connection, uuid4(), status="completed", output_payload=output)
    update = connection.execute.call_args.args[0]
    params = update.compile(dialect=postgresql.dialect()).params
    assert params["status"] == status
    assert "||" in str(update.compile(dialect=postgresql.dialect()))
    assert (params["completed_at"] is not None) == (status == "completed")


def test_coverage_without_requirement_reference_remains_potential():
    finding = CaseFinding(
        title="Missing lockout",
        severity="medium",
        case_refs=["case"],
        evidence="Common practice",
        recommendation="Verify account policy",
        basis="requirement",
    )
    assert finding.basis == "potential"


def test_cancelled_job_cannot_be_resurrected_by_a_late_result():
    store = JobStore.__new__(JobStore)
    store.get_job = Mock()
    connection = Mock()
    connection.execute.return_value.rowcount = 0
    store.update_job(connection, uuid4(), status="completed")
    store.get_job.assert_not_called()
    statement = str(connection.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "generation_jobs.status !=" in statement


def test_late_model_response_cannot_commit_after_cancellation():
    from casepilot_agent.tasks import GenerationCancelled, lock_active_job

    store = Mock()
    store.get_job_for_update.return_value = {"status": "cancelled"}
    with pytest.raises(GenerationCancelled):
        lock_active_job(store, Mock(), uuid4())
