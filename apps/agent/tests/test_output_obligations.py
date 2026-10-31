"""Deterministic output obligations; models interpret intent, never waive invariants."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from casepilot_agent.output_obligations import (
    bind_obligations,
    ensure_required_coverage,
    validate_output_obligations,
)
from casepilot_agent.quantity import OutputQuantity


def plan():
    return {
        "test_points": [{"id": "P1"}, {"id": "P2"}],
        "approved_source_catalog": [
            {"key": "asset:a", "revision": "r1"},
            {"key": "asset:b", "revision": "r2"},
        ],
        "reuse": {
            "decisions": [
                {
                    "point_id": "P1",
                    "action": "reuse",
                    "source": {"key": "asset:a", "revision": "r1"},
                }
            ]
        },
    }


def case(key=None, action="reuse"):
    import json

    return SimpleNamespace(
        source_refs=[]
        if key is None
        else [SimpleNamespace(excerpt=json.dumps({"source_key": key, "action": action}))]
    )


def test_explicit_required_subset_not_all_approved_and_exact_new_count():
    value = plan()
    bind_obligations(
        value,
        OutputQuantity(
            required_reuse_source_keys=["asset:a"], output_case_count=2, new_case_count=1
        ),
    )
    assert value["output_obligations"]["required_reuse_source_keys"] == ["asset:a"]
    validate_output_obligations(value, [case("asset:a"), case()])


@pytest.mark.parametrize("keys", [["foreign"], ["asset:a", "asset:a"]])
def test_unknown_or_duplicate_required_sources_rejected(keys):
    with pytest.raises(ValueError):
        bind_obligations(plan(), OutputQuantity(required_reuse_source_keys=keys))


@pytest.mark.parametrize(
    "cases",
    [
        [case(), case()],
        [case("asset:a"), case("asset:a")],
        [case("asset:a"), case("asset:b", "modify")],
        [case("asset:a")],
    ],
)
def test_missing_duplicate_wrong_count_and_modify_not_new_fail(cases):
    value = plan()
    bind_obligations(
        value,
        OutputQuantity(
            required_reuse_source_keys=["asset:a"], output_case_count=2, new_case_count=1
        ),
    )
    with pytest.raises(ValueError):
        validate_output_obligations(value, cases)


def test_point_or_reviewer_change_invalidates_binding():
    value = plan()
    bind_obligations(value, OutputQuantity(required_reuse_source_keys=["asset:a"]))
    value["reuse"]["user_choices"] = {"P1": "new"}
    with pytest.raises(ValueError, match="changed"):
        validate_output_obligations(value, [case("asset:a")])


def test_fresh_plan_coverage_corrected_once_but_reviewed_plan_never_replanned():
    value = plan()
    value["reuse"]["decisions"] = []
    quantity = OutputQuantity(required_reuse_source_keys=["asset:a"])
    calls = []

    def repair(current, missing):
        calls.append(missing)
        return plan()

    corrected = ensure_required_coverage(value, quantity, reviewed=False, repair=repair)
    assert calls == [["asset:a"]]
    assert corrected["reuse"]["decisions"]
    with pytest.raises(ValueError, match="required_reuse"):
        ensure_required_coverage(value, quantity, reviewed=True, repair=repair)
    assert len(calls) == 1


def test_failed_single_correction_is_truthful_failure():
    value = plan()
    value["reuse"]["decisions"] = []
    calls = []

    def repair(current, missing):
        calls.append(missing)
        return deepcopy(current)

    with pytest.raises(ValueError, match="required_reuse"):
        ensure_required_coverage(
            value,
            OutputQuantity(required_reuse_source_keys=["asset:a"]),
            reviewed=False,
            repair=repair,
        )
    assert len(calls) == 1


def test_reviewed_exclusion_cannot_revive_source_from_previous_obligation():
    from casepilot_agent.output_obligations import approved_catalog

    value = plan()
    bind_obligations(
        value,
        OutputQuantity(
            required_reuse_source_keys=["asset:a"], output_case_count=2, new_case_count=1
        ),
    )
    value["test_points"] = [{"id": "P2"}]
    value["reuse"]["decisions"] = []
    assert [item["key"] for item in approved_catalog(value)] == ["asset:b"]
    with pytest.raises(ValueError, match="required_reuse_source_invalid"):
        bind_obligations(value, OutputQuantity(required_reuse_source_keys=["asset:a"]))


def test_real_pipeline_reuse_one_plus_new_one_preserves_point_ids_and_source():
    from test_compact_generation import execute, request, run

    from casepilot_agent.contracts import GenerationRequest
    from casepilot_agent.providers.mock import MockProvider

    req = request(2)
    req.prompt = "复用原用例1条，再生成1条缺口用例"
    snapshot = (
        MockProvider()
        .generate(GenerationRequest(prompt="登录"))
        .test_cases[0]
        .model_dump(mode="json")
    )
    req.confirmed_plan["approved_source_catalog"] = [
        {"key": "asset:a", "revision": "r1"},
        {"key": "asset:b", "revision": "r2"},
    ]
    req.confirmed_plan["reuse"] = {
        "strategy": "regression",
        "decisions": [
            {
                "point_id": "P-0",
                "point_snapshot": deepcopy(req.confirmed_plan["test_points"][0]),
                "action": "reuse",
                "reason": "confirmed exact reuse",
                "source": {
                    "key": "asset:a",
                    "label": "Original",
                    "locator": "A",
                    "revision": "r1",
                    "snapshot": snapshot,
                },
            }
        ],
    }
    original = deepcopy(req.confirmed_plan)

    def executor(stage, instruction, payload, schema, model):
        if stage == "output_quantity.interpreted":
            return OutputQuantity(
                case_count=1,
                count_includes_reuse=False,
                required_reuse_source_keys=["asset:a"],
                output_case_count=2,
                new_case_count=1,
            )
        return execute(stage, instruction, payload, schema, model)

    result = run(req, executor)
    assert len(result.test_cases) == 2
    assert result.quality.passed
    assert result.test_cases[0].title == snapshot["title"]
    assert req.confirmed_plan == original
    assert [point.id for point in result.test_points] == ["P-0", "P-1"]
    assert result.model_metadata["output_obligations"]["new_case_count"] == 1


def test_final_validator_rejects_silent_missing_source_even_if_generation_claims_count(monkeypatch):
    from test_compact_generation import execute, request, run

    from casepilot_agent.contracts import GenerationRequest
    from casepilot_agent.providers.mock import MockProvider

    req = request(1)
    snapshot = (
        MockProvider()
        .generate(GenerationRequest(prompt="登录"))
        .test_cases[0]
        .model_dump(mode="json")
    )
    req.confirmed_plan["reuse"] = {
        "strategy": "regression",
        "decisions": [
            {
                "point_id": "P-0",
                "point_snapshot": deepcopy(req.confirmed_plan["test_points"][0]),
                "action": "reuse",
                "reason": "confirmed",
                "source": {
                    "key": "asset:a",
                    "label": "Original",
                    "locator": "A",
                    "snapshot": snapshot,
                },
            }
        ],
    }
    from casepilot_agent import compact_generation

    original_run = compact_generation.run_compact

    def corrupt(*args, **kwargs):
        result = original_run(*args, **kwargs)
        result.test_cases[0].source_refs = []
        return result

    monkeypatch.setattr(compact_generation, "run_compact", corrupt)

    def executor(stage, instruction, payload, schema, model):
        if stage == "output_quantity.interpreted":
            return OutputQuantity(
                required_reuse_source_keys=["asset:a"], output_case_count=1, new_case_count=0
            )
        return execute(stage, instruction, payload, schema, model)

    with pytest.raises(ValueError, match="required_reuse_output"):
        run(req, executor)


@pytest.mark.parametrize("reviewed,still_missing,conflict", [
    (False, False, None), (False, True, None), (True, False, None),
    (False, True, "mapping"), (False, True, "budget"),
])
def test_worker_reserves_required_source_without_model_repair_but_preserves_reviewed_points(
    monkeypatch, reviewed, still_missing, conflict
):
    from uuid import uuid4

    from test_compact_generation import request
    from test_draft_planning_progress import Store

    from casepilot_agent import tasks
    from casepilot_agent.contracts import GenerationRequest, UsageMetadata
    from casepilot_agent.providers.mock import MockProvider
    from casepilot_agent.reuse import ReuseAnalysis

    store = Store()
    store.job["space_id"] = uuid4()
    original = request(2).confirmed_plan
    source = {
        "key": "asset:a",
        "kind": "formal",
        "label": "Original",
        "locator": "A",
        "revision": "r1",
        "snapshot": (MockProvider().generate(GenerationRequest(prompt="登录"))
                     .test_cases[0].model_dump(mode="json")),
    }
    store.job["input_payload"].update(
        prompt="复用原用例1条，再新增1条缺口",
        generation_strategy="select_and_generate",
        asset_selection_confirmed=True,
        confirmed_asset_sources=[source],
    )
    if conflict == "mapping":
        store.job["input_payload"]["confirmed_asset_sources"].append({**source, "key": "asset:b"})
    if reviewed:
        original["point_review_receipt"] = {"brief_id": str(uuid4()), "version": 1,
            "kind": "points", "point_ids": [p["id"] for p in original["test_points"]]}
        store.job["input_payload"]["current_test_brief"] = {"planning": deepcopy(original)}
    store.attach_reuse_collections = lambda connection, items, **kwargs: items

    def persist(connection, job, content):
        store.briefs.append(deepcopy(content))
        return 1

    store.persist_test_brief = persist

    class Provider:
        def complete(self, *, stage, payload, **kwargs):
            if stage == "output_quantity.interpreted":
                assert payload["approved_source_catalog"][0]["key"] == "asset:a"
                value = OutputQuantity(
                    required_reuse_source_keys=[s["key"] for s in
                        store.job["input_payload"]["confirmed_asset_sources"]],
                    test_point_count=1 if conflict == "budget" else None,
                    output_case_count=3 if conflict == "mapping" else 2, new_case_count=1
                )
            elif stage in {"requirement.analyzed", "requirement.extracted"}:
                value = ReuseAnalysis(
                    summary="login",
                    test_object="account",
                    test_object_specified=True,
                    generation_strategy="regression",
                )
            else:
                raise AssertionError(stage)
            return value, UsageMetadata(model="fixture")

    builds, comparisons = [], []

    def build(requirement, context, *args, **kwargs):
        builds.append(deepcopy(context))
        return deepcopy(original)

    def compare(plan, *args, **kwargs):
        comparisons.append(1)
        decisions = []
        if len(comparisons) == 2 and not still_missing:
            decisions = [
                {
                    "point_id": "P-0",
                    "point_snapshot": deepcopy(plan["test_points"][0]),
                    "action": "reuse",
                    "source": source,
                }
            ]
        return {"decisions": decisions, "strategy": "regression"}

    monkeypatch.setattr(tasks, "JobStore", lambda *args: store)
    monkeypatch.setattr(tasks, "create_provider", lambda *args: Provider())
    monkeypatch.setattr(tasks, "create_embedding_provider", lambda: None)
    monkeypatch.setattr(tasks, "_context_payload", lambda *args, **kwargs: {"evidence": []})
    monkeypatch.setattr(tasks, "build_planning", build)
    monkeypatch.setattr(tasks, "plan_reuse", compare)
    if conflict:
        tasks.draft_test_brief(str(store.job["id"]))
        content = store.briefs[0]
        expected = ("reserved_reuse_mapping_requires_clarification" if conflict == "mapping"
                    else "reserved_reuse_point_budget_requires_clarification")
        assert content["open_questions"][-1]["id"] == expected
        assert content["open_questions"][-1]["blocking"] is True
        pending = content["planning"]["pending_reserved_outputs"]
        assert pending["reason"] == expected
        assert pending["required_sources"] == store.job["input_payload"]["confirmed_asset_sources"]
        assert pending["quantity"]["new_case_count"] == 1
        assert content["planning"]["test_points"] == []
        assert not builds and not comparisons
        assert store.job["status"] == "completed"  # Only the blocking brief is ready for review.
        assert not content["planning"].get("point_review_receipt")
        return
    if reviewed:
        tasks.draft_test_brief(str(store.job["id"]))
        content = store.briefs[0]
        assert content["planning"]["test_points"] == original["test_points"]
        assert content["planning"]["pending_reserved_outputs"]["reason"] == (
            "reserved_reuse_mapping_requires_clarification"
        )
        assert content["open_questions"][-1]["blocking"]
        assert not builds and not comparisons
        return
    else:
        tasks.draft_test_brief(str(store.job["id"]))
        assert store.briefs[0]["planning"]["output_obligations"]["required_reuse_source_keys"] == [
            "asset:a"
        ]
    assert len(builds) == (0 if reviewed else 1)
    assert len(comparisons) == 1
    if builds:
        assert "required_coverage_feedback" not in builds[0]
        reserved = store.briefs[0]["planning"]["reserved_reuse_outputs"]
        assert len(reserved) == 1 and reserved[0]["source"] == source
        assert len(reserved[0]["point_ids"]) == 1
        assert not store.briefs[0]["planning"].get("point_review_receipt")


def test_candidate_catalog_retains_exact_version_and_canonical_identity():
    from casepilot_agent.contracts import GenerationRequest
    from casepilot_agent.providers.mock import MockProvider
    from casepilot_agent.reuse import normalize_sources

    snapshot = (
        MockProvider()
        .generate(GenerationRequest(prompt="login"))
        .test_cases[0]
        .model_dump(mode="json")
    )
    rows = normalize_sources(
        [{"ref": "draft-one", "target_type": "candidate", "version": 3, "snapshot": snapshot}], []
    )
    assert rows[0]["canonical_ref"] == "candidate:draft-one"
    assert rows[0]["revision"] == 3


def test_confirmation_marker_does_not_erase_unchanged_source_obligation():
    value = plan()
    bind_obligations(value, OutputQuantity(required_reuse_source_keys=["asset:a"]))
    value["reuse"]["asset_confirmation"] = "reuse"
    value["reuse"]["user_choices"] = {}
    validate_output_obligations(value, [case("asset:a")])
