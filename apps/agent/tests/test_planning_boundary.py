from copy import deepcopy

import pytest
from pydantic import ValidationError

from casepilot_agent.planning_boundary import (
    BoundaryContract,
    BoundarySample,
    point_boundary_markdown,
    project_boundary_metadata,
    validate_boundary_contracts,
)

RULE = "elapsed since issue must be less than 7 seconds"


def fixture():
    contract = dict(source_slot="source:0", source_literal=RULE, threshold=7.0,
                    unit="seconds", comparator="lt", axis="elapsed", time_origin="since issue",
                    sampling_step=0.5, sampling_literal="sample every 0.5 seconds")
    obligation = dict(id="o", feature_point_ids=["f"], dimension="boundary",
                      point_ids=["p"], boundary_contract=contract)
    samples = [dict(obligation_id="o", position=position, value=value,
                    initial_state="not locked", assertion="observe supplied rule",
                    assertion_role="primary", assertion_feature_id="f",
                    assertion_source_slot="source:0")
               for position, value in [("before", 6.5), ("at", 7.0), ("after", 7.5)]]
    point = dict(id="p", primary_feature_id="f", feature_point_ids=["f"],
                 scenario="original scenario", boundary_samples=samples)
    context = dict(user_input=RULE, test_setup="Use fixtures: sample every 0.5 seconds.")
    return [obligation], [point], context, {"f": ["source:0"]}


def test_complete_authorized_coordinates_are_checked_without_mutation():
    args = fixture()
    before = deepcopy(args)
    assert validate_boundary_contracts(*args) == set()
    assert args == before


@pytest.mark.parametrize("field,value,code", [
    ("source_slot", "source:99", "source_invalid"),
    ("source_literal", "invented < 7 seconds", "literal_invalid"),
    ("threshold", 17.0, "threshold_invalid"),
    ("unit", "minutes", "unit_invalid"),
    ("axis", "retries", "axis_invalid"),
    ("time_origin", "since last failure", "time_origin_invalid"),
    ("sampling_step", 1.0, "sampling_invalid"),
    ("sampling_literal", "unprovided 0.5 seconds", "sampling_invalid"),
])
def test_fabricated_contract_fields_rejected(field, value, code):
    args = fixture()
    args[0][0]["boundary_contract"][field] = value
    with pytest.raises(ValueError, match=f"planning_boundary_{code}"):
        validate_boundary_contracts(*args)


def test_sampling_evidence_cannot_be_taken_from_requirement_text():
    obligations, points, context, slots = fixture()
    context["user_input"] += "; sample every 0.5 seconds"
    context.pop("test_setup")
    with pytest.raises(ValueError, match="sampling_invalid"):
        validate_boundary_contracts(obligations, points, context, slots)


@pytest.mark.parametrize("field,value", [("sampling_step", None), ("sampling_literal", "")])
def test_missing_sampling_authority_stays_incomplete_not_guessed(field, value):
    args = fixture()
    args[0][0]["boundary_contract"][field] = value
    args[1][0]["boundary_samples"] = [args[1][0]["boundary_samples"][1]]
    assert validate_boundary_contracts(*args) == {"o"}


def test_missing_samples_cannot_claim_completion():
    args = fixture()
    args[1][0]["boundary_samples"] = args[1][0]["boundary_samples"][:2]
    assert validate_boundary_contracts(*args) == {"o"}


@pytest.mark.parametrize("field,value,code", [
    ("value", 6.0, "coordinate_invalid"),
    ("obligation_id", "foreign", "sample_link_invalid"),
    ("assertion_feature_id", "foreign", "assertion_owner_invalid"),
    ("assertion_source_slot", "source:99", "assertion_owner_invalid"),
    ("assertion_role", "secondary", "assertion_owner_invalid"),
])
def test_fabricated_or_unlinked_samples_rejected(field, value, code):
    args = fixture()
    args[1][0]["boundary_samples"][0][field] = value
    with pytest.raises(ValueError, match=f"planning_boundary_{code}"):
        validate_boundary_contracts(*args)


def test_sample_requires_actual_obligation_point_link():
    args = fixture()
    args[0][0]["point_ids"] = []
    with pytest.raises(ValueError, match="sample_link_invalid"):
        validate_boundary_contracts(*args)


def test_secondary_assertion_uses_its_own_legal_feature_source():
    obligations, points, context, slots = fixture()
    points[0]["feature_point_ids"].append("dependent")
    slots["dependent"] = ["source:0"]
    sample = points[0]["boundary_samples"][0]
    sample.update(assertion_role="secondary", assertion_feature_id="dependent")
    assert validate_boundary_contracts(obligations, points, context, slots) == set()


