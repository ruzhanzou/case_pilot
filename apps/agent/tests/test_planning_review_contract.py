from copy import deepcopy

import pytest
from pydantic import ValidationError

from casepilot_agent.planning_review import (
    Review,
    Revision,
    candidate_plan,
    snapshot,
    validate_review,
)


@pytest.fixture
def data():
    source = dict(
        label="Rule",
        locator="user_input",
        excerpt="A accepts x; B rejects y.",
        source_id=None,
        document_id=None,
        chunk_id=None,
    )
    plan = {
        "feature_points": [dict(id=x, source_refs=[source]) for x in ["A", "B"]],
        "test_points": [
            dict(
                id=x,
                title=x,
                scenario="original",
                objective="outcome",
                category="normal",
                priority="P1",
                priority_reason="test",
                feature_point_ids=["A"],
                primary_feature_id="A",
                source_refs=[source],
            )
            for x in ["p1", "p2"]
        ],
        "coverage_review": {
            "status": "pending_independent_review",
            "source": "model_proposed",
            "warnings": ["coverage_unverified"],
            "batches": [
                dict(
                    batch_index=1,
                    obligations=[
                        dict(
                            id="o1",
                            feature_point_ids=["A"],
                            dimension="normal",
                            basis="A accepts x;",
                            point_ids=["p1"],
                            clarification="",
                        ),
                        dict(
                            id="o2",
                            feature_point_ids=["A"],
                            dimension="state",
                            basis="related state",
                            point_ids=["p1"],
                            clarification="",
                        ),
                    ],
                    uncovered_ids=[],
                    clarifications=[],
                    warnings=["coverage_unverified"],
                    duplicate_suggestions=[],
                )
            ],
        },
    }
    return snapshot(plan)


def review():
    return Review.model_validate(
        {
            "findings": [
                dict(
                    id="issue-1",
                    kind="contradiction",
                    point_ids=["p1"],
                    obligation_keys=["1:o1"],
                    explanation="Proposed issue",
                    citations=[dict(source=0, quote="A accepts x;")],
                )
            ],
            "unresolved": ["Not independently certified"],
        }
    )


def revision():
    return Revision.model_validate(
        {
            "points": [
                dict(
                    point_id="p1",
                    action="upsert",
                    title="revised",
                    scenario="new scenario",
                    objective="new outcome",
                    feature_ids=["A"],
                    primary_feature_id="A",
                    sources=[0],
                    issue_ids=["issue-1"],
                )
            ],
            "obligations": [],
            "unresolved": ["Need review"],
        }
    )


def test_untouched_points_multi_obligations_and_warnings_preserved(data):
    original = deepcopy(data)
    result = candidate_plan(
        data, validate_review(review(), data), ["issue-1"], revision(), "synthetic"
    )
    assert data == original
    assert result["test_points"][1] == original["planning"]["test_points"][1]
    assert len(result["coverage_review"]["batches"][0]["obligations"]) == 2
    assert result["coverage_review"]["status"] == "pending_independent_review"
    assert "coverage_unverified" in result["coverage_review"]["warnings"]
    assert "Need review" in result["coverage_review"]["batches"][0]["clarifications"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("point_id", "p2"),
        ("feature_ids", ["foreign"]),
        ("primary_feature_id", "foreign"),
        ("sources", [999]),
        ("issue_ids", ["foreign"]),
    ],
)
def test_revision_scope_reference_rejected(data, field, value):
    r = revision()
    setattr(r.points[0], field, value)
    with pytest.raises(ValueError):
        candidate_plan(data, review(), ["issue-1"], r, "synthetic")


def test_model_cannot_approve_or_clear_warnings(data):
    for extra in ["approved", "status", "warnings", "coverage_review"]:
        value = revision().model_dump()
        value[extra] = True
        with pytest.raises(ValidationError):
            Revision.model_validate(value)
    r = revision()
    r.points[0].action = "delete"
    with pytest.raises(ValueError):
        candidate_plan(data, review(), ["issue-1"], r, "synthetic")


