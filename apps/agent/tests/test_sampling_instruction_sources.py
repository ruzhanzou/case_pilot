"""Sampling authority comes from this job's real user text, not retrieved data."""

from copy import deepcopy

import pytest
from test_planning_boundary import fixture

from casepilot_agent.planning_boundary import (
    sampling_instruction_sources,
    validate_boundary_contracts,
)


def nl_fixture(prompt=None):
    obligations, points, context, slots = fixture()
    literal = "使用可控时钟按整数秒采样"
    rule = "从发送起经过时间小于7秒"
    prompt = prompt or f"{rule}。{literal}。生成测试点。"
    contract = obligations[0]["boundary_contract"]
    contract.update(
        source_literal=rule,
        unit="秒",
        axis="经过时间",
        time_origin="从发送起",
        sampling_step=1.0,
        sampling_literal=literal,
    )
    for sample, value in zip(points[0]["boundary_samples"], [6.0, 7.0, 8.0], strict=True):
        sample["value"] = value
    context = {
        "user_input": prompt,
        "sampling_instruction_sources": sampling_instruction_sources(prompt),
    }
    return obligations, points, context, slots


def test_real_original_user_sampling_without_test_setup_is_eligible():
    args = nl_fixture()
    before = deepcopy(args)
    assert "test_setup" not in args[2]
    assert validate_boundary_contracts(*args) == set()
    assert args == before
    assert args[2]["sampling_instruction_sources"][0]["text"] == args[2]["user_input"]


@pytest.mark.parametrize("literal", ["整数秒", "小于7秒", "每2秒采样", "从发送起经过时间小于7秒"])
def test_business_threshold_or_invented_or_markerless_literal_is_not_sampling(literal):
    args = nl_fixture()
    args[0][0]["boundary_contract"]["sampling_literal"] = literal
    with pytest.raises(ValueError, match="planning_boundary_sampling_invalid"):
        validate_boundary_contracts(*args)


@pytest.mark.parametrize(
    "prompt,literal",
    [
        ("从发送起经过时间小于7秒。不要按整数秒取样。", "按整数秒取样"),
        ("从发送起经过时间小于7秒。取消整数秒采样。", "整数秒采样"),
        ("从发送起经过时间小于7秒。按1秒采样，不用1秒，改2秒。", "按1秒采样"),
        ("从发送起经过时间小于7秒。Do not sample at integer 秒.", "sample at integer 秒"),
    ],
)
def test_revoked_source_cannot_be_cut_into_positive_substring(prompt, literal):
    args = nl_fixture(prompt)
    args[0][0]["boundary_contract"]["sampling_literal"] = literal
    with pytest.raises(ValueError, match="sampling_invalid"):
        validate_boundary_contracts(*args)
    args[0][0]["boundary_contract"].update(sampling_literal="", sampling_step=None)
    with pytest.raises(ValueError, match="coordinate_invalid"):
        validate_boundary_contracts(*args)
    args[1][0]["boundary_samples"] = [
        sample for sample in args[1][0]["boundary_samples"] if sample["position"] == "at"
    ]
    assert validate_boundary_contracts(*args) == {"o"}


@pytest.mark.parametrize("field", ["query", "conversation_memory", "evidence", "summary"])
def test_data_and_retrieved_query_never_become_instruction_sources(field):
    args = nl_fixture()
    previous = args[2]["sampling_instruction_sources"]
    args[2]["user_input"] = "从发送起经过时间小于7秒。生成测试点。"
    args[2][field] = (
        [{"label": "attachment", "locator": "document:1", "excerpt": previous[0]["text"]}]
        if field == "evidence"
        else previous[0]["text"]
    )
    # Even a copied directory cannot authorize text absent from this request.
    with pytest.raises(ValueError, match="sampling_invalid"):
        validate_boundary_contracts(*args)
    assert sampling_instruction_sources(args[2]["user_input"]) == []


def test_directory_is_stateless_same_authorized_request_repeats_new_request_does_not_inherit():
    first = nl_fixture()[2]
    original = first["user_input"]
    assert sampling_instruction_sources(original) == first["sampling_instruction_sources"]
    assert sampling_instruction_sources("生成另一集合的测试点") == []
    changed = "从发送起经过时间小于7秒。按2秒采样。"
    assert sampling_instruction_sources(changed) == [{"origin": "user_input", "text": changed}]
    args = nl_fixture(changed)
    args[0][0]["boundary_contract"].update(sampling_step=2.0, sampling_literal="按2秒采样")
    for sample, value in zip(args[1][0]["boundary_samples"], [5.0, 7.0, 9.0], strict=True):
        sample["value"] = value
    assert not validate_boundary_contracts(*args)