def test_decimal_coordinates_do_not_use_binary_float_addition():
    obligations, points, context, slots = fixture()
    contract = obligations[0]["boundary_contract"]
    rule = "elapsed since issue less than 0.3 seconds"
    contract.update(source_literal=rule, threshold=0.3, sampling_step=0.1,
                    sampling_literal="every 0.1 seconds")
    context.update(user_input=rule, test_setup=["every 0.1 seconds"])
    for sample, value in zip(points[0]["boundary_samples"], [0.2, 0.3, 0.4], strict=True):
        sample["value"] = value
    assert validate_boundary_contracts(obligations, points, context, slots) == set()


@pytest.mark.parametrize("field,value", [("threshold", float("inf")), ("threshold", "7"),
                                         ("sampling_step", 0.0), ("unit", " "),
                                         ("extra", "untrusted")])
def test_contract_is_strict_finite_and_forbids_extra(field, value):
    contract = fixture()[0][0]["boundary_contract"]
    contract[field] = value
    with pytest.raises(ValidationError):
        BoundaryContract.model_validate(contract)


@pytest.mark.parametrize("field,value", [("value", float("nan")), ("initial_state", " "),
                                         ("assertion", ""), ("extra", "untrusted")])
def test_sample_is_strict_and_requires_explicit_state_assertion(field, value):
    sample = fixture()[1][0]["boundary_samples"][0]
    sample[field] = value
    with pytest.raises(ValidationError):
        BoundarySample.model_validate(sample)


def test_legacy_absent_fields_are_unchanged_and_markdown_empty():
    assert not validate_boundary_contracts(
        [dict(id="legacy", dimension="boundary")], [], {}, {}
    )
    assert point_boundary_markdown({"scenario": "legacy"}) == ""


def test_projection_replaces_model_canonical_fields_and_removes_persisted_slots():
    obligations, points, context, _ = fixture()
    plan = dict(coverage_obligations=obligations, test_points=points)
    before = deepcopy(plan)
    projected = project_boundary_metadata(plan, context)
    contract = projected["coverage_obligations"][0]["boundary_contract"]
    assert "source_slot" not in contract
    assert contract["source_ref"]["excerpt"] == RULE
    sample = projected["test_points"][0]["boundary_samples"][0]
    assert "assertion_source_slot" not in sample
    assert sample["assertion_source_ref"]["excerpt"] == RULE
    assert (sample["unit"], sample["axis"], sample["time_origin"]) == (
        "seconds", "elapsed", "since issue")
    BoundaryContract.model_validate(contract)
    BoundarySample.model_validate(sample)
    assert plan == before
    markdown = point_boundary_markdown(projected["test_points"][0])
    assert "before = 6.5" in markdown and "not locked" in markdown
    assert "observe supplied rule" in markdown
    assert projected["test_points"][0]["scenario"] == "original scenario"


def test_canonical_ref_cannot_bypass_unknown_slot_on_projection():
    obligations, points, context, _ = fixture()
    obligations[0]["boundary_contract"].update(
        source_slot="source:99", source_ref=dict(label="forged", excerpt="forged"))
    with pytest.raises(ValueError, match="source_invalid"):
        project_boundary_metadata(
            dict(coverage_obligations=obligations, test_points=points), context
        )


def test_missing_step_does_not_authorize_fabricated_nonempty_sampling_literal():
    args = fixture()
    args[0][0]["boundary_contract"].update(
        sampling_step=None, sampling_literal="invented 1 seconds"
    )
    with pytest.raises(ValueError, match="sampling_invalid"):
        validate_boundary_contracts(*args)


def test_threshold_token_supports_chinese_adjacent_text_without_subnumber_matching():
    obligations, points, context, slots = fixture()
    text = "从发送起经过时间小于7秒"
    obligations[0]["boundary_contract"].update(
        source_literal=text, axis="经过时间", unit="秒", time_origin="从发送起",
        sampling_literal="每0.5秒取样"
    )
    context.update(user_input=text, test_setup="每0.5秒取样")
    assert not validate_boundary_contracts(obligations, points, context, slots)


@pytest.mark.parametrize("literal,unit,rule", [
    ("使用可控时钟按整数秒采样", "秒", "从发送起经过时间小于7秒"),
    ("Sample at integer seconds using a controlled clock", "seconds", RULE),
])
def test_explicit_integer_unit_test_setup_authorizes_one_unit_only(literal, unit, rule):
    obligations, points, context, slots = fixture()
    contract = obligations[0]["boundary_contract"]
    contract.update(source_literal=rule, unit=unit, sampling_step=1.0, sampling_literal=literal)
    if unit == "秒":
        contract.update(axis="经过时间", time_origin="从发送起")
    context.update(user_input=rule, test_setup=literal)
    for sample, value in zip(points[0]["boundary_samples"], [6.0, 7.0, 8.0], strict=True):
        sample["value"] = value
    assert not validate_boundary_contracts(obligations, points, context, slots)
    contract["sampling_step"] = 2.0
    with pytest.raises(ValueError, match="sampling_invalid"):
        validate_boundary_contracts(obligations, points, context, slots)
    contract["sampling_step"] = 1.0
    context["test_setup"] = "integer minutes" if unit == "seconds" else "整数分钟"
    contract["sampling_literal"] = context["test_setup"]
    with pytest.raises(ValueError, match="sampling_invalid"):
        validate_boundary_contracts(obligations, points, context, slots)
    context["user_input"] += literal
    context["test_setup"] = ""
    contract["sampling_literal"] = literal
    with pytest.raises(ValueError, match="sampling_invalid"):
        validate_boundary_contracts(obligations, points, context, slots)


