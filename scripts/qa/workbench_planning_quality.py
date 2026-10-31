"""Independent OTP planning oracle. Never infer semantic correctness from free text.

The bounded execution language below is QA-only. Production natural-language
artifacts are adapted as pending_manual until their behavior has been independently
encoded/reviewed; a model's claimed scenario labels are not execution evidence.
"""
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Literal

RULES = {
    "OTP-1": "正确验证码仅在生成后0≤t<120秒有效；过期验证码拒绝。",
    "OTP-2": "未锁定时，错误验证码累计第5次失败触发600秒锁定；前4次不锁定。",
    "OTP-3": "锁定期间即使验证码正确也拒绝；从触发锁定起满600秒解除锁定并清零失败计数。",
    "OTP-4": "成功验证清零失败计数。",
}
# Issuing a fresh code is fixture setup, not an invented product resend feature.
# Tests may supply its issuance time; issuing it does not reset failure state.
REQUIRED = {
    "valid_0", "valid_119", "expired_120", "expired_121", "wrong_4", "wrong_5",
    "locked_correct_599", "unlocked_correct_600", "success_resets",
}
SOURCE = {
    "key": "asset:otp-normal", "revision": "fixture-revision-1",
    "snapshot": {
        "title": "OTP正常成功", "module": "OTP", "priority": "P1", "case_type": "功能",
        "tags": [], "preconditions": ["未锁定，失败计数为0；验证码在t=0生成"],
        "steps": [{"action": "在t=0提交正确验证码", "expected": "验证成功，失败计数为0"}],
    },
}
BODY_FIELDS = tuple(SOURCE["snapshot"])


@dataclass(frozen=True)
class Attempt:
    at: int
    issued_at: int
    code: Literal["correct", "wrong"]
    expected: Literal["accepted", "wrong", "expired", "locked"]
    expected_failures: int
    expected_locked_until: int | None


@dataclass
class Scenario:
    id: str
    requirement_ids: list[str]
    evidence: dict[str, str]
    attempts: list[Attempt]
    # Only test-owned scripts or independently human-verified encodings execute.
    encoding_authority: Literal["fixture", "human_verified", "unverified"] = "unverified"


@dataclass
class Result:
    status: str
    covered: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    pending_manual: list[str] = field(default_factory=list)


def execute(scenario: Scenario):
    """Execute from an explicit clean initial state; expectations cannot change rules."""
    failures, covered = [], set()
    if scenario.encoding_authority not in {"fixture", "human_verified"}:
        return covered, [], True
    if not scenario.attempts:
        return covered, ["empty_scenario"], False
    if (not scenario.requirement_ids or len(scenario.requirement_ids) != len(set(scenario.requirement_ids))
            or any(key not in RULES for key in scenario.requirement_ids)):
        return covered, ["unknown_or_duplicate_requirement"], False
    if set(scenario.evidence) != set(scenario.requirement_ids) or any(
        scenario.evidence[key] != RULES[key] for key in scenario.requirement_ids
    ):
        return covered, ["requirement_evidence_mismatch"], False
    count, locked_until, previous_at = 0, None, -1
    for step in scenario.attempts:
        if (any(type(value) is not int for value in (step.at, step.issued_at, step.expected_failures))
                or step.at < previous_at or step.issued_at < 0 or step.at < step.issued_at
                or step.code not in {"correct", "wrong"}):
            return set(), ["invalid_execution_input"], False
        previous_at = step.at
        before_count, before_lock = count, locked_until
        if locked_until is not None and step.at >= locked_until:
            locked_until, count = None, 0
        age = step.at - step.issued_at
        if locked_until is not None:
            actual = "locked"
        elif step.code == "wrong":
            count += 1
            actual = "wrong"
            if count == 5:
                locked_until = step.at + 600
        elif age >= 120:
            actual = "expired"
        else:
            actual, count = "accepted", 0
        if (actual, count, locked_until) != (
            step.expected, step.expected_failures, step.expected_locked_until
        ):
            failures.append("behavior_mismatch")
            continue
        claims = set()
        if actual == "accepted" and age in {0, 119}:
            claims.add(f"valid_{age}")
        if actual == "expired" and age in {120, 121}:
            claims.add(f"expired_{age}")
        if actual == "wrong" and count in {4, 5}:
            claims.add(f"wrong_{count}")
        if actual == "locked" and step.code == "correct" and locked_until - step.at == 1:
            claims.add("locked_correct_599")
        if actual == "accepted" and before_lock is not None and step.at == before_lock:
            claims.add("unlocked_correct_600")
        if actual == "accepted" and before_count > 0 and before_lock is None:
            claims.add("success_resets")
        requirements = {
            "valid_0": {"OTP-1"}, "valid_119": {"OTP-1"},
            "expired_120": {"OTP-1"}, "expired_121": {"OTP-1"},
            "wrong_4": {"OTP-2"}, "wrong_5": {"OTP-2"},
            "locked_correct_599": {"OTP-2", "OTP-3"},
            "unlocked_correct_600": {"OTP-2", "OTP-3"}, "success_resets": {"OTP-4"},
        }
        for claim in claims:
            if requirements[claim] <= set(scenario.requirement_ids):
                covered.add(claim)
            else:
                failures.append("missing_requirement_basis")
    # A contradictory scenario cannot earn partial credit.
    return (set() if failures else covered), failures, False


def evaluate(scenarios: list[Scenario], *, reused_source=None, reused_case=None):
    covered, failures, pending = set(), [], []
    if reused_source != {"key": SOURCE["key"], "revision": SOURCE["revision"]}:
        failures.append("reused_source_identity_mismatch")
    if (not isinstance(reused_case, dict) or any(
        reused_case.get(key) != SOURCE["snapshot"][key] for key in BODY_FIELDS
    )):
        failures.append("reused_source_body_changed")
    if not failures:
        covered.add("valid_0")  # Fixture-owned exact source has this known behavior.
    seen = set()
    for scenario in scenarios:
        if scenario.id in seen:
            failures.append("duplicate_scenario_id")
        seen.add(scenario.id)
        observed, errors, manual = execute(scenario)
        covered.update(observed)
        failures.extend(errors)
        if manual:
            pending.append(scenario.id)
    missing = sorted(REQUIRED - covered)
    status = "failed" if failures else "pending_manual" if pending else "incomplete" if missing else "passed"
    return Result(status, sorted(covered), missing, sorted(set(failures)), pending)


def adapt_artifact(artifact):
    """Read actual planning/case artifacts without trusting generated coverage claims.

    Return exact content for independent encoding plus explicitly non-passing
    records. This adapter does NOT parse Chinese prose or assign coverage labels.
    """
    planning = artifact.get("planning", artifact)
    points = planning.get("test_points", [])
    cases = artifact.get("test_cases", [])
    return {
        "status": "pending_manual",
        "items": [{"kind": kind, "id": str(item.get("id", "")),
                   "content": deepcopy(item), "encoding_authority": "unverified"}
                  for kind, values in (("test_point", points), ("test_case", cases))
                  for item in values],
        "rule_catalog": deepcopy(RULES), "required_coverage": sorted(REQUIRED),
    }
