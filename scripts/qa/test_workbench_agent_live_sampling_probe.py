"""Safety and artifact scope for the opt-in NL entry probe; never transport calls."""
import hashlib
import json
from unittest.mock import patch

import pytest
import workbench_agent_live_sampling_probe as probe
from pydantic import ValidationError
from test_workbench_planning_quality_probe import artifact


def typed_artifact():
    return probe.SamplingArtifact.model_validate({**artifact().model_dump(mode="json"),
                                                  "source_commit": "a" * 40})


@pytest.mark.parametrize("args", [[], ["--allow-live", "--max-requests", "17"]])
def test_no_optin_or_oversized_budget_never_calls_provider(tmp_path, capsys, args):
    with patch.object(probe, "execute") as execute:
        assert probe.main(["--artifact-path", str(tmp_path / "fresh.json"), *args]) == 1
        execute.assert_not_called()
    report = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert not report["artifact_saved"]
    assert report["scope"] == "nl_planning_only"
    assert report["quality_status"] == "quality_pending_manual"


def test_fixed_prompt_contains_unchanged_rules_and_real_sampling_setup():
    assert all(value in probe.PROMPT for value in probe.RULES.values())
    assert all(value in probe.PROMPT for value in probe.TEST_SETUP)
    assert probe.PROMPT_SHA256 == hashlib.sha256(probe.PROMPT.encode()).hexdigest()
    assert probe.RULES_SHA256 == "696f40934241b9707d28ec8b2aa2cc1b3925b480153a4d85cfca57ddc345554f"


def test_artifact_is_private_exclusive_typed_and_never_raw(tmp_path):
    value = typed_artifact()
    path = probe.write_artifact(tmp_path / "fresh.json", value)
    assert path.stat().st_mode & 0o777 == 0o600
    restored = probe.SamplingArtifact.model_validate_json(path.read_text())
    assert restored == value
    assert restored.original_prompt_fixture_sha256 == probe.PROMPT_SHA256
    with pytest.raises(probe.SafetyStop):
        probe.write_artifact(path, value)
    for field in ("raw_response", "reasoning", "api_key", "headers", "original_prompt"):
        raw = value.model_dump(mode="json")
        raw[field] = "private-secret"
        with pytest.raises(ValidationError):
            probe.SamplingArtifact.model_validate(raw)
    raw = value.model_dump(mode="json")
    raw["source_commit"] = "untrusted"
    with pytest.raises(ValidationError):
        probe.SamplingArtifact.model_validate(raw)


def test_failure_summary_does_not_expose_exception_or_key(tmp_path, capsys):
    async def failed(*args):
        raise ValueError("private-secret-body")
    with patch.object(probe, "read_key", return_value="private-secret-key"), \
         patch.object(probe, "execute", side_effect=failed):
        assert probe.main(["--allow-live", "--artifact-path", str(tmp_path / "fresh.json")]) == 1
    output = capsys.readouterr().out
    assert "private-secret" not in output
    assert not json.loads(output.splitlines()[-1])["artifact_saved"]


def test_success_summary_never_claims_semantic_quality_or_full_chain(tmp_path, capsys):
    async def completed(key, model, budget, report, storage):
        report["protocol_passed"] = True
        return typed_artifact()
    with patch.object(probe, "read_key", return_value="unused"), \
         patch.object(probe, "execute", side_effect=completed):
        assert probe.main(["--allow-live", "--artifact-path", str(tmp_path / "fresh.json")]) == 0
    summary = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert summary["artifact_saved"] and summary["protocol_passed"]
    assert summary["quality_status"] == "quality_pending_manual"
    assert summary["no_formal_adoption"] and summary["setup_collection_scripted"]
    assert not summary["continuous_chain_passed"]
    assert "feature_points" not in summary and "test_points" not in summary


def test_same_obligation_point_link_required_not_two_independent_any_checks():
    from copy import deepcopy

    raw = typed_artifact().model_dump(mode="json")
    point = raw["test_points"][0]
    second = {**deepcopy(point), "id": "other-point"}
    raw["test_points"].append(second)
    ref = {"source_id": None, "document_id": None, "chunk_id": None,
           "label": "Synthetic user", "locator": "user_input", "excerpt": probe.PROMPT}
    contract = {"status": "model_proposed", "source_ref": ref, "source_literal": probe.RULES["OTP-1"],
                "threshold": 120, "unit": "秒", "comparator": "lt", "axis": "验证码",
                "time_origin": "生成后", "sampling_step": 1, "sampling_literal": "按整数秒采样"}
    point["boundary_samples"] = [{"obligation_id": "same-id", "position": "at", "value": 120,
        "initial_state": "未锁定", "assertion": "拒绝", "assertion_role": "primary",
        "assertion_feature_id": point["primary_feature_id"], "assertion_source_ref": ref,
        "unit": "秒", "axis": "验证码", "time_origin": "生成后"}]
    batch = raw["coverage_review"]["batches"][0]
    batch["obligations"] = [{"id": "same-id", "feature_point_ids": point["feature_point_ids"],
        "dimension": "boundary", "basis": probe.RULES["OTP-1"], "point_ids": [second["id"]],
        "clarification": "", "boundary_contract": contract}]
    # A different batch has the sample's same ID but no authorized sampling step.
    other_batch = deepcopy(batch)
    other_batch["batch_index"] = 2
    other_batch["obligations"][0]["point_ids"] = [point["id"]]
    other_batch["obligations"][0]["boundary_contract"]["sampling_step"] = None
    raw["coverage_review"]["batches"].append(other_batch)
    assert not probe.has_user_sampling_sample(probe.SamplingArtifact.model_validate(raw))
    batch["obligations"][0]["point_ids"] = [point["id"]]
    assert probe.has_user_sampling_sample(probe.SamplingArtifact.model_validate(raw))
    point["boundary_samples"][0]["unit"] = "分钟"
    assert not probe.has_user_sampling_sample(probe.SamplingArtifact.model_validate(raw))


@pytest.mark.parametrize("stage", ["nl_sampling_submit", "sampling_draft_worker"])
def test_safe_transport_stage_is_fixed_and_retained(stage):
    from workbench_agent_live_acceptance import STAGE, set_stage
    token = set_stage(stage)
    try:
        assert STAGE.get() == stage
        set_stage("secret-unknown-stage")
        assert STAGE.get() == "unspecified"
    finally:
        STAGE.reset(token)
