from copy import deepcopy

import pytest
from test_planning_sources import plan

from casepilot_agent.contracts import FeaturePlan, SourceRef
from casepilot_agent.planning_sources import (
    payload_catalog,
    project_feature_sources,
    source_selection_schema,
)


def test_rules_without_raw_user_have_no_empty_user_slot_and_fallback_is_actual_evidence():
    context = {"evidence": [dict(label="rule", locator="r1", excerpt="Explicit rule text")]}
    assert payload_catalog(context) == [dict(slot="source:0", **context["evidence"][0])]
    projected = project_feature_sources(plan([]), context)
    assert projected.feature_points[0].source_refs[0].excerpt == "Explicit rule text"
    with pytest.raises(ValueError, match="planning_source_reference_invalid"):
        project_feature_sources(plan([SourceRef(label="not user", locator="")]), context)


def test_actual_natural_language_input_without_attachment_is_retained():
    context = {"query": "Create cases for the explicitly specified account rule."}
    refs = project_feature_sources(plan([]), context).feature_points[0].source_refs
    assert len(refs) == 1 and refs[0].locator == "user_input"
    assert refs[0].excerpt == context["query"]


def test_no_source_never_promotes_summary_to_original_evidence():
    with pytest.raises(ValueError, match="planning_source_reference_invalid"):
        source_selection_schema(FeaturePlan, {"summary": "Model-derived statement"})


def test_projection_does_not_rewrite_preexisting_confirmed_snapshot():
    prior = plan([SourceRef(label="historic", locator="historic", excerpt="old text")])
    snapshot = deepcopy(prior.model_dump())
    with pytest.raises(ValueError, match="planning_source_reference_invalid"):
        project_feature_sources(prior, {"user_input": "new unrelated rule"})
    assert prior.model_dump() == snapshot
