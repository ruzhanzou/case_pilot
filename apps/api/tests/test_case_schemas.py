import pytest
from pydantic import ValidationError

from casepilot_api.schemas import (
    ExecutionRecordUpdate,
    ExecutionRunCreate,
    ExecutionRunUpdate,
    ExecutionStatus,
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
        ExecutionRunCreate.model_validate({"description": ""})
    assert (
        ExecutionRunCreate.model_validate({"description": "Audio 回归测试"}).description
        == "Audio 回归测试"
    )


def test_execution_run_can_only_close_as_completed_or_aborted() -> None:
    assert ExecutionRunUpdate.model_validate({"status": "completed"}).status == "completed"
    with pytest.raises(ValidationError):
        ExecutionRunUpdate.model_validate({"status": "active"})
