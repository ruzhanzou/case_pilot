from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from casepilot_api.agent_router import deterministic_plan
from casepilot_api.case_scope import requested_new_module
from casepilot_api.conversations import (
    _operation_runtime_status,
    _require_idle_conversation,
    classify_intent,
)
from casepilot_api.schemas import WorkspaceStateUpdate


@pytest.mark.parametrize(
    "text,module",
    [
        ("增加退款模块，覆盖申请、审核和到账", "退款"),
        ("新增一个订单/退款模块", "订单/退款"),
        ("改写退款模块用例", ""),
        ("create module Refund", "Refund"),
    ],
)
def test_explicit_new_module_path(text, module):
    assert requested_new_module(text) == module


def test_combined_coverage_and_duplicates_are_separate_tasks():
    plan = deterministic_plan(
        "检查登录模块遗漏和冗余；补充登录模块用例；改写登录模块用例",
        classify_intent,
        has_targets=False,
    )
    assert [item.intent for item in plan.operations] == [
        "COVERAGE_ANALYZE",
        "CASE_DEDUP",
        "CASE_GENERATE",
        "CASE_MODIFY",
    ]
    assert [item.depends_on for item in plan.operations] == [None, 0, 1, 2]


def test_server_rejects_another_message_while_a_job_is_active():
    db = Mock()
    db.scalar.return_value = uuid4()
    conversation = SimpleNamespace(id=uuid4())
    with pytest.raises(HTTPException) as error:
        _require_idle_conversation(db, conversation)
    assert error.value.status_code == 409
    assert error.value.detail == "conversation_task_running"
    db.refresh.assert_called_once_with(conversation, with_for_update=True)
    db.scalar.return_value = None
    _require_idle_conversation(db, conversation)


def test_instant_and_waiting_results_keep_the_same_task_identity():
    operation = SimpleNamespace(id=uuid4(), message_id=uuid4(), payload={}, status="running")
    message = SimpleNamespace(
        message_metadata={}, status="awaiting_confirmation", related_job_id=None
    )
    _operation_runtime_status(operation, message, {})
    assert operation.status == "awaiting_confirmation"
    assert message.message_metadata["operation_id"] == str(operation.id)
    message.status = "completed"
    _operation_runtime_status(operation, message, {})
    assert operation.status == "completed"
    assert operation.completed_at <= datetime.now(UTC)


def test_task_workspace_view_can_be_restored():
    assert WorkspaceStateUpdate(active_view="plan").active_view == "plan"


def test_user_examples_route_to_module_generation_and_complete_task_chain():
    assert classify_intent("增加退款模块")[0] == "CASE_GENERATE"
    plan = deterministic_plan(
        "检查登录模块遗漏和冗余，补上缺失场景，再优化用例表达",
        classify_intent,
        has_targets=False,
    )
    assert [item.intent for item in plan.operations] == [
        "COVERAGE_ANALYZE",
        "CASE_DEDUP",
        "CASE_GENERATE",
        "CASE_MODIFY",
    ]


def test_empty_module_creates_a_persisted_module_without_starting_generation(monkeypatch):
    from casepilot_api import conversations
    from casepilot_api.schemas import ConversationMessageCreate, MindMapNote

    conversation = SimpleNamespace(id=uuid4(), collection_id=uuid4())
    collection = SimpleNamespace(mind_map_notes=[])
    operation = SimpleNamespace(payload={}, result={})
    db = Mock()
    db.get.return_value = operation
    monkeypatch.setattr(conversations, "_collection_gate", lambda *args: None)
    monkeypatch.setattr(conversations, "ensure_collection", lambda *args: collection)
    message, action, job = conversations._start_action(
        db,
        SimpleNamespace(id=uuid4()),
        conversation,
        SimpleNamespace(),
        ConversationMessageCreate(content="只创建退款模块，不生成用例"),
        "CASE_GENERATE",
        1.0,
        uuid4(),
    )
    assert job is None
    assert action["type"] == "module_created"
    assert message.status == "completed"
    assert MindMapNote.model_validate(collection.mind_map_notes[0]).kind == "module"
    assert operation.result["module_path"] == "退款"


def test_module_name_is_test_object_instead_of_requested_case_count():
    from casepilot_api.conversations import _extract_explicit_test_object

    assert _extract_explicit_test_object("新增密码重置模块的2条用例") == "密码重置模块"
    assert _extract_explicit_test_object("生成2条用例") == ""
