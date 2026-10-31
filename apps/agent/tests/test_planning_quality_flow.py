"""Scripted contracts, not claims that a live model understands rule semantics."""

from copy import deepcopy

import pytest
from test_parallel_planning import features

from casepilot_agent.contracts import RequirementAnalysis
from casepilot_agent.planning import build_planning

RULE = "elapsed since issue must be less than 7 seconds; otherwise invalid"
SAMPLING = "sample every 1 seconds"


def boundary_contract(*, sampling=True):
    return dict(
        source_slot="source:0",
        source_literal=RULE,
        threshold=7.0,
        unit="seconds",
        comparator="lt",
        axis="elapsed",
        time_origin="since issue",
        sampling_step=1.0 if sampling else None,
        sampling_literal=SAMPLING if sampling else "",
    )


def boundary_sample(value, identifier="threshold"):
    return dict(
        obligation_id=identifier,
        position={6: "before", 7: "at", 8: "after"}[value],
        value=float(value),
        initial_state="issued and not previously consumed",
        assertion="valid" if value < 7 else "invalid",
        assertion_role="primary",
    )


def point(value, identifier="p0"):
    return dict(
        id=identifier,
        title=f"elapsed {value}",
        scenario=f"elapsed {value}",
        objective=f"Check explicit threshold at {value}",
        category="boundary",
        priority="P1",
        priority_reason="Given rule",
        feature_point_ids=[],
        source_refs=[{"locator": "source:0", "label": "ignored"}],
    )


def bind_scripted_points(payload, values):
    """Select a real server pair for the script's explicitly intended owner."""
    for value in values:
        owner = value.pop("primary_feature_id", None) or value["feature_point_ids"][0]
        slots = {ref.get("locator") for ref in value.get("source_refs", [])}
        choices = [item for item in payload["primary_bindings"] if item["feature_id"] == owner]
        binding = next((item for item in choices if item["source_slot"] in slots), choices[0])
        value["primary_binding"] = binding["id"]
        for sample in value.get("boundary_samples") or []:
            sample.setdefault("assertion_binding", binding["id"])
    return values


def obligation(identifier, refs):
    return dict(
        id=identifier,
        feature_point_ids=[],
        dimension="boundary",
        basis="Explicit integer seconds: elapsed < 7 is valid; >= 7 invalid",
        point_ids=refs,
        clarification="",
    )


def run(*, target=None, fill=True, mutate=False, ambiguity=False):
    calls = []

    def complete(stage, instruction, payload, schema):
        if stage == "feature.generated":
            return features(1)
        calls.append(deepcopy(payload))
        owner = payload["feature_points"]["feature_points"][0]["id"]
        values = (
            deepcopy(payload["existing_plan"]["test_points"])
            if payload.get("coverage_completion")
            else [point(6)]
        )
        obligations = [obligation("threshold", ["p0"])]
        obligations[0]["boundary_contract"] = boundary_contract()
        if not payload.get("coverage_completion"):
            values[0]["boundary_samples"] = [boundary_sample(6)]
        if payload.get("coverage_completion") and fill:
            for value, identifier in [(7, "p1"), (8, "p2")]:
                added = point(value, identifier)
                added["boundary_samples"] = [boundary_sample(value)]
                values.append(added)
            obligations[0]["point_ids"] = ["p0", "p1", "p2"]
        if payload.get("coverage_completion") and mutate:
            values[0]["objective"] = "Changed existing assertion"
        if ambiguity:
            # Sampling granularity/state is unknown: no adjacent coordinates or
            # claimed coverage are fabricated, and the original point stays put.
            values[0].pop("boundary_samples", None)
            obligations[0]["point_ids"] = []
            obligations[0]["boundary_contract"] = boundary_contract(sampling=False)
            obligations[0]["clarification"] = (
                "No specified sampling step or initial state; clarify instead of inventing"
            )
        for item in values + obligations:
            item["feature_point_ids"] = [owner]
            if "source_refs" in item:
                item["primary_feature_id"] = owner
        return schema.model_validate(
            {
                "test_points": bind_scripted_points(payload, values),
                "coverage_obligations": obligations,
            }
        )

    return build_planning(
        RequirementAnalysis(summary="Given threshold"),
        {"user_input": RULE, "test_setup": [] if ambiguity else [SAMPLING]},
        complete,
        target_count=target,
    ), calls