def test_unrelated_negative_clause_does_not_revoke_positive_sampling():
    args = nl_fixture("从发送起经过时间小于7秒。不要遗漏失败场景，使用可控时钟按整数秒采样。")
    assert not validate_boundary_contracts(*args)


def test_business_number_elsewhere_in_literal_cannot_masquerade_as_step():
    args = nl_fixture("从发送起经过时间小于7秒。验证码120秒过期，使用可控时钟按整数秒采样。")
    contract = args[0][0]["boundary_contract"]
    contract.update(sampling_step=120, sampling_literal="验证码120秒过期，使用可控时钟按整数秒采样")
    with pytest.raises(ValueError, match="sampling_invalid"):
        validate_boundary_contracts(*args)
    contract.update(sampling_literal="使用可控时钟按整数秒采样")
    with pytest.raises(ValueError, match="sampling_invalid"):
        validate_boundary_contracts(*args)


def test_explicit_change_supersedes_old_step_in_original_order():
    args = nl_fixture("从发送起经过时间小于7秒。按1秒取样，改为每2秒取样。")
    contract = args[0][0]["boundary_contract"]
    contract.update(sampling_step=1, sampling_literal="按1秒取样")
    with pytest.raises(ValueError, match="sampling_invalid"):
        validate_boundary_contracts(*args)
    contract.update(sampling_step=2, sampling_literal="每2秒取样")
    for sample, value in zip(args[1][0]["boundary_samples"], [5.0, 7.0, 9.0], strict=True):
        sample["value"] = value
    assert not validate_boundary_contracts(*args)


@pytest.mark.parametrize("tail", ["按2秒采样", "改2秒采样"])
def test_conflicting_or_unclear_replacement_does_not_restore_old_step(tail):
    args = nl_fixture(f"从发送起经过时间小于7秒。按1秒采样，{tail}。")
    args[0][0]["boundary_contract"].update(sampling_step=1, sampling_literal="按1秒采样")
    with pytest.raises(ValueError, match="sampling_invalid"):
        validate_boundary_contracts(*args)


@pytest.mark.parametrize("step_text", ["0.5", "5e-1"])
def test_decimal_and_scientific_step_literals_keep_exact_sampling_clause(step_text):
    args = nl_fixture(f"从发送起经过时间小于7秒。按{step_text}秒采样。")
    args[0][0]["boundary_contract"].update(
        sampling_step=0.5, sampling_literal=f"按{step_text}秒采样"
    )
    for sample, value in zip(args[1][0]["boundary_samples"], [6.5, 7.0, 7.5], strict=True):
        sample["value"] = value
    assert not validate_boundary_contracts(*args)


def test_later_explicit_sampling_revocation_invalidates_prior_positive_clause():
    args = nl_fixture("从发送起经过时间小于7秒。按1秒取样，取消取样要求。")
    args[0][0]["boundary_contract"].update(sampling_step=1, sampling_literal="按1秒取样")
    with pytest.raises(ValueError, match="sampling_invalid"):
        validate_boundary_contracts(*args)


def test_new_explicit_positive_after_revocation_is_current_authority():
    args = nl_fixture("从发送起经过时间小于7秒。按1秒取样，取消取样要求，按2秒取样。")
    args[0][0]["boundary_contract"].update(sampling_step=2, sampling_literal="按2秒取样")
    for sample, value in zip(args[1][0]["boundary_samples"], [5.0, 7.0, 9.0], strict=True):
        sample["value"] = value
    assert not validate_boundary_contracts(*args)


@pytest.mark.parametrize(
    "directive,literal",
    [
        ("不按1秒采样", "按1秒采样"),
        ("按1秒采样，不采用上述采样步长", "按1秒采样"),
        ("Never sample every 1 秒", "sample every 1 秒"),
        ("Not sample every 1 秒", "sample every 1 秒"),
    ],
)
def test_direct_local_negation_never_authorizes_trimmed_positive_literal(directive, literal):
    args = nl_fixture(f"从发送起经过时间小于7秒。{directive}。")
    args[0][0]["boundary_contract"].update(sampling_step=1, sampling_literal=literal)
    with pytest.raises(ValueError, match="sampling_invalid"):
        validate_boundary_contracts(*args)