@pytest.mark.parametrize("field,value", [("point_ids", ["foreign"]), ("obligation_keys", ["2:o1"])])
def test_review_unknown_targets_rejected(data, field, value):
    r = review()
    setattr(r.findings[0], field, value)
    with pytest.raises(ValueError):
        validate_review(r, data)


def test_quote_must_be_exact_and_input_must_not_be_truncated(data):
    r = review()
    r.findings[0].citations[0].quote = "invented"
    with pytest.raises(ValueError):
        validate_review(r, data)
    data["planning"]["test_points"][0]["scenario"] = "x" * 180001
    with pytest.raises(ValueError):
        snapshot(data["planning"])


@pytest.mark.parametrize(
    "field,value,path",
    [
        ("point_ids", ["unknown"], ["findings", 0, "point_ids", 0]),
        ("obligation_keys", ["unknown"], ["findings", 0, "obligation_keys", 0]),
        ("source", 999, ["findings", 0, "citations", 0, "source"]),
        ("quote", "not in source", ["findings", 0, "citations", 0, "quote"]),
    ],
)
def test_exact_rejection_path_without_values(data, field, value, path):
    from casepilot_agent.planning_review_diagnostics import diagnostic

    r = review()
    setattr(
        r.findings[0].citations[0] if field in {"source", "quote"} else r.findings[0], field, value
    )
    with pytest.raises(ValueError) as caught:
        validate_review(r, data)
    evidence = diagnostic(caught.value, "reference_validation")
    assert evidence["errors"][0]["path"] == path
    assert evidence["errors"][0]["path_complete"]
    assert "not in source" not in str(evidence)


def test_schema_diagnostic_complete_known_path_redacts_unknown_key_and_input():
    from casepilot_agent.planning_review_diagnostics import diagnostic

    raw = review().model_dump()
    raw["findings"][0]["citations"][0]["source"] = "PRIVATE_VALUE"
    raw["PRIVATE_KEY"] = "PRIVATE_VALUE"
    with pytest.raises(ValidationError) as caught:
        Review.model_validate(raw)
    evidence = diagnostic(caught.value, "schema_validation")
    assert evidence["code"] == "planning_review_schema_invalid"
    assert evidence["errors"][0]["path"] == ["findings", 0, "citations", 0, "source"]
    assert evidence["errors"][0]["path_complete"]
    assert evidence["errors"][1]["path"] == ["unknown_field"]
    assert not evidence["errors"][1]["path_complete"]
    assert "PRIVATE" not in str(evidence)


def test_unknown_exception_and_broken_observer_never_expose_or_change_failure():
    from casepilot_agent.planning_review_diagnostics import diagnostic, notify, observe_failures

    error = TypeError("PRIVATE_SQL_OR_KEY")
    with observe_failures(lambda value: (_ for _ in ()).throw(ValueError("PRIVATE_CALLBACK"))):
        evidence = diagnostic(error, "result_serialization")
        notify(evidence)
    assert evidence["code"] == "planning_review_serialization_failed"
    assert evidence["exception_chain"] == ["TypeError"]
    assert "PRIVATE" not in str(evidence)


def test_observer_cannot_mutate_persisted_diagnostic():
    from casepilot_agent.planning_review_diagnostics import diagnostic, notify, observe_failures

    evidence = diagnostic(TypeError("private"), "result_serialization")
    original = deepcopy(evidence)

    def tamper(value):
        value["code"] = "PRIVATE"
        value["exception_chain"].append("PRIVATE")

    with observe_failures(tamper):
        notify(evidence)
    assert evidence == original


