"""Planning selection IDs/text never become authority without server projection."""
import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from casepilot_agent.contracts import FeaturePlan, FeaturePoint, SourceRef
from casepilot_agent.planning import PlanningAnalysis
from casepilot_agent.planning_sources import (
    payload_catalog,
    project_feature_sources,
    source_catalog,
    source_selection_schema,
)


def context():
    return {"user_input": "OTP expires at 120 seconds", "evidence": [{
        "source_id": "source-a", "document_id": "document-a", "chunk_id": "chunk-a",
        "label": "Verified document", "locator": "page 1", "excerpt": "Exact authorized rule",
    }]}


def plan(refs):
    return FeaturePlan(feature_points=[FeaturePoint(
        id="F", name="OTP", description="Rule", module="Account", requirement_refs=["OTP-1"],
        source_refs=refs,
    )])


def test_dynamic_schema_restricts_slots_and_null_identity_without_changing_global_ref():
    schema = source_selection_schema(FeaturePlan, context())
    value = schema.model_json_schema()["$defs"]["PlanningSourceSelection"]["properties"]
    assert value["locator"]["enum"] == ["source:0", "source:1"]
    assert all(value[key]["type"] == "null" for key in ("source_id", "document_id", "chunk_id"))
    assert SourceRef(label="Existing", chunk_id="still-supported").chunk_id == "still-supported"
    data = plan([SourceRef(label="Ignored", locator="source:1")]).model_dump()
    selected = schema.model_validate(data)
    projected = project_feature_sources(selected, context())
    assert type(projected) is FeaturePlan
    assert projected.feature_points[0].source_refs[0].model_dump() == context()["evidence"][0]
    data["feature_points"][0]["source_refs"][0]["chunk_id"] = "chunk-a"
    with pytest.raises(ValidationError):
        schema.model_validate(data)


@pytest.mark.parametrize("ref", [
    SourceRef(label="Foreign", locator="source:999"),
    SourceRef(label="Invented no-ID document", locator="private-file:5"),
    SourceRef(label="Foreign", source_id="source-b", document_id="document-b", chunk_id="chunk-b"),
    SourceRef(label="Mixed", source_id="source-b", document_id="document-a", chunk_id="chunk-a"),
    SourceRef(label="Partial", chunk_id="chunk-a"),
    SourceRef(label="Slot with forged IDs", locator="source:1", chunk_id="chunk-a"),
])
def test_unknown_cross_scope_partial_and_mixed_identities_are_rejected(ref):
    with pytest.raises(ValueError, match="^planning_source_reference_invalid$"):
        project_feature_sources(plan([ref]), context())


def test_exact_cached_identity_is_rehydrated_not_trusted_for_label_or_excerpt():
    ref = SourceRef(**{**context()["evidence"][0], "label": "Forged", "excerpt": "Injected text"})
    original = plan([ref])
    projected = project_feature_sources(original, context())
    assert projected.feature_points[0].source_refs[0].model_dump() == context()["evidence"][0]
    assert original.feature_points[0].source_refs[0].excerpt == "Injected text"


def test_no_attachment_user_input_has_no_invented_ids_and_drops_model_prose():
    ctx = {"user_input": "The actual original request"}
    output = project_feature_sources(
        plan([SourceRef(label="Fake document", excerpt="made-up rule")]), ctx
    )
    ref = output.feature_points[0].source_refs[0]
    assert (ref.source_id, ref.document_id, ref.chunk_id) == (None, None, None)
    assert ref.label == "用户输入" and ref.excerpt == ctx["user_input"]
    with pytest.raises(ValueError, match="planning_source_reference_invalid"):
        project_feature_sources(plan([SourceRef(label="User", source_id="user-input")]), ctx)


def test_authorized_history_is_reference_only_and_original_snapshot_is_immutable():
    source = {"key": "asset:a", "revision": "r1", "label": "History",
              "document_id": "old-doc",
              "snapshot": {"title": "Original",
                           "steps": [{"action": "Act", "expected": "Observe"}]}}
    ctx = {"user_input": "Reuse original", "planning_authorized_sources": [source]}
    before = deepcopy(ctx)
    output = project_feature_sources(plan([SourceRef(label="ignored", locator="source:1")]), ctx)
    ref = output.feature_points[0].source_refs[0]
    assert not any((ref.source_id, ref.document_id, ref.chunk_id))
    assert json.loads(ref.excerpt)["action"] == "reference"
    assert json.loads(ref.excerpt)["snapshot"] == source["snapshot"]
    assert ctx == before
    assert set(payload_catalog(ctx)[1]) == {"slot", "label", "locator", "excerpt"}


def test_preloaded_planning_analysis_uses_same_projection_without_losing_revision_contract():
    analysis = PlanningAnalysis(summary="OTP", feature_points=plan([
        SourceRef(label="model text", locator="source:1")]).feature_points,
        planning_update_mode="merge", superseded_test_point_ids=["old-point"])
    output = project_feature_sources(analysis, context())
    assert isinstance(output, PlanningAnalysis)
    assert output.superseded_test_point_ids == ["old-point"]
    assert output.feature_points[0].source_refs[0].excerpt == "Exact authorized rule"


def test_empty_selection_only_hydrates_current_batch_not_other_available_documents():
    ctx = context()
    original = source_catalog(ctx)
    output = project_feature_sources(plan([]), ctx)
    assert output.feature_points[0].source_refs == original[1:]
    assert source_catalog({"query": "Original fallback"})[0].excerpt == "Original fallback"


def test_exact_server_ref_with_slot_like_locator_roundtrips_without_alias_confusion():
    batch = context()
    batch["evidence"][0]["locator"] = "source:document-section"
    canonical = SourceRef.model_validate(batch["evidence"][0])
    result = project_feature_sources(plan([canonical]), batch)
    assert result.feature_points[0].source_refs == [canonical]
    mixed = canonical.model_copy(update={"source_id": "foreign"})
    with pytest.raises(ValueError, match="planning_source_reference_invalid"):
        project_feature_sources(plan([mixed]), batch)
