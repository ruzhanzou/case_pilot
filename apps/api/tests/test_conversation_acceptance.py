import json
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from casepilot_api.agent_router import DEFAULT_ACTIONS, deterministic_plan
from casepilot_api.conversations import classify_intent
from casepilot_api.schemas import ConversationOperationCollectionConfirmRequest

FIXTURE = Path(__file__).parent / "fixtures" / "conversation_intent_acceptance.json"


def _macro_f1(expected: list[str], actual: list[str]) -> float:
    labels = sorted(set(expected) | set(actual))
    scores: list[float] = []
    for label in labels:
        true_positive = sum(
            wanted == label and got == label
            for wanted, got in zip(expected, actual, strict=True)
        )
        false_positive = sum(
            wanted != label and got == label
            for wanted, got in zip(expected, actual, strict=True)
        )
        false_negative = sum(
            wanted == label and got != label
            for wanted, got in zip(expected, actual, strict=True)
        )
        denominator = 2 * true_positive + false_positive + false_negative
        scores.append(0.0 if denominator == 0 else 2 * true_positive / denominator)
    return sum(scores) / len(scores)


def test_conversation_intent_acceptance_macro_f1_and_write_precision() -> None:
    samples = json.loads(FIXTURE.read_text(encoding="utf-8"))
    expected: list[str] = []
    actual: list[str] = []
    ids_by_failure: list[str] = []
    for sample in samples:
        intent, _ = classify_intent(
            sample["text"],
            has_targets=sample.get("has_targets", False),
            phase=sample.get("phase", "idle"),
        )
        expected.append(sample["expected"])
        actual.append(intent)
        if intent != sample["expected"]:
            ids_by_failure.append(sample["id"])

    assert _macro_f1(expected, actual) >= 0.92, ids_by_failure
    for intent, threshold in {
        "CASE_GENERATE": 0.95,
        "CASE_MODIFY": 0.95,
        "CASE_DELETE": 0.99,
    }.items():
        predicted = Counter(
            wanted == intent
            for wanted, got in zip(expected, actual, strict=True)
            if got == intent
        )
        precision = predicted[True] / sum(predicted.values())
        assert precision >= threshold, (intent, precision, ids_by_failure)


def test_asset_operations_expose_the_acceptance_action_contract() -> None:
    expected_actions = {
        "CASE_GENERATE": "BRIEF_CREATE",
        "CASE_MODIFY": "CHANGESET_PREPARE",
        "CASE_DELETE": "CASE_DELETE_PREPARE",
        "CASE_QUERY": "CASE_SEARCH",
        "KNOWLEDGE_QA": "ANSWER_QUESTION",
        "SMALL_TALK": "ANSWER_QUESTION",
        "UNRESOLVED": "CLARIFY_INTENT",
    }

    assert expected_actions == DEFAULT_ACTIONS


def test_four_operations_are_limited_to_three_without_reordering() -> None:
    plan = deterministic_plan(
        "先解释等价类；再查询用例；然后修改当前用例；最后删除旧用例",
        lambda clause: (
            ("CASE_QUERY", 0.96)
            if "查询" in clause
            else ("CASE_MODIFY", 0.96)
            if "修改" in clause
            else ("CASE_DELETE", 0.99)
            if "删除" in clause
            else ("KNOWLEDGE_QA", 0.94)
        ),
        has_targets=True,
    )

    assert [item.intent for item in plan.operations] == [
        "KNOWLEDGE_QA",
        "CASE_QUERY",
        "CASE_MODIFY",
    ]


def test_collection_confirmation_requires_exactly_one_choice() -> None:
    with pytest.raises(ValidationError):
        ConversationOperationCollectionConfirmRequest()
    with pytest.raises(ValidationError):
        ConversationOperationCollectionConfirmRequest(
            collection_id="00000000-0000-0000-0000-000000000001",
            create_collection_name="重复选择",
        )

    existing = ConversationOperationCollectionConfirmRequest(
        collection_id="00000000-0000-0000-0000-000000000001"
    )
    created = ConversationOperationCollectionConfirmRequest(
        create_collection_name="  新验收集合  "
    )
    assert str(existing.collection_id).endswith("0001")
    assert created.create_collection_name == "新验收集合"
