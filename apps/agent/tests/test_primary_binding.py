"""A selected legal pair derives ownership; invalid secondary data stays invalid."""
from copy import deepcopy

import pytest

from casepilot_agent.contracts import FeaturePoint, SourceRef
from casepilot_agent.planning_sources import bind_primary_selection, primary_bindings


def fixture():
    ref = SourceRef(source_id="S", document_id="D", chunk_id="C", label="Rule",
                    locator="section", excerpt="Exact rule")
    features = [FeaturePoint(id="F", name="Feature", description="Rule", module="M",
                             requirement_refs=[], source_refs=[ref])]
    context = {"user_input": "Request", "evidence": [ref.model_dump()]}
    return features, context


def test_pairs_are_only_server_proven_and_currently_shown():
    features, context = fixture()
    assert primary_bindings(features, context) == [
        {"id": "primary:0", "feature_id": "F", "source_slot": "source:1"}]
    assert primary_bindings(features, {"user_input": "Request"}) == []
    context["evidence"][0]["source_id"] = "foreign"
    assert primary_bindings(features, context) == []


def test_known_pair_expands_once_without_mutating_input_or_secondary_dependencies():
    bindings = primary_bindings(*fixture())
    original = {"primary_binding": "primary:0", "primary_feature_id": None,
                "feature_point_ids": ["secondary", "F"],
                "source_refs": [{"label": "dependency", "locator": "source:0"}]}
    before = deepcopy(original)
    expanded = bind_primary_selection(original, bindings)
    assert expanded["primary_feature_id"] == "F"
    assert expanded["feature_point_ids"] == ["F", "secondary"]
    assert [ref["locator"] for ref in expanded["source_refs"]] == ["source:0", "source:1"]
    assert bind_primary_selection(expanded, bindings) == expanded
    assert original == before


def test_empty_secondary_sources_are_allowed_but_wrong_owner_is_not_repaired():
    bindings = primary_bindings(*fixture())
    result = bind_primary_selection({"primary_binding": "primary:0",
                                     "feature_point_ids": [], "source_refs": []}, bindings)
    assert result["feature_point_ids"] == ["F"]
    assert result["source_refs"][0]["locator"] == "source:1"
    with pytest.raises(ValueError, match="^planning_primary_binding_conflict$"):
        bind_primary_selection({"primary_binding": "primary:0", "primary_feature_id": "other"},
                               bindings)


@pytest.mark.parametrize("ref", [
    {"label": "forged", "locator": "source:1", "chunk_id": "C"},
    {"label": "foreign", "locator": "source:999", "source_id": "foreign"},
    "invalid-ref-shape",
])
def test_foreign_mixed_and_malformed_secondary_refs_are_not_hidden(ref):
    original = {"primary_binding": "primary:0", "feature_point_ids": ["F"], "source_refs": [ref]}
    expanded = bind_primary_selection(original, primary_bindings(*fixture()))
    assert expanded["source_refs"][0] == ref
    assert len(expanded["source_refs"]) == (1 if isinstance(ref, dict)
                                           and ref["locator"] == "source:1" else 2)


@pytest.mark.parametrize("bad", [None, "F", {"F": True}, 7])
def test_nonlist_owners_and_sources_are_not_silently_repaired(bad):
    expanded = bind_primary_selection({"primary_binding": "primary:0",
                                       "feature_point_ids": bad, "source_refs": bad},
                                      primary_bindings(*fixture()))
    assert expanded["feature_point_ids"] == bad
    assert expanded["source_refs"] == bad


def test_unknown_pair_and_nonmapping_input_are_unchanged_not_given_fallback():
    original = {"primary_binding": "primary:99", "feature_point_ids": []}
    assert bind_primary_selection(original, primary_bindings(*fixture())) == original
    assert bind_primary_selection(None, primary_bindings(*fixture())) is None
