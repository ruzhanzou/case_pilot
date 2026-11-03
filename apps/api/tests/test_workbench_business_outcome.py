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
            assert turn["assistant_message"]["content"] == "已启动改写草稿计算"
            assert state["answer_sections"]["actions"] == []
            assert state["answer_sections"]["information_authority"] == "unverified_dialogue"
            assert state["final"]["message"] == turn["assistant_message"]["content"]
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


@pytest.mark.parametrize("recover", [False, True])
def test_rejected_inline_plan_gets_existing_correction_and_no_false_effect(recover):
    from casepilot_api.workbench_tools import DomainPrepareArguments

    malformed = call("prepare_rewrite", arguments=(
        '{"plan":{"steps":["rewrite", "show diff"],"plan_actions":["CASE_MODIFY"]}}'
    ))
    valid = call("prepare_rewrite", "corrected", arguments=(
        '{"plan":{"steps":["rewrite and show diff"],"plan_actions":["CASE_MODIFY"]}}'
    ))
    provider = Provider(malformed, answer("已准备启动改写"),
                        *([valid, action] if recover else [answer("已准备启动改写")]))
    writes = []
    result = WorkbenchAgent(provider, [ToolSpec(
        "prepare_rewrite", "Prepare a draft only", DomainPrepareArguments,
        lambda _: writes.append("draft") or {"status": "queued", "applied": False},
        "prepare", fulfilled_actions=("CASE_MODIFY",),
    )], max_turns=4).run([], "Scoped", verify_no_effect_answer=True,
                        completion_state=lambda: {})
    assert result.error_code is None
    assert writes == (["draft"] if recover else [])
    assert len(provider.requests) == (4 if recover else 3)
    assert len([e for e in result.events if e["type"] == "final_correction"]) == 1
    error = next(e for e in result.events if e["type"] == "tool_rejected")
    assert error["diagnostic"]["argument_errors"] == [{
        "type": "value_error", "loc": ["plan"], "code": "workbench_plan_step_count_mismatch",
    }]
    outcome = business_outcome("current", result.tool_results)
    assert outcome.activity == ("preparation_verified" if recover else "not_executed")
    if not recover:
        assert "未启动任务或生成差异" in unexecuted_answer_notice(result, outcome)


def test_rejected_call_at_turn_budget_still_shows_no_execution_notice():
    result = SimpleNamespace(status="completed", events=[{"type": "tool_rejected"}],
                             tool_results=[])
    outcome = business_outcome("current", [])
    assert "未启动任务或生成差异" in unexecuted_answer_notice(result, outcome)


@pytest.mark.asyncio
@pytest.mark.parametrize("recover", [False, True])
async def test_pg_rejected_plan_recovery_creates_only_a_reviewable_job(monkeypatch, recover):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, cases = await selected_pair(client)
        claim = FinalAnswer(kind="answer", message="已准备启动改写")
        steps = [
            ("prepare_rewrite", {"plan": {
                "steps": ["修改预期", "展示差异"], "plan_actions": ["CASE_MODIFY"],
            }}), claim,
        ]
        steps.extend([
            ("prepare_rewrite", {"plan": {
                "steps": ["修改预期并展示差异"], "plan_actions": ["CASE_MODIFY"],
            }}), "prepare",
        ] if recover else [claim])
        provider = activate(monkeypatch, steps)
        turn = await send(client, cid, "只改当前选中用例的预期，先给我看差异，不应用")
        agent = turn["assistant_message"]["metadata"]["workbench_agent"]
        assert agent["business_outcome"]["activity"] == (
            "preparation_verified" if recover else "not_executed")
        assert len(provider.observations) == (4 if recover else 3)
        if not recover:
            assert not turn.get("operation_plan")
            assert agent["answer_sections"]["actions"] == []
        else:
            assert turn["operation_plan"] is not None
        for case in cases:
            actual = (await client.get(f"/api/v1/test-cases/{case['id']}")).json()
            assert actual["current_revision_id"] == case["current_revision_id"]


@pytest.mark.asyncio
async def test_rejected_new_preparation_clarification_is_not_a_completed_side_question(monkeypatch):
    from test_workbench_goal_completion import latest
    from test_workbench_side_questions import snapshot, waiting_review

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, prior_id, _, _ = await waiting_review(client, monkeypatch)
        before = snapshot(prior_id)
        activate(monkeypatch, [
            ("prepare_rewrite", {"plan": {
                "steps": ["修改预期", "展示差异"], "plan_actions": ["CASE_MODIFY"],
            }}), FinalAnswer(kind="clarify", message="请确认本次目标范围"),
        ])
        turn = await send(client, cid, "改写当前选中内容，先展示差异")
        state = turn["assistant_message"]["metadata"]["workbench_agent"]
        assert state["status"] == "awaiting_input"
        assert latest(cid)["status"] == "waiting_approval"
        assert not latest(cid)["plan"].get("steps")
        assert snapshot(prior_id) == before  # Invalid arguments do not revoke earlier authority.
        assert not turn.get("operation_plan")


