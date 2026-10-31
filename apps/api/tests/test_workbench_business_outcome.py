"""Execution evidence is not inferred from model prose or turn completion."""
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from test_workbench_agent import Args, Provider, action, answer, call
from test_workbench_continuation_scope import selected_pair
from test_workbench_goal_completion import activate, send

from casepilot_api.main import app
from casepilot_api.workbench_agent import FinalAnswer, ModelTurn, ToolSpec, WorkbenchAgent
from casepilot_api.workbench_business_outcome import business_outcome, unexecuted_answer_notice


@pytest.mark.parametrize("message", ["已启动改写草稿计算", "预期结果描述应观察到的行为"])
def test_repeated_no_tool_answer_is_a_valid_turn_not_business_execution(message):
    provider = Provider(answer(message), answer(message))
    result = WorkbenchAgent(provider, [], max_turns=2).run(
        [{"role": "user", "content": "Synthetic selected workspace request"}], "Scoped",
        verify_no_effect_answer=True, completion_state=lambda: {},
    )
    outcome = business_outcome("run", result.tool_results)
    assert result.status == "completed" and result.error_code is None
    assert outcome.activity == "not_executed" and outcome.receipt_ids == []
    assert len(provider.requests) == 2
    assert "未启动任务或生成差异" in unexecuted_answer_notice(result, outcome)
    assert result.final.message == message  # Preserve dialogue; never classify its language.


@pytest.mark.parametrize("tool,effect,activity", [
    ("read_attachment_evidence", "read", "context_observed"),
    ("query_assets", "read", "read_completed"),
    ("select_assets", "read", "workspace_updated"),
    ("plan_work", "plan", "planned"),
    ("prepare_rewrite", "prepare", "preparation_verified"),
])
def test_outcome_comes_from_actual_tool_execution(tool, effect, activity):
    provider = Provider(call(tool), answer("Plan recorded") if effect == "plan" else action)
    result = WorkbenchAgent(provider, [ToolSpec(
        tool, "Synthetic tool", Args, lambda _: {"status": "queued", "applied": False}, effect,
    )]).run([], "Scoped", allow_plan_only=True)
    outcome = business_outcome("current", result.tool_results)
    assert outcome.activity == activity
    assert outcome.receipt_ids == [result.tool_results[0]["receipt"]["id"]]
    assert outcome.authority == "server_tool_records"
    assert "completed" not in outcome.model_dump().values()


def test_clarification_and_plain_chat_are_not_failures_or_write_requests():
    for kind in ("answer", "clarify"):
        result = SimpleNamespace(status="completed" if kind == "answer" else "awaiting_input",
                                 events=[], tool_results=[])
        outcome = business_outcome("current", result.tool_results)
        assert outcome.activity == "not_executed"
        assert unexecuted_answer_notice(result, outcome) == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("clarify", [False, True])
async def test_real_pg_no_execution_does_not_create_job_diff_or_change_cases(monkeypatch, clarify):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, cases = await selected_pair(client)
        final = FinalAnswer(kind="clarify" if clarify else "answer",
                            message="请明确来源" if clarify else "已启动改写草稿计算")
        provider = activate(monkeypatch, [final, final])
        turn = await send(client, cid, "只改当前选中用例的预期并等我确认")
        state = turn["assistant_message"]["metadata"]["workbench_agent"]
        assert state["business_outcome"]["activity"] == "not_executed"
        assert state["business_outcome"]["receipt_ids"] == []
        assert state["business_outcome"]["run_id"] == state["run_id"]
        assert state["status"] == ("awaiting_input" if clarify else "completed")
        assert len(provider.observations) == (1 if clarify else 2)
        if not clarify:
            assert turn["assistant_message"]["content"].startswith("执行记录：本轮未启动任务")
        assert not turn.get("operation_plan")
        for case in cases:
            row = (await client.get(f"/api/v1/test-cases/{case['id']}")).json()
            assert row["current_revision_id"] == case["current_revision_id"]


@pytest.mark.parametrize("ref", ["previous-run:1", "foreign-run:2"])
def test_model_supplied_receipt_never_becomes_business_evidence(ref):
    invalid = ModelTurn(final=FinalAnswer(kind="action", message="Already changed",
                                        effect="prepare", receipt_ids=[ref]))
    provider = Provider(invalid, invalid)
    result = WorkbenchAgent(provider, []).run([], "Scoped")
    assert result.status == "failed"
    assert business_outcome("current", result.tool_results).activity == "not_executed"


def test_registered_skills_and_primitives_are_visible_to_actual_sdk_runner():
    from casepilot_api.workbench_tools import INSTRUCTIONS, WorkbenchTools

    class ObservedProvider(Provider):
        def complete(self, messages, tools, instructions):
            self.names = {tool["name"] for tool in tools}
            self.instructions = instructions
            return super().complete(messages, tools, instructions)

    provider = ObservedProvider(answer("Informational explanation"))
    specs = WorkbenchTools.__new__(WorkbenchTools).specs()
    result = WorkbenchAgent(provider, specs).run([], INSTRUCTIONS)
    assert result.status == "completed"
    assert {"load_workbench_skill", "query_assets", "prepare_rewrite",
            "prepare_generation", "prepare_reuse"} <= provider.names
    assert "every domain tool remains directly available" in provider.instructions
    assert "requires neither skill loading" in provider.instructions