@pytest.mark.parametrize("samples", ["absent", None, []])
def test_legacy_projection_preserves_absent_none_or_empty_samples(samples):
    point = dict(id="legacy", scenario="unchanged", feature_point_ids=["f"])
    if samples != "absent":
        point["boundary_samples"] = samples
    plan = dict(test_points=[point], coverage_obligations=[])
    assert project_boundary_metadata(plan, {}) == plan
    assert point_boundary_markdown(point) == ""
    assert not validate_boundary_contracts([], [point], {}, {})


def test_only_validated_temporary_assertion_binding_is_removed_before_persistence():
    obligations, points, context, slots = fixture()
    points[0]["boundary_samples"][0]["assertion_binding"] = "server-pair"
    assert not validate_boundary_contracts(obligations, points, context, slots)
    projected = project_boundary_metadata(
        dict(coverage_obligations=obligations, test_points=points), context
    )
    assert "assertion_binding" not in projected["test_points"][0]["boundary_samples"][0]
    points[0]["boundary_samples"][0]["untrusted_extra"] = "must reject"
    with pytest.raises(ValidationError):
        validate_boundary_contracts(obligations, points, context, slots)


@pytest.mark.parametrize("value,exact", [(1234567.0, "1234567.0"), (59.999999, "59.999999")])
def test_boundary_markdown_does_not_round_explicit_coordinate(value, exact):
    sample = fixture()[1][0]["boundary_samples"][0]
    sample["value"] = value
    markdown = point_boundary_markdown({"boundary_samples": [sample]})
    assert f"before = {exact} " in markdown


def test_quantities_cannot_be_cross_bound_between_axes():
    args = fixture()
    rule = "elapsed seconds since issuance < 7 seconds; failure_count >= 3 attempts."
    args[2]["user_input"] = rule
    contract = args[0][0]["boundary_contract"]
    contract.update(source_literal=rule, time_origin="issuance")
    assert validate_boundary_contracts(*args) == set()
    contract["threshold"] = 3
    with pytest.raises(ValueError, match="relation_invalid"):
        validate_boundary_contracts(*args)


def test_count_axis_cannot_borrow_integer_second_sampling():
    args = fixture()
    rule = "failure_count >= 3 attempts"
    args[2].update(user_input=rule, test_setup="Sample at integer seconds")
    args[0][0]["boundary_contract"].update(
        source_literal=rule, threshold=3, unit="attempts", axis="failure_count",
        time_origin="not_applicable", comparator="gte", sampling_step=1,
        sampling_literal="Sample at integer seconds")
    with pytest.raises(ValueError, match="sampling_invalid"):
        validate_boundary_contracts(*args)


def test_evidence_selectors_bind_separate_quantities_and_do_not_infer_range_unit():
    from casepilot_agent.planning_boundary import boundary_evidence_bindings

    bindings = boundary_evidence_bindings({
        "user_input": "elapsed < 7 seconds; failure_count >= 3 attempts; 0≤t<120秒"
    })
    assert [item["threshold"] for item in bindings] == [7, 3]
    assert all(item["source_slot"] == "source:0" for item in bindings)
    assert boundary_evidence_bindings({
        "user_input": "elapsed 7 seconds and count 3 attempts"
    }) == []


@pytest.mark.parametrize("separator", [",", " and "])
def test_bare_other_axis_number_cannot_supply_axis_for_quantity(separator):
    args = fixture()
    rule = f"elapsed since issuance < 7 seconds{separator} failure_count >= 3"
    args[2]["user_input"] = rule
    args[0][0]["boundary_contract"].update(
        source_literal=rule, time_origin="issuance", axis="failure_count")
    with pytest.raises(ValueError, match="relation_invalid"):
        validate_boundary_contracts(*args)


@pytest.mark.parametrize("field,value", [("sampling_step", None), ("sampling_literal", "")])
def test_no_sampling_authority_cannot_preserve_before_after_hard_coordinates(field, value):
    args = fixture()
    args[0][0]["boundary_contract"][field] = value
    with pytest.raises(ValueError, match="planning_boundary_coordinate_invalid"):
        validate_boundary_contracts(*args)


@pytest.mark.parametrize("quantity", ["1e999", "1e-999", "9007199254740993"])
def test_evidence_selector_does_not_round_or_overflow_exact_source_quantity(quantity):
    from casepilot_agent.planning_boundary import boundary_evidence_bindings

    assert boundary_evidence_bindings({"user_input": f"elapsed < {quantity} seconds"}) == []