@pytest.mark.parametrize("activity,coverage,guarded,kind,retain", [
    ("not_executed", "not_planned", True, "answer", False),
    ("context_observed", "not_planned", True, "answer", False),
    ("planned", "pending_steps", True, "answer", False),
    ("read_completed", "pending_steps", False, "answer", False),
    ("workspace_updated", "pending_steps", False, "answer", False),
    ("not_executed", "not_planned", False, "answer", True),
    ("not_executed", "not_planned", False, "clarify", True),
    ("read_completed", "not_planned", False, "answer", True),
    ("read_completed", "steps_verified", False, "answer", True),
    ("preparation_verified", "pending_steps", False, "action", True),
])
def test_display_projection_never_appends_unverified_claims(
    activity, coverage, guarded, kind, retain,
):
    from casepilot_api.workbench_business_outcome import BusinessOutcome, present_final

    original = FinalAnswer(kind=kind, message="synthetic original assertion")
    result = SimpleNamespace(
        final=original, status="completed" if kind != "clarify" else "awaiting_input",
        events=[{"error_code": "agent_execution_unverified"}] if guarded else [],
    )
    outcome = BusinessOutcome(activity=activity, plan_coverage=coverage,
                              run_id="current", receipt_ids=[])
    displayed = present_final(result, outcome)
    assert original.message == displayed["message"]  # Information is not execution evidence.
    assert result.final is original and original.message == "synthetic original assertion"
    assert set(displayed) == set(original.model_dump())
    assert "synthetic original assertion" not in str(outcome.model_dump())


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_failed_or_cancelled_final_does_not_expose_model_prose(status):
    from casepilot_api.workbench_business_outcome import present_final

    result = SimpleNamespace(final=None, status=status, events=[])
    assert present_final(result, business_outcome("current", [])) is None


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_sections_preserve_read_data_with_receipt_and_never_approve(status):
    from casepilot_api.workbench_business_outcome import answer_sections

    rows = [{"ref": "synthetic", "snapshot": {"title": "Valid observed result"}}]
    records = [
        {"tool": "query_assets",
         "receipt": {"id": "run:1", "tool": "query_assets", "effect": "read"},
         "result": {"cases": rows}},
        {"tool": "prepare_rewrite",
         "receipt": {"id": "run:2", "tool": "prepare_rewrite", "effect": "prepare"},
         "result": {"status": "queued", "requires_human_review": False}},
        {"tool": "query_assets",
         "receipt": {"id": "old:1", "tool": "query_assets", "effect": "read"},
         "result": {"cases": [{"private": "must not leak"}]}},
        {"tool": "prepare_rewrite", "receipt": None, "result": {"status": "rejected"}},
    ]
    section = answer_sections("run", records, status)
    assert len(section["actions"]) == 2
    assert section["actions"][0]["state"] == "read_completed"
    assert section["actions"][1]["state"] == "queued"
    assert section["read_results"][0]["rows"] == rows
    assert section["read_results"][0]["receipt_id"] == "run:1"
    assert "must not leak" not in str(section)
    assert "applied" not in str(section)


@pytest.mark.parametrize("state,review,expected", [
    ("queued", False, "queued"), ("running", False, "queued"),
    ("awaiting_input", True, "awaiting_review"),
    ("completed", False, "preparation_recorded"), ("failed", False, "failed"),
])
def test_preparation_section_is_not_formal_application(state, review, expected):
    from casepilot_api.workbench_business_outcome import answer_sections

    sections = answer_sections("run", [{"tool": "prepare_rewrite",
         "receipt": {
        "id": "run:1", "tool": "prepare_rewrite", "effect": "prepare"},
        "result": {"status": state, "requires_human_review": review}}], "completed")
    assert sections["actions"][0]["state"] == expected

@pytest.mark.parametrize("tool,expected", [
    ("select_assets", "workspace_updated"),
    ("select_collection", "workspace_updated"),
    ("preview_uploaded_cases", "preparation_recorded"),
])
def test_turn_cancel_does_not_relabel_completed_workspace_effect(tool, expected):
    from casepilot_api.workbench_business_outcome import answer_sections

    result = answer_sections("run", [{"tool": tool, "receipt": {
        "id": "run:1", "tool": tool, "effect": "prepare"},
        "result": {"status": "completed"}}], "cancelled")
    assert result["actions"][0]["state"] == expected


def test_actual_agent_segment_receipt_survives_durable_run_projection():
    from casepilot_api.workbench_business_outcome import answer_sections

    result = WorkbenchAgent(Provider(call("query_assets"), action), [ToolSpec(
        "query_assets", "Read", Args, lambda _: {"cases": [{"snapshot": {"title": "Read"}}]},
        "read",
    )]).run([], "Scoped")
    assert result.receipt_namespace and result.receipt_namespace != "durable-run"
    section = answer_sections("durable-run", result.tool_results, result.status,
                              receipt_namespace=result.receipt_namespace)
    assert section["run_id"] == "durable-run"
    assert len(section["actions"]) == len(result.tool_results) == 1
    assert section["read_results"][0]["rows"][0]["snapshot"]["title"] == "Read"
    assert answer_sections("durable-run", result.tool_results, result.status,
                           receipt_namespace="foreign")["actions"] == []
