"""Current schema choices help models; runtime authority never depends on obedience."""

import json

import pytest
from test_workbench_agent import Args, Provider, action, call

from casepilot_api.workbench_agent import (
    FinalAnswer,
    InjectedModel,
    ModelTurn,
    ToolSpec,
    WorkbenchAgent,
)
from casepilot_api.workbench_events import safe_event
from casepilot_api.workbench_receipts import CurrentReceiptSchema, safe_receipt_diagnostic


class ObservedModel(InjectedModel):
    def __init__(self, provider):
        super().__init__(provider)
        self.schemas = []

    async def get_response(self, *args, **kwargs):
        self.schemas.append(kwargs["output_schema"].json_schema())
        return await super().get_response(*args, **kwargs)


def test_each_sdk_request_receives_current_choices_without_an_extra_model_turn():
    model = ObservedModel(Provider(call(), action))
    result = WorkbenchAgent(model, [ToolSpec("query", "Read", Args, lambda _: {})]).run(
        [{"role": "user", "content": "Read synthetic cases"}], "Synthetic scope",
    )
    assert result.status == "completed"
    first, second = [s["properties"]["receipt_ids"] for s in model.schemas]
    assert first["maxItems"] == 0
    assert second["items"]["enum"] == result.final.receipt_ids
    assert "enum" not in first["items"]  # The previous request's schema was not mutated.


@pytest.mark.parametrize("correct", [False, True])
def test_applied_then_pending_then_replacement_cannot_reuse_earlier_receipt(correct):
    # Agent contract fixture only: DB/apply lifecycle is independently exercised
    # by the real HTTP/broker journey. No model can create an applied receipt here.
    tools = [ToolSpec("prepare", "Prepare only", Args,
                      lambda _: {"status": "queued", "applied": False}, "prepare")]
    prior = []
    for request in ("First revision", "Supplement after application"):
        provider = Provider(call("prepare"), action)
        result = WorkbenchAgent(provider, tools).run(
            [{"role": "user", "content": request}], "Synthetic scope",
        )
        prior.append(result.final.receipt_ids[0])
    invalid = ModelTurn(final=FinalAnswer(
        kind="action", effect="prepare", message="Review replacement",
        receipt_ids=[prior[-1]],
    ))
    provider = Provider(call("prepare"), invalid, action if correct else invalid)
    result = WorkbenchAgent(provider, tools).run([
        {"role": "assistant", "content": json.dumps({"receipt_ids": prior})},
        {"role": "user", "content": "Do not apply pending supplement; replace it"},
    ], "Synthetic scope")
    assert len(provider.requests) == 3
    assert len(result.tool_results) == 1  # Correction never repeats successful preparation.
    assert result.error_code == (None if correct else "agent_final_receipt_invalid")
    correction = next(e for e in result.events if e["type"] == "final_correction")
    assert correction["receipt_validation"] == {
        "kind": "action", "effect": "prepare",
        "available": [{"slot": 1, "effect": "prepare"}],
        "submitted": [{"relation": "not_current"}],
    }
    assert not any(ref in json.dumps(result.events) for ref in prior)
    if correct:
        assert result.final.receipt_ids[0] not in prior


def test_schema_does_not_repair_or_accept_a_foreign_reference():
    schema = CurrentReceiptSchema(FinalAnswer, {"current:1": {"effect": "read"}})
    final = schema.validate_json(json.dumps({
        "kind": "action", "message": "Read", "effect": "read", "receipt_ids": ["old:1"],
    }))
    assert final.receipt_ids == ["old:1"]  # Existing runtime guard receives the violation.
    assert schema.json_schema()["properties"]["receipt_ids"]["items"]["enum"] == ["current:1"]


def test_receipt_diagnostics_drop_unknown_values_at_storage_boundary():
    value = {
        "raw": "private text",
        "available": [{"slot": 1, "effect": "read", "id": "secret"},
                      {"slot": True, "effect": "read"}, {"slot": 2, "effect": ["read"]}],
        "submitted": [{"relation": "not_current", "id": "private text"},
                      {"relation": "current", "slot": 1, "raw": "secret"}],
    }
    expected = {"available": [{"slot": 1, "effect": "read"}], "submitted": [
        {"relation": "not_current"}, {"relation": "current", "slot": 1},
    ]}
    assert safe_receipt_diagnostic(value) == expected
    event = safe_event({"type": "run_failed", "sequence": 1, "receipt_validation": value})
    assert event["receipt_validation"] == expected
    assert "private" not in json.dumps(event) and "secret" not in json.dumps(event)
    assert safe_receipt_diagnostic({"submitted": [{}] * 65}) == {}


@pytest.mark.parametrize("effects,expected", [
    ([], ["none"]), (["plan"], ["none"]),
    (["read"], ["none", "read"]), (["prepare"], ["none", "prepare"]),
])
def test_final_effect_choices_require_real_current_receipts(effects, expected):
    receipts = {str(i): {"effect": effect} for i, effect in enumerate(effects)}
    schema = CurrentReceiptSchema(FinalAnswer, receipts).json_schema()
    assert schema["properties"]["effect"]["enum"] == expected
    if expected == ["none"]:
        assert schema["properties"]["kind"]["enum"] == ["answer", "clarify"]


