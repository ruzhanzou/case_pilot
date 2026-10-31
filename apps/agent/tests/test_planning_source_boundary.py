"""Exercise provenance projection through planning and the unchanged execution guard."""
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from semantic_validation_fixture import with_point_semantics
from test_compact_generation import execute, request
from test_parallel_planning import features, points
from test_planning_sources import context

from casepilot_agent.compact_generation import StageContractError, run_compact
from casepilot_agent.contracts import RequirementAnalysis, SourceRef
from casepilot_agent.planning import build_planning
from casepilot_agent.planning_sources import source_selection_schema
from casepilot_agent.providers.safe_diagnostics import structured_failure


@pytest.mark.parametrize("attachment", [False, True])
def test_both_planning_outputs_and_progress_only_contain_server_provenance(attachment):
    batch = context() if attachment else {"user_input": "Original user rule", "evidence": []}
    observed, calls = [], []

    def complete(stage, instruction, payload, schema):
        calls.append(stage)
        if stage == "feature.generated":
            value = features(1).model_dump()
            value["feature_points"][0]["source_refs"] = [{
                "label": "MODEL_PRIVATE_FALSE_LABEL", "excerpt": "MODEL_PRIVATE_INSTRUCTION",
                "locator": "source:1" if attachment else "source:0",
            }]
            return schema.model_validate(value)
        return points(payload, fill_budget=True)

    plan = build_planning(RequirementAnalysis(summary="Rule"), batch, complete,
                          target_count=1, on_progress=lambda value, _: observed.append(value))
    ref = plan["test_points"][0]["source_refs"][0]
    if attachment:
        assert ref == batch["evidence"][0]
    else:
        assert ref["excerpt"] == batch["user_input"]
        assert not any(ref[field] for field in ("source_id", "document_id", "chunk_id"))
    assert calls == ["feature.generated", "test_point.generated"]
    assert "MODEL_PRIVATE" not in json.dumps([plan, observed])


def test_preprovided_feature_plan_cannot_bypass_batch_source_authority():
    value = features(1)
    value.feature_points[0].source_refs = [SourceRef(
        source_id="foreign-source", document_id="foreign-document", chunk_id="foreign-chunk",
        label="foreign",
    )]
    with pytest.raises(ValueError, match="^planning_source_reference_invalid$"):
        build_planning(RequirementAnalysis(summary="Rule"), context(),
                       lambda *a: pytest.fail("must reject before point model"),
                       feature_plans=[value], target_count=1)


def test_generation_guard_rejects_mixed_identity_even_when_chunk_is_known():
    req = request(1)
    canonical = context()["evidence"][0]
    req.confirmed_plan["evidence"] = [canonical]
    req.confirmed_plan["test_points"][0]["source_refs"] = [
        {**canonical, "source_id": "foreign-source"}
    ]
    with pytest.raises(StageContractError, match="invalid_source_reference"):
        run_compact(req, SimpleNamespace(name="real"), with_point_semantics(execute), None, 1)


def test_selection_schema_diagnostics_only_expose_fixed_fields_and_error_types():
    from casepilot_agent.contracts import FeaturePlan

    schema = source_selection_schema(FeaturePlan, context())
    data = features(1).model_dump()
    data["feature_points"][0]["source_refs"] = [{
        "locator": "source:999_PRIVATE", "chunk_id": "PRIVATE_CHUNK_ID",
        "label": "PRIVATE_LABEL", "excerpt": "PRIVATE_PROMPT_BODY",
    }]
    with pytest.raises(ValidationError) as caught:
        schema.model_validate(data)
    diagnostic = structured_failure(caught.value, stage="feature.generated", result_type=schema)
    assert {item["type"] for item in diagnostic["validation_errors"]} == {
        "literal_error", "none_required",
    }
    assert "PRIVATE" not in json.dumps(diagnostic)
    assert all(item["loc"][-1] in {"locator", "chunk_id"}
               for item in diagnostic["validation_errors"])