def test_scope_error_has_exact_field_and_joint_constraints_are_marked_incomplete(data):
    from casepilot_agent.planning_review_diagnostics import diagnostic

    r = revision()
    r.points[0].point_id = "p2"
    with pytest.raises(ValueError) as caught:
        candidate_plan(data, review(), ["issue-1"], r, "synthetic")
    evidence = diagnostic(caught.value, "revision_validation")
    assert evidence["code"] == "planning_revision_scope_invalid"
    assert evidence["errors"][0]["path"] == ["points", 0, "point_id"]
    assert evidence["errors"][0]["path_complete"]
    data["planning"]["feature_points"][0]["source_refs"] = []
    with pytest.raises(ValueError) as caught:
        candidate_plan(data, review(), ["issue-1"], revision(), "synthetic")
    evidence = diagnostic(caught.value, "revision_validation")
    assert evidence["code"] == "planning_revision_primary_source_invalid"
    assert not evidence["errors"][0]["path_complete"]


def selection(data):
    from casepilot_agent.planning_review import ReviewSelection, citation_catalog

    value = review().model_dump()
    value["findings"][0]["citations"] = [{"span_id": citation_catalog(data)[0]["span_id"]}]
    return ReviewSelection.model_validate(value)


def test_server_span_projection_preserves_exact_newlines_and_input(data):
    from casepilot_agent.planning_review import citation_catalog, project_review

    data["sources"][0]["excerpt"] = "A accepts x.\nB rejects y.\r\n"
    before = deepcopy(data)
    catalog = citation_catalog(data)
    choice = selection(data)
    choice.findings[0].citations.append(
        type(choice.findings[0].citations[0])(span_id=catalog[1]["span_id"])
    )
    result = project_review(choice, data)
    assert [c.quote for c in result.findings[0].citations] == ["A accepts x.\n", "B rejects y.\r\n"]
    assert data == before and citation_catalog(data) == catalog


def test_unknown_cross_source_and_stale_span_ids_rejected(data):
    from casepilot_agent.planning_review import project_review

    choice = selection(data)
    changed = deepcopy(data)
    changed["sources"][0]["label"] = "another source identity"
    with pytest.raises(ValueError, match="planning_review_span_invalid"):
        project_review(choice, changed)
    changed["sources"][0]["excerpt"] += "new version"
    with pytest.raises(ValueError, match="planning_review_span_invalid"):
        project_review(choice, changed)
    choice.findings[0].citations[0].span_id = "span-0000000000000000"
    with pytest.raises(ValueError, match="planning_review_span_invalid"):
        project_review(choice, data)


def test_model_cannot_supply_quote_or_source_offset(data):
    from casepilot_agent.planning_review import ReviewSelection

    for field, value in [("quote", "invented"), ("source", 0), ("start", 0), ("end", 5)]:
        raw = selection(data).model_dump()
        raw["findings"][0]["citations"][0][field] = value
        with pytest.raises(ValidationError):
            ReviewSelection.model_validate(raw)


def test_span_catalog_complete_chunks_and_coverage_semantics_do_not_edit_plan(data):
    from casepilot_agent.planning_review import citation_catalog, review_model_input

    data["sources"][0]["excerpt"] = "x" * 4001 + "\nlast\n"
    catalog = citation_catalog(data)
    assert "".join(c["quote"] for c in catalog) == data["sources"][0]["excerpt"]
    assert all(len(c["quote"]) <= 2000 for c in catalog)
    before = deepcopy(data)
    output = review_model_input({"snapshot": data})
    assert output["snapshot"] == before and data == before
    assert set(output["coverage_semantics"]) == {
        "point_ids",
        "uncovered_ids",
        "shared_points",
        "warnings",
    }
    output["snapshot"]["planning"].clear()
    assert data == before


def test_catalog_over_budget_rejects_without_truncation(data):
    from casepilot_agent.planning_review import review_model_input

    data["sources"][0]["excerpt"] = "x\n" * 10000
    with pytest.raises(ValueError, match="planning_review_input_limit"):
        review_model_input({"snapshot": data})
