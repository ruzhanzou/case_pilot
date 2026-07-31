import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from casepilot_api.case_management import validate_execution_record_update
from casepilot_api.schemas import (
    CandidateCreate,
    ExecutionRecordUpdate,
    ExecutionRunCreate,
    ExecutionRunUpdate,
    ExecutionStatus,
    GenerationStartRequest,
    WorkspaceStateUpdate,
)
from casepilot_api.schemas import (
    TestCaseBatchCreate as BatchCreateSchema,
)
from casepilot_api.schemas import (
    TestCaseCreate as CaseCreateSchema,
)


def valid_case_payload() -> dict:
    return {
        "case_key": "AUTH-001",
        "title": "使用正确邮箱与密码登录成功",
        "module": "账号与认证",
        "priority": "P0",
        "case_type": "功能",
        "tags": ["登录", "账号"],
        "preconditions": ["账号已注册"],
        "steps": [
            {
                "id": "submit-login",
                "action": "提交正确账号与密码",
                "expected": "登录成功并进入工作台",
            }
        ],
        "source": "验收基线",
    }


def test_structured_case_requires_at_least_one_complete_step() -> None:
    payload = valid_case_payload()
    payload["steps"] = []

    with pytest.raises(ValidationError):
        CaseCreateSchema.model_validate(payload)


def test_execution_status_is_scoped_to_execution_records() -> None:
    assert {item.value for item in ExecutionStatus} == {
        "not_run",
        "passed",
        "failed",
        "skipped",
        "blocked",
    }


def test_execution_record_accepts_step_completion_and_actual_result() -> None:
    record = ExecutionRecordUpdate.model_validate(
        {
            "status": "passed",
            "completed_step_ids": ["submit-login"],
            "actual_result": "登录成功",
            "defect_ref": "",
            "base_updated_at": "2026-07-27T10:00:00+08:00",
        }
    )

    assert record.status is ExecutionStatus.PASSED
    assert record.completed_step_ids == ["submit-login"]
    assert record.base_updated_at is not None


def test_execution_run_requires_task_description() -> None:
    with pytest.raises(ValidationError):
        ExecutionRunCreate.model_validate({"description": "", "assignee_ids": []})
    assignee_id = "00000000-0000-0000-0000-000000000002"
    assert (
        ExecutionRunCreate.model_validate(
            {
                "description": "Audio 回归测试",
                "assignee_ids": [assignee_id],
            }
        ).description
        == "Audio 回归测试"
    )


def test_execution_run_can_only_close_as_completed_or_aborted() -> None:
    update = ExecutionRunUpdate.model_validate({"status": "completed"})
    assert update.status == "completed"
    assert update.allow_incomplete is False
    assert (
        ExecutionRunUpdate.model_validate(
            {"status": "completed", "allow_incomplete": True}
        ).allow_incomplete
        is True
    )
    with pytest.raises(ValidationError):
        ExecutionRunUpdate.model_validate({"status": "active"})


def test_batch_case_create_requires_at_least_one_case() -> None:
    with pytest.raises(ValidationError):
        BatchCreateSchema.model_validate({"cases": []})
    assert len(
        BatchCreateSchema.model_validate({"cases": [valid_case_payload()]}).cases
    ) == 1


def test_generation_requests_accept_configured_model_names() -> None:
    collection_id = "00000000-0000-0000-0000-000000000001"
    request = GenerationStartRequest.model_validate(
        {
            "prompt": "生成支付测试用例",
            "collection_id": collection_id,
            "model_id": "deepseek-v4-pro",
        }
    )
    candidate = CandidateCreate.model_validate(
        {
            "base_revision_id": collection_id,
            "instruction": "补充边界场景",
            "model_id": "glm-5.2",
        }
    )

    assert request.model_id == "deepseek-v4-pro"
    assert candidate.model_id == "glm-5.2"


def test_generation_requests_reject_unsafe_model_names() -> None:
    with pytest.raises(ValidationError):
        GenerationStartRequest.model_validate(
            {
                "prompt": "生成支付测试用例",
                "collection_id": "00000000-0000-0000-0000-000000000001",
                "model_id": "../unexpected-model",
            }
        )


def test_workspace_state_accepts_safe_model_names() -> None:
    state = WorkspaceStateUpdate.model_validate(
        {"model_id": "doubao-seed-2.0-lite"}
    )

    assert state.model_id == "doubao-seed-2.0-lite"
    with pytest.raises(ValidationError):
        WorkspaceStateUpdate.model_validate({"model_id": "../unexpected-model"})


@pytest.mark.parametrize("status", ["failed", "skipped", "blocked"])
def test_execution_result_reason_is_required(status: str) -> None:
    payload = ExecutionRecordUpdate.model_validate(
        {
            "status": status,
            "completed_step_ids": [],
            "actual_result": "",
            "defect_ref": "",
        }
    )
    with pytest.raises(HTTPException) as caught:
        validate_execution_record_update(payload, {"submit-login"})
    assert caught.value.detail == "execution_result_reason_required"


def test_passed_execution_allows_optional_step_tracking() -> None:
    payload = ExecutionRecordUpdate.model_validate(
        {
            "status": "passed",
            "completed_step_ids": ["first"],
            "actual_result": "",
            "defect_ref": "",
        }
    )
    validate_execution_record_update(payload, {"first", "second"})
