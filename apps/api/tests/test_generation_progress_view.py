from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from casepilot_api.generation import job_view


def test_compact_progress_uses_verified_cases_and_survives_polling():
    db = MagicMock()
    db.scalars.return_value.all.return_value = []
    job = SimpleNamespace(
        id=uuid4(),
        space_id=uuid4(),
        status="running",
        stage="test_case.grounded",
        error_code=None,
        input_payload={"output_contract": "case_batch_v2"},
        output_payload={
            "generated_count": 0,
            "total_count": 50,
            "batch_start_index": 1,
            "batch_count": 5,
            "started_at": "2026-10-10T01:00:00+08:00",
            "retry_attempt": 0,
        },
    )
    job.output_payload["active_batches"] = [
        {"start": 1, "count": 5, "stage": "test_case.generated", "retry_attempt": 0},
        {"start": 6, "count": 5, "stage": "test_case.grounded", "retry_attempt": 0},
    ]
    view = job_view(db, job)
    assert view.active_batches == job.output_payload["active_batches"]
    assert view.progress == 0  # Auditing the first batch is not 76% complete.
    assert view.batch_start_index == 1 and view.batch_count == 5
    assert view.started_at == job.output_payload["started_at"]
    job.output_payload.update(
        generated_count=10, batch_start_index=11, batch_count=2, retry_attempt=1
    )
    view = job_view(db, job)
    assert view.progress == 19 and view.generated_count == 10
    assert view.retry_attempt == 1
    job.status = job.stage = "failed"
    assert job_view(db, job).progress == 19
    job.status = job.stage = "cancelled"
    assert job_view(db, job).progress == 19
    job.status = job.stage = "completed"
    job.output_payload.update(generated_count=50)
    assert job_view(db, job).progress == 100


def test_planning_snapshot_and_progress_survive_polling_and_failure():
    db = MagicMock()
    db.scalars.return_value.all.return_value = []
    preview = {
        "test_object": "登录",
        "planning": {"feature_points": [{"id": "F1"}], "test_points": [{"id": "P1"}]},
    }
    metadata = {"progress": 55, "completed_batches": 1, "total_batches": 3, "test_point_count": 1}
    job = SimpleNamespace(
        id=uuid4(),
        space_id=uuid4(),
        status="running",
        stage="test_point.generated",
        error_code=None,
        input_payload={},
        output_payload={"planning_preview": preview, "planning_progress": metadata},
    )
    for status in ("running", "failed", "cancelled"):
        job.status = status
        view = job_view(db, job)
        assert view.planning_preview == preview
        assert view.planning_progress == metadata
        assert view.progress == 55
        assert not view.test_cases
    job.status = job.stage = "completed"
    assert job_view(db, job).progress == 100


def test_reuse_confirmation_rejects_changed_rules_features_and_points():
    from copy import deepcopy

    import pytest
    from fastapi import HTTPException

    from casepilot_api.conversations import validate_reuse_confirmation

    feature = {"id": "F1", "description": "验证码2分钟过期"}
    point = {"id": "P1", "title": "验证码过期"}
    content = {"business_rules": ["有效期2分钟"]}
    planning = {"feature_points": [feature], "test_points": [point], "reuse": {
        "strategy": "change", "brief_snapshot": deepcopy(content),
        "feature_snapshots": [deepcopy(feature)],
        "decisions": [{"point_id": "P1", "point_snapshot": deepcopy(point)}],
    }}
    validate_reuse_confirmation(content, planning)
    for changed_content, changed_plan in [
        ({"business_rules": ["有效期5分钟"]}, planning),
        (content, {**planning, "feature_points": [{"id": "F1", "description": "验证码5分钟过期"}]}),
        (content, {**planning, "test_points": [{"id": "P1", "title": "验证码重发"}]}),
    ]:
        with pytest.raises(HTTPException) as error:
            validate_reuse_confirmation(changed_content, changed_plan)
        assert error.value.status_code == 409
        assert error.value.detail == "reuse_plan_changed_reanalyze_required"