def test_no_budget_is_not_three_per_feature_and_one_completion_retains_boundaries():
    plan, calls = run()
    assert len(calls) == 2 and calls[0]["batch_count"] == 24
    assert calls[1]["coverage_completion"] is True
    assert len(plan["test_points"]) == 3
    samples = [sample for p in plan["test_points"] for sample in p["boundary_samples"]]
    assert {(sample["position"], sample["value"]) for sample in samples} == {
        ("before", 6.0),
        ("at", 7.0),
        ("after", 8.0),
    }
    assert all(
        sample["unit"] == "seconds"
        and sample["time_origin"] == "since issue"
        and "assertion_binding" not in sample
        for sample in samples
    )
    review = plan["coverage_review"]
    assert review["status"] == "pending_independent_review"
    batch = review["batches"][0]
    assert batch["completion_attempted"] and batch["uncovered_ids"] == []
    real_ids = {p["id"] for p in plan["test_points"]}
    assert {p for item in batch["obligations"] for p in item["point_ids"]} == real_ids
    assert {f for item in batch["obligations"] for f in item["feature_point_ids"]} <= {
        f["id"] for f in plan["feature_points"]
    }


def test_exact_budget_never_appends_but_persists_uncovered_warning():
    plan, calls = run(target=1)
    assert len(calls) == 1 and len(plan["test_points"]) == 1
    batch = plan["coverage_review"]["batches"][0]
    assert batch["uncovered_ids"] == ["threshold"]
    assert batch["warnings"] == [
        "coverage_unverified", "boundary_semantics_requires_review", "coverage_budget_limited"
    ]


def test_completion_remains_bounded_and_unresolved_gaps_visible():
    plan, calls = run(fill=False)
    assert len(calls) == 2
    assert plan["coverage_review"]["batches"][0]["warnings"] == [
        "coverage_unverified",
        "boundary_semantics_requires_review",
        "coverage_gap_remaining",
    ]


def test_undefined_rules_are_clarification_not_invented_completion():
    plan, calls = run(ambiguity=True)
    assert len(calls) == 1
    assert len(plan["coverage_review"]["batches"][0]["clarifications"]) == 1
    assert len(plan["test_points"]) == 1
    assert not plan["test_points"][0].get("boundary_samples")


def test_completion_cannot_rewrite_existing_point():
    with pytest.raises(ValueError, match="planning_coverage_existing_point_changed"):
        run(mutate=True)


def test_global_default_batch_budget_stops_before_point_calls():
    def complete(stage, instruction, payload, schema):
        assert stage == "feature.generated"
        return features(100)

    plan = build_planning(
        RequirementAnalysis(summary="Many rules"),
        {"user_input": "Plan the supplied 100 synthetic rules"},
        complete,
    )
    assert plan["test_points"] == []
    assert len(plan["feature_points"]) == 100
    assert plan["coverage_review"]["warnings"] == ["coverage_scope_limit"]


def test_distinct_objectives_collision_never_merges_and_ids_ignore_order():
    from casepilot_agent.contracts import TestPoint as Point
    from casepilot_agent.planning import merge_planning

    feature = features(1).feature_points[0]
    first, second = point(7, "one"), point(7, "two")
    for item in (first, second):
        item["feature_point_ids"] = [feature.id]
    second["objective"] = "Check the distinct explicit exception condition"
    points = [Point.model_validate(item) for item in (first, second)]
    a = merge_planning([feature], points, {}, 1)["test_points"]
    b = merge_planning([feature], list(reversed(points)), {}, 1)["test_points"]
    assert len(a) == len(b) == 2
    assert {p["objective"]: p["id"] for p in a} == {p["objective"]: p["id"] for p in b}
    duplicate = points[0].model_copy(update={"id": "three"})
    assert len(merge_planning([feature], [points[0], duplicate], {}, 1)["test_points"]) == 1


