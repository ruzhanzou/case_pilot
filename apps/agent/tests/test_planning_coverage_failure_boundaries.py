"""Synthetic malformed provider responses identify guards, not the live failure cause."""

from copy import deepcopy

import pytest
from test_parallel_planning import features
from test_planning_quality_flow import (
    RULE,
    SAMPLING,
    bind_scripted_points,
    boundary_contract,
    boundary_sample,
    obligation,
    point,
)

from casepilot_agent.contracts import RequirementAnalysis
from casepilot_agent.planning import build_planning


def boundary_fixture(payload):
    values = (
        deepcopy(payload["existing_plan"]["test_points"])
        if payload.get("coverage_completion")
        else [point(6)]
    )
    if not payload.get("coverage_completion"):
        values[0]["boundary_samples"] = [boundary_sample(6)]
    threshold = obligation("threshold", ["p0"])
    threshold["boundary_contract"] = boundary_contract()
    unclear = obligation("unspecified_reset", [])
    unclear["clarification"] = "Reset boundary is not specified; request clarification"
    if payload.get("coverage_completion"):
        extra = point(7, "p1")
        # Keep the original two-point count: one point can explicitly check two
        # coordinates, neither coordinate may be inferred from prose.
        extra["boundary_samples"] = [boundary_sample(7), boundary_sample(8)]
        values.append(extra)
        threshold["point_ids"] = ["p0", "p1"]
    return values, [threshold, unclear]


def evidence_context():
    return {"user_input": RULE, "test_setup": [SAMPLING]}


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("foreign_point", "planning_coverage_point_reference_invalid"),
        ("foreign_owner", "literal_error"),
        ("drop_obligation", "planning_coverage_obligation_changed"),
        ("paraphrase_basis", "planning_coverage_obligation_changed"),
        ("paraphrase_original", "planning_coverage_existing_point_changed"),
        ("rename_original", "planning_boundary_sample_link_invalid"),
        ("duplicate_id", "planning_coverage_point_id_duplicate"),
    ],
)
def test_plausible_second_response_fails_closed_with_precise_domain_code(mutation, expected):
    calls = []

    def complete(stage, instruction, payload, schema):
        if stage == "feature.generated":
            return features(1)
        owner = payload["feature_points"]["feature_points"][0]["id"]
        values, obligations = boundary_fixture(payload)
        for value in values + obligations:
            value["feature_point_ids"] = [owner]
            if "source_refs" in value:
                value["primary_feature_id"] = owner
        if payload.get("coverage_completion"):
            if mutation == "foreign_point":
                obligations[0]["point_ids"].append("p99")
            elif mutation == "foreign_owner":
                # New obligation avoids the separate immutable-existing-obligation guard.
                obligations.append({**obligation("new", []), "feature_point_ids": ["foreign"]})
            elif mutation == "drop_obligation":
                obligations.pop(1)
            elif mutation == "paraphrase_basis":
                obligations[0]["basis"] += " (restated)"
            elif mutation == "paraphrase_original":
                values[0]["objective"] += "."
            elif mutation == "rename_original":
                values[0]["id"] = "renamed"
            elif mutation == "duplicate_id":
                values.append(deepcopy(values[1]))
        calls.append(payload.get("coverage_completion", False))
        return schema.model_validate(
            {
                "test_points": bind_scripted_points(payload, values),
                "coverage_obligations": obligations,
            }
        )

    with pytest.raises(ValueError, match=expected):
        build_planning(RequirementAnalysis(summary="Explicit rule"), evidence_context(), complete)
    assert calls == [False, True]


@pytest.mark.parametrize("bad_kind", ["link", "original"])
@pytest.mark.parametrize("terminal", [False, True])
def test_existing_sdk_structured_retry_sees_same_guards_and_safe_codes(
    monkeypatch, bad_kind, terminal
):
    import json
    from types import SimpleNamespace

    from agents import Runner
    from agents.exceptions import ModelBehaviorError

    from casepilot_agent.providers.agents_sdk import AgentsSdkProvider
    from casepilot_agent.providers.safe_diagnostics import observe_structured_failures

    calls, diagnostics, response = [], [], {}
    expected = (
        "planning_coverage_point_reference_invalid"
        if bad_kind == "link"
        else "planning_coverage_existing_point_changed"
    )

    async def fake_run(agent, *args, **kwargs):
        value = deepcopy(response)
        calls.append(1)
        if terminal or len(calls) == 1:
            if bad_kind == "link":
                value["coverage_obligations"][0]["point_ids"].append("UNTRUSTED_PRIVATE_FOREIGN_ID")
            else:
                value["test_points"][0]["objective"] = "UNTRUSTED_PRIVATE_CHANGED_ASSERTION"
        output = agent.output_type.validate_json(json.dumps(value))
        return SimpleNamespace(
            final_output=output, context_wrapper=SimpleNamespace(usage=SimpleNamespace())
        )

    monkeypatch.setattr(Runner, "run", fake_run)
    provider = AgentsSdkProvider(
        base_url="https://example.test/v1",
        api_key="test-only",
        model="same",
        pro_model="same",
        local_model="same",
        timeout=5,
    )

    def complete(stage, instruction, payload, schema):
        if stage == "feature.generated":
            return features(1)
        owner = payload["feature_points"]["feature_points"][0]["id"]
        values, obligations = boundary_fixture(payload)
        for value in values + obligations:
            value["feature_point_ids"] = [owner]
            if "source_refs" in value:
                value["primary_feature_id"] = owner
        candidate = {
            "test_points": bind_scripted_points(payload, values),
            "coverage_obligations": obligations,
        }
        if not payload.get("coverage_completion"):
            return schema.model_validate(candidate)
        response.update(candidate)
        return provider.complete(
            stage=stage,
            instruction=instruction,
            payload=payload,
            result_type=schema,
            model_id="auto",
        )[0]

    with observe_structured_failures(diagnostics.append):
        if terminal:
            with pytest.raises(ModelBehaviorError):
                build_planning(
                    RequirementAnalysis(summary="Explicit rule"), evidence_context(), complete
                )
        else:
            plan = build_planning(
                RequirementAnalysis(summary="Explicit rule"), evidence_context(), complete
            )
            assert len(plan["test_points"]) == 2
            assert plan["coverage_review"]["batches"][0]["uncovered_ids"] == []
    assert len(calls) == 2  # Existing provider retry only; no extra planning repair loop.
    assert len(diagnostics) == (2 if terminal else 1)
    assert all(event["validation_errors"][0]["type"] == expected for event in diagnostics)
    assert "UNTRUSTED_PRIVATE" not in json.dumps(diagnostics)
    assert all("counts" not in item for event in diagnostics for item in event["validation_errors"])