def test_no_tool_replacement_failure_remains_failed_without_fabricating_receipts():
    invalid = ModelTurn(final=FinalAnswer(
        kind="action", effect="prepare", message="Replacement ready", receipt_ids=[],
    ))
    provider = Provider(invalid, invalid)
    result = WorkbenchAgent(provider, []).run([
        {"role": "assistant", "content": "Earlier proposal is awaiting review"},
        {"role": "user", "content": "Replace the pending suggestion, do not apply"},
    ], "Synthetic fixture; no previous receipt authorizes this turn")
    assert result.error_code == "agent_final_receipt_required"
    assert len(provider.requests) == 2
    assert result.tool_results == []
    correction = next(e for e in result.events if e["type"] == "final_correction")
    assert correction["receipt_validation"] == {
        "available": [], "submitted": [], "kind": "action", "effect": "prepare",
    }
    assert "No successful tool ran" in provider.requests[1][-1]["content"]
    assert "do NOT ask permission to start" in provider.requests[1][-1]["content"]
    assert "Formal application" in provider.requests[1][-1]["content"]


def test_no_tool_correction_can_prepare_once_within_original_budget():
    invalid = ModelTurn(final=FinalAnswer(kind="action", effect="prepare", message="Ready"))
    provider = Provider(invalid, call("prepare"), action)
    writes = []
    result = WorkbenchAgent(provider, [ToolSpec(
        "prepare", "Prepare only", Args,
        lambda _: writes.append("draft") or {"status": "queued", "applied": False},
        "prepare",
    )], max_turns=3).run([{"role": "user", "content": "Replace pending suggestion"}], "Scoped")
    assert result.error_code is None
    assert writes == ["draft"]
    assert len(provider.requests) == 3
    assert result.final.receipt_ids == [result.tool_results[-1]["receipt"]["id"]]


def test_final_shape_diagnostics_are_enum_only():
    assert safe_receipt_diagnostic({"kind": "private text", "effect": ["read"]}) == {}
    assert safe_receipt_diagnostic({"kind": "action", "effect": "read", "raw": "private"}) == {
        "kind": "action", "effect": "read",
    }


@pytest.mark.parametrize("answer_text", ["已开始为您生成改写草稿", "A factual explanation"])
def test_production_no_tool_check_uses_existing_budget_without_forcing_a_tool(answer_text):
    from test_workbench_agent import answer

    provider = Provider(answer(answer_text), answer("Informational reply; no operation executed"))
    result = WorkbenchAgent(provider, [], max_turns=2).run(
        [{"role": "user", "content": "Synthetic current request"}], "Scoped",
        verify_no_effect_answer=True, completion_state=lambda: {},
    )
    assert result.error_code is None and len(provider.requests) == 2
    assert result.tool_results == [] and result.final.effect == "none"
    assert "NO domain task or diff was created" in provider.requests[1][-1]["content"]
    event = next(e for e in result.events if e["type"] == "final_correction")
    assert safe_event(event)["error_code"] == "agent_execution_unverified"
    terminal = result.events[-1]
    assert terminal["completion"]["completion_code"] == "dialogue_only"


def test_false_start_claim_can_prepare_once_after_no_effect_check():
    from test_workbench_agent import answer

    provider = Provider(answer("已开始为您生成改写草稿"), call("prepare"), action)
    drafted = []
    result = WorkbenchAgent(provider, [ToolSpec(
        "prepare", "Prepare only", Args,
        lambda _: drafted.append("draft") or {"status": "queued", "applied": False}, "prepare",
    )], max_turns=3).run([
        {"role": "user", "content": "Rewrite selected cases and wait for review"},
    ], "Scoped", verify_no_effect_answer=True)
    assert result.error_code is None and drafted == ["draft"]
    assert len(provider.requests) == 3
    assert result.final.receipt_ids == [result.tool_results[-1]["receipt"]["id"]]


def test_clarification_does_not_trigger_an_extra_no_effect_turn():
    provider = Provider(ModelTurn(final=FinalAnswer(kind="clarify", message="Which source?")))
    result = WorkbenchAgent(provider, []).run([], "Scoped", verify_no_effect_answer=True)
    assert result.status == "awaiting_input" and len(provider.requests) == 1


@pytest.mark.parametrize("prepare_requested", [False, True])
def test_selected_context_read_check_does_not_force_a_write_for_information(prepare_requested):
    provider = Provider(call("read_attachment_evidence"), action,
                        *([call("prepare", "prepare"), action] if prepare_requested else [action]))
    writes = []
    result = WorkbenchAgent(provider, [
        ToolSpec("read_attachment_evidence", "Read synthetic material", Args,
                 lambda _: {"evidence": ["synthetic requirement"]}),
        ToolSpec("prepare", "Prepare only", Args,
                 lambda _: writes.append("draft") or {"status": "queued", "applied": False},
                 "prepare"),
    ], max_turns=4).run([
        {"role": "user", "content": "Rewrite selected cases" if prepare_requested
         else "Explain the reference only; do not modify anything"},
    ], "Scoped", verify_no_effect_answer=True, completion_state=lambda: {})
    assert result.error_code is None
    assert writes == (["draft"] if prepare_requested else [])
    assert len(provider.requests) == (4 if prepare_requested else 3)
    assert result.final.effect == ("prepare" if prepare_requested else "read")
    assert sum(e["type"] == "final_correction" for e in result.events) == 1
    if not prepare_requested:
        assert result.events[-1]["completion"]["completion_code"] == "tool_result_only"