def test_split_chunk_same_identity_never_hydrates_unseen_other_slice():
    first, second = "A" * 18000, "B" * 18000
    seen = []

    def complete(stage, instruction, payload, schema):
        if stage == "feature.generated":
            plan = features(1).model_dump()
            rule = payload["context"]["evidence"][0]["excerpt"][0]
            plan["feature_points"][0]["name"] = f"Rule {rule}"
            plan["feature_points"][0]["source_refs"] = [{"locator": "source:1", "label": "select"}]
            return schema.model_validate(plan)
        assert not any(key.startswith("_") for key in payload)
        snippet = payload["source_catalog"][1]["excerpt"]
        seen.append(snippet)
        value = point(snippet[0])
        value["feature_point_ids"] = [payload["feature_points"]["feature_points"][0]["id"]]
        value["primary_feature_id"] = value["feature_point_ids"][0]
        value["source_refs"] = [{"locator": "source:1", "label": "select"}]
        return schema.model_validate({"test_points": bind_scripted_points(payload, [value])})

    plan = build_planning(
        RequirementAnalysis(summary="Split rules"),
        {
            "user_input": "Inspect the supplied split rules without adding outside sources",
            "evidence": [
                {
                    "source_id": "s",
                    "document_id": "d",
                    "chunk_id": "c",
                    "label": "Actual source",
                    "locator": "page1",
                    "excerpt": first + second,
                }
            ],
        },
        complete,
    )
    assert set(seen) == {first, second}
    for point_data in plan["test_points"]:
        refs = point_data["source_refs"]
        assert len(refs) == 1 and refs[0]["excerpt"] in {first, second}
        assert refs[0]["excerpt"][0] in point_data["title"]


@pytest.mark.parametrize("parallel", [False, True])
def test_cancellation_after_initial_response_prevents_completion_and_more_dispatch(parallel):
    from contextvars import ContextVar
    from threading import Barrier, Event, Lock

    marker = ContextVar("quality_run_marker", default="unbound")
    cancelled, lock, calls = Event(), Lock(), []
    first_wave = Barrier(3, timeout=5) if parallel else None

    class Cancelled(Exception):
        pass

    def check():
        assert marker.get() == "authorized-run"
        if cancelled.is_set():
            raise Cancelled()

    def complete(stage, instruction, payload, schema):
        assert marker.get() == "authorized-run"
        if stage == "feature.generated":
            return features(10 if parallel else 1)
        with lock:
            calls.append(deepcopy(payload))
        assert not payload.get("coverage_completion")
        if first_wave:
            first_wave.wait()
        owners = [f["id"] for f in payload["feature_points"]["feature_points"]]
        value = point(6)
        value["feature_point_ids"] = owners
        value["primary_feature_id"] = owners[0]
        missing = obligation("threshold", ["p0"])
        missing["boundary_contract"] = boundary_contract()
        missing["feature_point_ids"] = owners
        value["boundary_samples"] = [boundary_sample(6)]
        response = schema.model_validate(
            {
                "test_points": bind_scripted_points(payload, [value]),
                "coverage_obligations": [missing],
            }
        )
        cancelled.set()
        return response

    token = marker.set("authorized-run")
    try:
        with pytest.raises(Cancelled):
            build_planning(
                RequirementAnalysis(summary="Rules"),
                {"user_input": RULE, "test_setup": [SAMPLING]},
                complete,
                check_cancelled=check,
            )
    finally:
        marker.reset(token)
    assert marker.get() == "unbound"
    assert len(calls) == (3 if parallel else 1)
    assert all(not call.get("coverage_completion") for call in calls)


def test_semantic_review_guidance_reaches_initial_and_only_completion(monkeypatch):
    import casepilot_agent.planning as planning

    original = planning.build_planning
    instructions = []

    def observed(requirement, context, complete, **kwargs):
        def capture(stage, instruction, payload, schema):
            if stage == "test_point.generated":
                instructions.append(instruction)
            return complete(stage, instruction, payload, schema)
        return original(requirement, context, capture, **kwargs)

    monkeypatch.setitem(run.__globals__, "build_planning", observed)
    plan, calls = run()
    assert len(instructions) == len(calls) == 2
    assert all("【独立边界与跨规则自查】" in value for value in instructions)
    assert plan["coverage_review"]["status"] == "pending_independent_review"
