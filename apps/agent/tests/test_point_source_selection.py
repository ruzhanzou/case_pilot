"""Point evidence dependencies are not inferred from feature ownership."""
from copy import deepcopy

import pytest
from pydantic import Field, ValidationError, create_model

from casepilot_agent.contracts import SourceRef
from casepilot_agent.contracts import TestPoint as Point
from casepilot_agent.contracts import TestPointPlan as PointPlan
from casepilot_agent.planning_sources import (
    payload_catalog,
    point_source_selection_type,
    project_point_sources,
)


def context():
    return {"user_input": "Test authorization and timeout independently", "evidence": [
        {"source_id": "S", "document_id": "D", "chunk_id": "owner-rule",
         "label": "Ownership rule", "locator": "section 1", "excerpt": "The owner may approve."},
        {"source_id": "S", "document_id": "D", "chunk_id": "time-rule",
         "label": "Time dependency", "locator": "section 2",
         "excerpt": "Approval expires at 30 seconds."},
    ]}


def point(refs):
    return Point(id="P", title="Owner approval at expiry", objective="Expiry is enforced",
                 category="boundary", priority="P1", priority_reason="Explicit threshold",
                 feature_point_ids=["ownership-feature"], source_refs=refs)


def selection_plan(ctx):
    selected_point = point_source_selection_type(Point, ctx)
    return create_model("BatchPointPlan", __base__=PointPlan,
                        test_points=(list[selected_point], Field(default_factory=list)))


def test_point_can_cite_dependency_without_claiming_its_feature_ownership():
    ctx = context()
    before = deepcopy(ctx)
    schema = selection_plan(ctx)
    model_value = schema.model_validate({"test_points": [point([
        SourceRef(locator="source:2", label="Forged label", excerpt="Invented exception")
    ]).model_dump()]})
    result = project_point_sources(model_value, ctx)
    assert type(result) is PointPlan
    assert result.test_points[0].feature_point_ids == ["ownership-feature"]
    assert result.test_points[0].source_refs == [SourceRef.model_validate(ctx["evidence"][1])]
    assert "Invented exception" not in result.model_dump_json()
    assert ctx == before


def test_current_point_request_catalog_is_the_only_schema_authority():
    ctx = context()
    ctx["evidence"] = ctx["evidence"][:1]
    schema = selection_plan(ctx)
    props = schema.model_json_schema()["$defs"]["PlanningSourceSelection"]["properties"]
    assert props["locator"]["enum"] == [row["slot"] for row in payload_catalog(ctx)]
    for ref in [SourceRef(label="Unseen", locator="source:2"),
                SourceRef(label="Mixed", locator="source:1", chunk_id="time-rule")]:
        with pytest.raises(ValidationError):
            schema.model_validate({"test_points": [point([ref]).model_dump()]})
    with pytest.raises(ValueError, match="^planning_source_reference_invalid$"):
        project_point_sources(PointPlan(test_points=[point([
            SourceRef.model_validate(context()["evidence"][1])
        ])]), ctx)


def test_point_empty_refs_fallback_uses_current_batch_not_feature_or_other_batches():
    ctx = context()
    ctx["evidence"] = ctx["evidence"][1:]
    output = project_point_sources(PointPlan(test_points=[point([])]), ctx)
    assert [ref.chunk_id for ref in output.test_points[0].source_refs] == ["time-rule"]
    user_only = project_point_sources(
        PointPlan(test_points=[point([])]), {"user_input": "Actual input"})
    ref = user_only.test_points[0].source_refs[0]
    assert ref.excerpt == "Actual input"
    assert (ref.source_id, ref.document_id, ref.chunk_id) == (None, None, None)


def test_hydrated_point_with_real_slot_prefixed_locator_roundtrips():
    ctx = context()
    ctx["evidence"][1]["locator"] = "source:real-time-rule"
    canonical = SourceRef.model_validate(ctx["evidence"][1])
    output = project_point_sources(PointPlan(test_points=[point([canonical])]), ctx)
    assert output.test_points[0].source_refs == [canonical]
    with pytest.raises(ValueError, match="planning_source_reference_invalid"):
        project_point_sources(PointPlan(test_points=[point([
            canonical.model_copy(update={"source_id": "foreign"})
        ])]), ctx)


def test_displayed_selection_retains_only_valid_shown_text_not_unseen_canonical_sources():
    canonical = context()
    original = deepcopy(canonical)
    shown = deepcopy(canonical)
    shown["evidence"] = [shown["evidence"][1]]
    shown["evidence"][0]["excerpt"] = "Approval expires"
    selected = PointPlan(test_points=[point([SourceRef(label="ignored", locator="source:1")])])
    output = project_point_sources(selected, shown, canonical_context=canonical)
    assert output.test_points[0].source_refs == [SourceRef.model_validate(shown["evidence"][0])]
    assert output.test_points[0].source_refs[0].excerpt == "Approval expires"
    assert canonical == original
    assert canonical["evidence"][1]["excerpt"] == "Approval expires at 30 seconds."
    # A physical identity present in original context but not displayed is not a
    # valid dependency. Canonical validation is not another source of authority.
    with pytest.raises(ValueError, match="planning_source_reference_invalid"):
        project_point_sources(PointPlan(test_points=[point([
            SourceRef.model_validate(canonical["evidence"][0])
        ])]), shown, canonical_context=canonical)
    wrong = deepcopy(canonical)
    wrong["evidence"][1]["source_id"] = "other-scope"
    with pytest.raises(ValueError, match="planning_source_reference_invalid"):
        project_point_sources(selected, shown, canonical_context=wrong)


def test_forged_displayed_snippet_cannot_borrow_a_real_canonical_identity():
    canonical = context()
    shown = deepcopy(canonical)
    shown["evidence"][1]["excerpt"] = "Administrators never expire"
    selected = PointPlan(test_points=[point([SourceRef(label="ignored", locator="source:2")])])
    with pytest.raises(ValueError, match="^planning_source_reference_invalid$"):
        project_point_sources(selected, shown, canonical_context=canonical)
