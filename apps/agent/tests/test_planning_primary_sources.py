"""Primary ownership is explicit; source intersection is not a semantic oracle."""
from copy import deepcopy
from typing import Literal

import pytest
from pydantic import create_model

from casepilot_agent.contracts import FeaturePoint, SourceRef
from casepilot_agent.contracts import TestPoint as Point
from casepilot_agent.contracts import TestPointPlan as Plan
from casepilot_agent.planning_sources import (
    feature_source_slots,
    project_point_sources,
    validate_primary_sources,
)


def setup():
    refs = [SourceRef(source_id="S", document_id="D", chunk_id=key,
                      label=key, locator=key, excerpt=text)
            for key, text in [("time", "Expires at 30 seconds"), ("role", "Only owners approve")]]
    context = {"user_input": "Verify rules", "evidence": [ref.model_dump() for ref in refs]}
    features = [FeaturePoint(id=key, name=key, description=key, module="M",
                             requirement_refs=[key], source_refs=[ref])
                for key, ref in zip(("F-time", "F-role"), refs, strict=True)]
    return context, features


def plan(primary="F-time", owners=None, refs=None, *, dynamic=True):
    point_type = create_model("OwnedPoint", __base__=Point,
                              primary_feature_id=(Literal["F-time", "F-role"], ...))
    plan_type = create_model("OwnedPlan", __base__=Plan, test_points=(list[point_type], ...))
    item = dict(id="P", title="Time boundary", objective="Verify", category="boundary",
                priority="P1", priority_reason="Explicit", feature_point_ids=owners or ["F-time"],
                source_refs=refs if refs is not None else [
                    SourceRef(label="ignored", locator="source:1")])
    if dynamic:
        item["primary_feature_id"] = primary
    return (plan_type if dynamic else Plan).model_validate({"test_points": [item]})


def test_primary_owner_must_be_linked_and_cite_its_actual_source():
    context, features = setup()
    with pytest.raises(ValueError, match="planning_primary_feature_invalid"):
        validate_primary_sources(plan(primary="F-role"), features, context)
    with pytest.raises(ValueError, match="^planning_primary_source_missing$"):
        validate_primary_sources(plan(primary="F-role", owners=["F-time", "F-role"]),
                                 features, context)
    with pytest.raises(ValueError, match="^planning_point_sources_required$"):
        validate_primary_sources(plan(refs=[]), features, context)


def test_cross_rule_dependency_allowed_and_primary_reorders_only_copied_output():
    context, features = setup()
    original = plan(primary="F-role", owners=["F-time", "F-role"], refs=[
        SourceRef(label="ignored", locator="source:1"),
        SourceRef(label="ignored", locator="source:2"),
    ])
    before = original.model_dump()
    assert validate_primary_sources(original, features, context) is None
    projected = project_point_sources(original, context)
    assert projected.test_points[0].feature_point_ids == ["F-role", "F-time"]
    assert original.model_dump() == before
    assert projected.test_points[0].primary_feature_id == "F-role"
    assert [ref.chunk_id for ref in projected.test_points[0].source_refs] == ["time", "role"]


def test_hidden_or_mixed_source_does_not_pass_because_one_valid_citation_exists():
    context, features = setup()
    for ref in [SourceRef(label="unseen", locator="source:99"),
                SourceRef(source_id="foreign", document_id="D", chunk_id="time", label="mixed")]:
        with pytest.raises(ValueError, match="^planning_source_reference_invalid$"):
            validate_primary_sources(plan(refs=[SourceRef(label="ok", locator="source:1"), ref]),
                                     features, context)


def test_compact_physical_source_matches_primary_but_no_id_sources_need_actual_provenance():
    context, features = setup()
    context["evidence"][0]["excerpt"] = "Expires"
    validate_primary_sources(plan(), features, context)
    # A shared whole user input permits attribution, but deliberately does not
    # claim semantic correctness of a fabricated scenario within that document.
    user_ref = SourceRef(label="用户输入", locator="user_input", excerpt="Verify rules")
    features[0].source_refs = [user_ref]
    candidate = plan(refs=[SourceRef(label="ignored", locator="source:0")])
    candidate.test_points[0].title = "Invented policy cannot be certified by this helper"
    validate_primary_sources(candidate, features, context)
    features[0].source_refs = [user_ref.model_copy(update={"excerpt": "Different authority"})]
    with pytest.raises(ValueError, match="^planning_primary_source_missing$"):
        validate_primary_sources(candidate, features, context)


def test_legacy_projection_does_not_reorder_or_mutate_confirmed_base_plan():
    context, _ = setup()
    original = plan(owners=["F-role", "F-time"], dynamic=False)
    before = deepcopy(original.model_dump())
    projected = project_point_sources(original, context)
    assert projected.test_points[0].feature_point_ids == ["F-role", "F-time"]
    assert original.model_dump() == before



def test_feature_slot_mapping_uses_same_provenance_and_only_displayed_catalog():
    context, features = setup()
    assert feature_source_slots(features, context) == {
        "F-time": ["source:1"], "F-role": ["source:2"]}
    context["evidence"] = context["evidence"][:1]
    context["evidence"][0]["excerpt"] = "Expires"
    assert feature_source_slots(features, context) == {"F-time": ["source:1"], "F-role": []}
    features[0].source_refs[0].source_id = "foreign"
    assert feature_source_slots(features, context)["F-time"] == []
