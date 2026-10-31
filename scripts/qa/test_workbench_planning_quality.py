from copy import deepcopy

import pytest
from workbench_planning_quality import (
    REQUIRED,
    RULES,
    SOURCE,
    Attempt,
    Scenario,
    adapt_artifact,
    evaluate,
    execute,
)


def scenario(name, attempts, refs=None):
    refs = refs or list(RULES)
    return Scenario(name, refs, {key: RULES[key] for key in refs}, attempts, "fixture")


def complete_gaps():
    return [
        scenario("valid119", [Attempt(119, 0, "correct", "accepted", 0, None)]),
        scenario("expired120", [Attempt(120, 0, "correct", "expired", 0, None)]),
        scenario("expired121", [Attempt(121, 0, "correct", "expired", 0, None)]),
        scenario("lock", [
            *[Attempt(i, 0, "wrong", "wrong", i + 1, 604 if i == 4 else None)
              for i in range(5)],
            Attempt(603, 603, "correct", "locked", 5, 604),
            Attempt(604, 604, "correct", "accepted", 0, None),
        ]),
        scenario("reset", [
            Attempt(0, 0, "wrong", "wrong", 1, None),
            Attempt(1, 0, "correct", "accepted", 0, None),
            Attempt(2, 0, "wrong", "wrong", 1, None),
        ]),
    ]


def check(items, **kwargs):
    return evaluate(items, reused_source=kwargs.get("source", {
        "key": SOURCE["key"], "revision": SOURCE["revision"],
    }), reused_case=kwargs.get("case", deepcopy(SOURCE["snapshot"])))


def test_exact_reuse_plus_gap_behavior_covers_rules_without_case_count_metric():
    result = check(complete_gaps())
    assert result.status == "passed"
    assert set(result.covered) == REQUIRED and not result.missing
    assert len(complete_gaps()) != len(REQUIRED)


@pytest.mark.parametrize("at", [120, 121])
def test_expired_boundary_cannot_claim_success(at):
    result = check([scenario("wrongboundary", [Attempt(at, 0, "correct", "accepted", 0, None)])])
    assert result.status == "failed" and "behavior_mismatch" in result.failures


def test_fourth_failure_does_not_lock_and_fifth_must_lock():
    attempts = [Attempt(i, 0, "wrong", "wrong", i + 1, None) for i in range(5)]
    assert "behavior_mismatch" in check([scenario("neverlock", attempts)]).failures
    attempts[3] = Attempt(3, 0, "wrong", "wrong", 4, 603)
    assert "behavior_mismatch" in check([scenario("earlylock", attempts[:4])]).failures


def test_more_normal_cases_cannot_replace_boundary_or_exception_coverage():
    normal = [scenario(str(i), [Attempt(0, 0, "correct", "accepted", 0, None)]) for i in range(50)]
    result = check(normal)
    assert result.status == "incomplete" and result.covered == ["valid_0"]


def test_wrong_evidence_unknown_rule_and_unsupported_expected_result_fail():
    value = complete_gaps()[0]
    value.evidence["OTP-1"] = "验证码有效期300秒"
    assert "requirement_evidence_mismatch" in check([value]).failures
    value = complete_gaps()[0]
    value.requirement_ids.append("OTP-SMS-COOLDOWN")
    assert "unknown_or_duplicate_requirement" in check([value]).failures
    value = scenario("invented", [Attempt(0, 0, "correct", "SMS_SENT", 0, None)])
    assert "behavior_mismatch" in check([value]).failures


def test_success_reset_is_real_transition_not_label():
    value = scenario("claimed_reset", [Attempt(0, 0, "correct", "accepted", 0, None)])
    assert "success_resets" not in check([value]).covered
    value = scenario("wrong_reset", [
        Attempt(0, 0, "wrong", "wrong", 1, None),
        Attempt(1, 0, "correct", "accepted", 1, None),
    ])
    assert "behavior_mismatch" in check([value]).failures


def test_missing_source_wrong_revision_or_changed_body_cannot_be_called_reuse():
    assert check(complete_gaps(), source=None, case=None).status == "failed"
    assert check(complete_gaps(), source={"key": SOURCE["key"], "revision": "old"}).status == "failed"
    changed = deepcopy(SOURCE["snapshot"])
    changed["steps"][0]["expected"] = "验证失败"
    assert "reused_source_body_changed" in check(complete_gaps(), case=changed).failures


def test_model_self_score_labels_and_authority_are_not_accepted_by_artifact_adapter():
    artifact = {"planning": {"test_points": [{"id": "P1", "title": "全部通过",
        "coverage": list(REQUIRED), "score": 100, "encoding_authority": "human_verified"}]}}
    adapted = adapt_artifact(artifact)
    assert adapted["status"] == "pending_manual"
    assert adapted["items"][0]["encoding_authority"] == "unverified"
    value = complete_gaps()[0]
    value.encoding_authority = "unverified"
    result = check([value])
    assert result.status == "pending_manual" and result.covered == ["valid_0"]


def test_fixture_scenario_cannot_hide_contradiction_with_partial_credit():
    value = scenario("contradiction", [
        Attempt(119, 0, "correct", "accepted", 0, None),
        Attempt(120, 0, "correct", "accepted", 0, None),
    ])
    covered, failures, manual = execute(value)
    assert not covered and failures and not manual


@pytest.mark.parametrize("elapsed,expected", [(599, "locked"), (600, "accepted"), (601, "accepted")])
def test_unlock_boundary_is_explicit_greater_than_or_equal_600(elapsed, expected):
    steps = [Attempt(i, 0, "wrong", "wrong", i + 1, 604 if i == 4 else None)
             for i in range(5)]
    steps.append(Attempt(4 + elapsed, 4 + elapsed, "correct", expected,
                         5 if expected == "locked" else 0,
                         604 if expected == "locked" else None))
    _, failures, manual = execute(scenario("unlock", steps))
    assert not failures and not manual


def test_behavior_without_its_rule_basis_is_not_coverage():
    value = complete_gaps()[3]
    value.requirement_ids = ["OTP-1"]
    value.evidence = {"OTP-1": RULES["OTP-1"]}
    covered, failures, _ = execute(value)
    assert not covered and "missing_requirement_basis" in failures


def test_complete_claims_plus_unverified_text_remain_pending_manual():
    prose = scenario("free_text", [])
    prose.encoding_authority = "unverified"
    result = check([*complete_gaps(), prose])
    assert result.status == "pending_manual" and not result.missing
