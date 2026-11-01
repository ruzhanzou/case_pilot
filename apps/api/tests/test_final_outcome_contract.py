import json

import pytest
from agents.exceptions import ModelBehaviorError
from test_workbench_agent import Args, Provider, action, call, run

from casepilot_api.workbench_agent import FinalAnswer, ModelTurn, ToolSpec
from casepilot_api.workbench_receipts import CurrentReceiptSchema


def receipt(status="queued", **changes):
    return {"effect": "prepare", "fulfilled_actions": ("CASE_MODIFY",), "result": {
        "status": status, "requires_human_review": status == "awaiting_input", "applied": False,
        "proposal": {"status": "pending"} if status == "awaiting_input" else None, **changes,
    }}


@pytest.mark.parametrize("status", ["queued", "running", "completed"])
def test_computation_cannot_advertise_informational_prepare(status):
    choices = CurrentReceiptSchema(FinalAnswer, {"current:1": receipt(status)}).json_schema()
    assert choices["properties"]["outcome"]["enum"] == [
        "answer_none", "clarify_none", "action_prepare"]


def test_pending_human_review_can_be_explained_but_cannot_claim_applied():
    schema = CurrentReceiptSchema(FinalAnswer, {"current:1": receipt("awaiting_input")})
    assert "answer_prepare" in schema.json_schema()["properties"]["outcome"]["enum"]
    final = schema.validate_json(json.dumps({"outcome": "answer_prepare", "message": "Pending",
                                           "receipt_ids": ["current:1"]}))
    assert (final.kind, final.effect) == ("answer", "prepare")
    choices = CurrentReceiptSchema(FinalAnswer, {"current:1": receipt(
        "awaiting_input", applied=True)}).json_schema()["properties"]["outcome"]["enum"]
    assert "answer_prepare" not in choices


@pytest.mark.parametrize("value", [
    {"outcome": "action_applied"}, {"outcome": {"private": "text"}},
    {"outcome": "action_prepare", "kind": "answer"},
])
def test_invalid_or_ambiguous_wire_claim_is_not_repaired(value):
    with pytest.raises(ModelBehaviorError, match="agent_final_outcome_invalid"):
        CurrentReceiptSchema(FinalAnswer, {}).validate_json(json.dumps(value))


def test_real_sdk_wire_decoding_still_requires_current_receipt_and_one_prepare():
    def wire(messages):
        legacy = action(messages).final
        return ModelTurn(text=json.dumps({"outcome": "action_prepare", "message": "Queued",
                                         "receipt_ids": legacy.receipt_ids}))

    calls = []
    result = run(Provider(call("prepare"), wire), [ToolSpec(
        "prepare", "Draft only", Args,
        lambda _: calls.append(True) or receipt()["result"], "prepare",
        fulfilled_actions=("CASE_MODIFY",),
    )])
    assert result.error_code is None and result.final.kind == "action" and calls == [True]


def test_foreign_receipt_remains_foreign_after_wire_decode():
    final = CurrentReceiptSchema(FinalAnswer, {}).validate_json(json.dumps({
        "outcome": "action_prepare", "message": "Queued", "receipt_ids": ["foreign:1"],
    }))
    result = run(Provider(ModelTurn(final=final), ModelTurn(final=final)))
    assert result.error_code == "agent_final_receipt_invalid"
