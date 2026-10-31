"""Real planning orchestration, deterministic provider; no network, DB or quality claim."""
import json
from copy import deepcopy
from unittest.mock import patch

import pytest
import workbench_planning_quality_probe as probe
from pydantic import ValidationError


class Provider:
    def __init__(self):
        self.calls = []

    def complete(self, *, stage, payload, result_type, **kwargs):
        self.calls.append(stage)
        requirement, context = probe.fixture()
        assert payload["requirement"]["business_rules"] == requirement.business_rules
        assert all(setting in payload["requirement"]["constraints"]
                   for setting in probe.TEST_SETUP)
        assert payload["context"]["historical_cases"] == context["historical_cases"]
        if stage == "feature.generated":
            return result_type.model_validate({"feature_points": [{
                "id": "f", "name": "OTP validity", "description": probe.RULES["OTP-1"],
                "module": "OTP", "requirement_refs": ["OTP-1"],
            }]}), None
        assert stage == "test_point.generated"
        assert payload["target_count"] is None
        feature_id = payload["feature_points"]["feature_points"][0]["id"]
        return result_type.model_validate({"test_points": [{
            "id": "p", "title": "Correct OTP at 0 seconds", "scenario": "Not locked",
            "objective": "Accepted", "category": "functional", "priority": "P1",
            "priority_reason": "Core validation", "feature_point_ids": [feature_id],
            "primary_binding": next(pair["id"] for pair in payload["primary_bindings"]
                                    if pair["feature_id"] == feature_id), "source_refs": [{
                "locator": payload["feature_source_slots"][feature_id][0], "label": "Input"}],
        }]}), None


def artifact():
    return probe.plan(Provider(), "offline")


def test_real_planning_fixed_synthetic_fixture_and_no_quality_claim(tmp_path):
    before = deepcopy((probe.RULES, probe.SOURCE))
    provider = Provider()
    result = probe.plan(provider, "offline")
    assert provider.calls == ["feature.generated", "test_point.generated"]
    assert len(result.test_points) == 1  # No manufactured quota or quality pass.
    assert result.test_points[0].id.startswith("TP-")
    assert (probe.RULES, probe.SOURCE) == before
    path = probe.write_artifact(tmp_path / "planning.json", result)
    saved = json.loads(path.read_text())
    assert set(saved) == {"feature_points", "test_points", "coverage_review"}
    assert saved["coverage_review"]["status"] == "pending_independent_review"
    assert saved["coverage_review"]["batches"][0]["warnings"] == ["coverage_not_assessed"]
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(probe.SafetyStop):
        probe.write_artifact(path, result)


@pytest.mark.parametrize("level", ["root", "feature", "point", "source", "coverage"])
def test_artifact_rejects_raw_secret_fields_before_creating_file(tmp_path, level):
    value = artifact().model_dump(mode="json")
    target = value
    if level == "feature":
        target = value["feature_points"][0]
    elif level == "point":
        target = value["test_points"][0]
    elif level == "source":
        target = value["feature_points"][0]["source_refs"][0]
    elif level == "coverage":
        target = value["coverage_review"]["batches"][0]
    target["raw_response"] = "private-secret-key"
    path = tmp_path / "secret.json"
    with pytest.raises(ValidationError):
        probe.write_artifact(path, value)
    assert not path.exists()


@pytest.mark.parametrize("extra", [[], ["--allow-live", "--max-requests", "9"]])
def test_no_permission_or_excessive_budget_makes_zero_calls(tmp_path, capsys, extra):
    with patch.object(probe, "execute") as execute:
        assert probe.main(["--artifact-path", str(tmp_path / "p.json"), *extra]) == 1
        execute.assert_not_called()
    report = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert report["requests_attempted"] == 0
    assert report["quality_status"] == "quality_pending_manual"
    assert report["fixture_version"] == "otp-controlled-clock-v2"
    assert report["rules_sha256"] == probe.RULES_SHA256
    assert report["same_input_ab_comparison"] is False
    assert not report["artifact_saved"]


def test_summary_success_is_only_artifact_saved(tmp_path, capsys):
    async def fake_execute(*args):
        return artifact()
    with patch.object(probe, "read_key", return_value="unused"), \
         patch.object(probe, "execute", side_effect=fake_execute):
        assert probe.main(["--allow-live", "--artifact-path", str(tmp_path / "p.json")]) == 0
    report = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert report["quality_status"] == "quality_pending_manual"
    assert report["fixture_version"] == "otp-controlled-clock-v2"
    assert report["rules_sha256"] == probe.RULES_SHA256
    assert report["same_input_ab_comparison"] is False
    assert report["artifact_saved"] and "passed" not in report
    assert not report["continuous_chain_passed"]
    assert "Correct OTP" not in json.dumps(report)


def test_path_refuses_symlink_parent_and_non_json(tmp_path):
    (tmp_path / "link").symlink_to(tmp_path, target_is_directory=True)
    for path in [tmp_path / "link" / "p.json", tmp_path / "p.txt", "/etc/p.json"]:
        with pytest.raises(probe.SafetyStop):
            probe.artifact_path(path)


def test_shared_budget_stops_at_eight_without_transport():
    budget = probe.RequestBudget(8)
    for _ in range(8):
        budget.reserve()
    with pytest.raises(probe.SafetyStop):
        budget.reserve()
    assert budget.count == 8


class CrossRuleProvider(Provider):
    wrong_completion_owner = False

    def complete(self, *, stage, payload, result_type, **kwargs):
        def slot(rule):
            return next(row["slot"] for row in payload["source_catalog"]
                        if row["excerpt"] == probe.RULES[rule])

        if stage == "feature.generated":
            self.calls.append(stage)
            features = [{
                "id": "f", "name": "Success resets counter", "description": probe.RULES["OTP-4"],
                "module": "OTP", "requirement_refs": ["OTP-4"],
                "source_refs": [{"locator": slot("OTP-4"), "label": "untrusted label"}],
            }]
            if self.wrong_completion_owner:
                features.append({"id": "other", "name": "Validity", "module": "OTP",
                    "description": probe.RULES["OTP-1"], "requirement_refs": ["OTP-1"],
                    "source_refs": [{"locator": slot("OTP-1"), "label": "Input"}]})
            return result_type.model_validate({"feature_points": features}), None
        self.calls.append(stage)
        assert stage == "test_point.generated"
        features = payload.get("feature_points", {}).get("feature_points")
        if payload.get("coverage_completion"):
            points = deepcopy(payload["existing_plan"]["test_points"])
            owner = points[0]["feature_point_ids"][0]
        else:
            owner = features[0]["id"]
            self.other_owner = features[-1]["id"]
            points = [{"id": "p1", "title": "Success clears zero failure count",
                "scenario": "Not locked", "objective": "Accepted", "category": "functional",
                "priority": "P1", "priority_reason": "Core validation",
                "feature_point_ids": [f["id"] for f in features],
                "primary_feature_id": owner, "source_refs": [
                    {"locator": slot("OTP-4"), "label": "untrusted"},
                    {"locator": slot("OTP-1"), "label": "untrusted"}]}]
        if payload.get("coverage_completion"):
            points.append({"id": "p2", "title": "Success clears count after four failures",
                "scenario": "Four failures; not locked; valid code within 120 seconds",
                "objective": "Successful verification resets failure count to zero", "category": "boundary", "priority": "P1",
                "priority_reason": "Counter reset safety",
                "feature_point_ids": ([owner, self.other_owner]
                                      if self.wrong_completion_owner else [owner]),
                "primary_feature_id": self.other_owner if self.wrong_completion_owner else owner,
                "source_refs": [{"locator": slot("OTP-4"), "label": "MODEL WRONG"},
                                {"locator": slot("OTP-1"), "label": "MODEL WRONG"},
                                {"locator": slot("OTP-2"), "label": "MODEL WRONG"}]})
        obligations = [
            {"id": "o1", "feature_point_ids": [owner], "dimension": "normal",
             "basis": probe.RULES["OTP-4"], "point_ids": ["p1"]},
            {"id": "o2", "feature_point_ids": [owner], "dimension": "state",
             "basis": probe.RULES["OTP-4"] + probe.RULES["OTP-1"] + probe.RULES["OTP-2"],
             "point_ids": ["p2"] if len(points) > 1 else []},
        ]
        for point in points:
            intended_owner = point.pop("primary_feature_id", point["feature_point_ids"][0])
            point["primary_binding"] = next(pair["id"] for pair in payload["primary_bindings"]
                                            if pair["feature_id"] == intended_owner)
        return result_type.model_validate({"test_points": points,
            "coverage_obligations": obligations, "duplicate_suggestions": []}), None


def test_probe_retains_cross_rule_citations_and_bounded_coverage_metadata(tmp_path):
    provider = CrossRuleProvider()
    artifact = probe.plan(provider, "offline")
    assert provider.calls == ["feature.generated", "test_point.generated", "test_point.generated"]
    assert len(artifact.test_points) == 2
    feature = artifact.feature_points[0]
    cross = next(point for point in artifact.test_points if "four failures" in point.title)
    assert cross.feature_point_ids == [feature.id]
    assert {ref.source_id for ref in feature.source_refs} == {"OTP-4"}
    assert {ref.source_id for ref in cross.source_refs} == {"OTP-4", "OTP-1", "OTP-2"}
    assert {ref.excerpt for ref in cross.source_refs} == {probe.RULES[key] for key in ("OTP-4", "OTP-1", "OTP-2")}
    saved = json.loads(probe.write_artifact(tmp_path / "cross.json", artifact).read_text())
    batch = saved["coverage_review"]["batches"][0]
    assert batch["completion_attempted"] and not batch["uncovered_ids"]
    assert {ref for item in batch["obligations"] for ref in item["point_ids"]} == {
        point.id for point in artifact.test_points}
    assert "MODEL WRONG" not in json.dumps(saved)
    assert saved["coverage_review"]["status"] == "pending_independent_review"


def test_explicit_quota_preserves_uncovered_review_without_an_extra_call():
    from casepilot_agent.planning import build_planning
    provider = CrossRuleProvider()
    requirement, context = probe.fixture()
    def complete(stage, instruction, payload, result_type):
        return provider.complete(stage=stage, payload=payload, result_type=result_type)[0]
    plan = build_planning(requirement, context, complete, target_count=1)
    assert provider.calls == ["feature.generated", "test_point.generated"]
    assert len(plan["test_points"]) == 1
    batch = plan["coverage_review"]["batches"][0]
    assert batch["uncovered_ids"] == ["o2"]
    assert batch["completion_attempted"] is False
    assert plan["coverage_review"]["status"] == "pending_independent_review"


def test_coverage_diagnostic_known_fields_only():
    from agents.exceptions import ModelBehaviorError
    from workbench_safe_diagnostics import safe_structured_failure
    error = ModelBehaviorError("private-secret")
    error.casepilot_safe_diagnostic = {
        "stage": "test_point.generated", "schema": "BatchTestPointPlan",
        "exception_chain": ["ModelBehaviorError"],
        "validation_errors": [{"type": "missing",
            "loc": ["coverage_obligations", 0, "basis"], "input": "private-secret"}],
    }
    diagnostic = safe_structured_failure(error)
    assert diagnostic["validation_errors"] == [
        {"type": "missing", "loc": ["coverage_obligations", 0, "basis"]}]
    assert "private-secret" not in json.dumps(diagnostic)


@pytest.mark.parametrize("message,code", [
    ("planning_coverage_existing_point_changed", "planning_coverage_existing_point_changed"),
    ("private-secret-response", "unclassified_domain_failure"),
])
def test_local_planning_error_is_emitted_before_top_level_summary_and_not_masked(
    monkeypatch, capsys, message, code
):
    from casepilot_agent import planning
    original = ValueError(message)
    def fail(*args, **kwargs):
        raise original
    monkeypatch.setattr(planning, "build_planning", fail)
    with pytest.raises(ValueError) as caught:
        probe.plan(Provider(), "offline")
    assert caught.value is original
    output = capsys.readouterr().out
    event = json.loads(output)
    assert event == {"event": "domain_failure", "phase": "planning_validation",
                     "failure": {"exception_class": "ValueError", "code": code}}
    assert "summary" not in output and "private-secret" not in output


def test_stage_failure_is_flushed_with_allowlisted_stage_and_original_error(capsys):
    original = RuntimeError("planning_source_reference_invalid")
    class FailureProvider:
        def complete(self, **kwargs):
            raise original
    with pytest.raises(RuntimeError) as caught:
        probe.plan(FailureProvider(), "offline")
    assert caught.value is original
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[0]["stage"] == "feature.generated"
    assert events[0]["failure"]["code"] == "planning_source_reference_invalid"
    assert all(event["event"] == "domain_failure" for event in events)


def test_broken_diagnostic_sink_does_not_replace_domain_failure(monkeypatch):
    original = ValueError("planning_coverage_basis_invalid")
    class FailureProvider:
        def complete(self, **kwargs):
            raise original
    def broken(*args, **kwargs):
        raise OSError("private-secret")
    monkeypatch.setattr(probe, "emit_json", broken)
    with pytest.raises(ValueError) as caught:
        probe.plan(FailureProvider(), "offline")
    assert caught.value is original


def test_safe_http_stage_context_distinguishes_initial_and_completion_calls():
    from workbench_agent_live_acceptance import STAGE
    class ObservedProvider(CrossRuleProvider):
        def __init__(self):
            super().__init__()
            self.stages = []
        def complete(self, **kwargs):
            self.stages.append(STAGE.get())
            return super().complete(**kwargs)
    provider = ObservedProvider()
    probe.plan(provider, "offline")
    assert provider.stages == ["feature.generated", "test_point.generated",
                               "planning_coverage_completion"]


def test_coverage_custom_type_allowlist_tracks_exact_production_contract():
    from casepilot_agent.planning_coverage import COVERAGE_VALIDATION_CODES
    from workbench_safe_diagnostics import _COVERAGE_TYPES
    assert _COVERAGE_TYPES == COVERAGE_VALIDATION_CODES


@pytest.mark.parametrize("code", sorted(__import__(
    "workbench_safe_diagnostics")._COVERAGE_TYPES))
def test_terminal_coverage_structured_failure_keeps_type_not_input_or_context(
    monkeypatch, tmp_path, capsys, code
):
    from agents.exceptions import ModelBehaviorError
    from casepilot_agent.providers.safe_diagnostics import structured_failure
    from pydantic import create_model, model_validator
    from pydantic_core import PydanticCustomError

    def reject(self):
        raise PydanticCustomError(code, "private-secret-message", {"key": "private-secret-context"})
    schema = create_model("BatchTestPointPlan",
        __validators__={"reject": model_validator(mode="after")(reject)})
    with pytest.raises(ValidationError) as caught:
        schema.model_validate({"raw_response": "private-secret-body"})
    error = ModelBehaviorError("private-secret-provider")
    error.__cause__ = caught.value
    error.casepilot_safe_diagnostic = structured_failure(
        error, stage="test_point.generated", result_type=schema)
    async def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(probe, "read_key", lambda *args: "private-secret-key")
    monkeypatch.setattr(probe, "execute", fail)
    assert probe.main(["--allow-live", "--artifact-path", str(tmp_path / "p.json")]) == 1
    output = capsys.readouterr().out
    report = json.loads(output.splitlines()[-1])
    assert report["structured_failure"]["schema"] == "BatchTestPointPlan"
    assert report["structured_failure"]["validation_errors"] == [{"type": code, "loc": []}]
    assert "private-secret" not in output
    assert not report["artifact_saved"]


def test_completion_cannot_change_primary_owner_to_dependency_even_with_real_sources():
    provider = CrossRuleProvider()
    provider.wrong_completion_owner = True
    with pytest.raises(ValidationError) as caught:
        probe.plan(provider, "offline")
    assert caught.value.errors(include_input=False)[0]["type"] == (
        "planning_coverage_completion_owner_invalid")
    assert provider.calls == ["feature.generated", "test_point.generated", "test_point.generated"]


def test_primary_feature_location_is_retained_without_model_identity():
    from agents.exceptions import ModelBehaviorError
    from workbench_safe_diagnostics import safe_structured_failure
    error = ModelBehaviorError("private-secret")
    error.casepilot_safe_diagnostic = {
        "stage": "test_point.generated", "schema": "BatchTestPointPlan",
        "exception_chain": ["ModelBehaviorError", "ValidationError"],
        "validation_errors": [{"type": "literal_error",
            "loc": ["test_points", 0, "primary_feature_id"],
            "input": "private-secret-foreign-feature"}],
    }
    result = safe_structured_failure(error)
    assert result["validation_errors"] == [{"type": "literal_error",
        "loc": ["test_points", 0, "primary_feature_id"]}]
    assert "private-secret" not in json.dumps(result)


def test_optional_primary_artifact_keeps_marker_and_legacy_fingerprint():
    from casepilot_agent.contracts import FeaturePoint, TestPoint
    from casepilot_agent.output_obligations import plan_fingerprint
    from casepilot_agent.planning import planned_module

    raw = artifact().model_dump(mode="json")
    point = raw["test_points"][0]
    assert point["primary_feature_id"] == point["feature_point_ids"][0]
    assert probe.PlanningArtifact.model_validate(raw).model_dump(mode="json") == raw
    features = [FeaturePoint(id="a", name="A", module="First", description="First rule", requirement_refs=[]),
                FeaturePoint(id="b", name="B", module="Second", description="Second rule", requirement_refs=[])]
    point.pop("primary_feature_id")
    point["feature_point_ids"] = ["b", "a"]
    legacy = TestPoint.model_validate(point)
    assert planned_module(legacy, features) == "First/A"
    assert legacy.model_dump(mode="json") == point
    old_plan = {"test_points": [point], "feature_points": [f.model_dump() for f in features]}
    round_trip = {**old_plan, "test_points": [probe.ArtifactPoint.model_validate(point).model_dump()]}
    assert round_trip == old_plan
    assert plan_fingerprint(round_trip) == plan_fingerprint(old_plan)


@pytest.mark.parametrize("location", ["primary_binding", "primary_feature_id"])
def test_primary_binding_diagnostic_location_never_exposes_pair_value(location):
    from agents.exceptions import ModelBehaviorError
    from workbench_safe_diagnostics import safe_structured_failure
    error = ModelBehaviorError("secret-body")
    error.casepilot_safe_diagnostic = {
        "stage": "test_point.generated", "schema": "BatchTestPointPlan",
        "exception_chain": ["ModelBehaviorError", "ValidationError"],
        "validation_errors": [{"type": "literal_error", "loc": ["test_points", 0, location],
                               "input": "secret-pair", "ctx": {"expected": "secret-pair"}}]}
    assert safe_structured_failure(error)["validation_errors"] == [
        {"type": "literal_error", "loc": ["test_points", 0, location]}]
    assert "secret" not in json.dumps(safe_structured_failure(error))


def test_probe_sdk_schema_uses_primary_pair_not_hidden_owner():
    from agents import AgentOutputSchema
    from casepilot_agent.providers.structured_output import recovering_output_schema

    class SchemaProvider(Provider):
        def complete(self, *, stage, payload, result_type, **kwargs):
            if stage == "test_point.generated":
                schema = recovering_output_schema(AgentOutputSchema, result_type).json_schema()
                point = schema["$defs"]["BatchTestPoint"]
                assert "primary_binding" in point["required"]
                assert "primary_feature_id" not in point["properties"]
                pairs = payload["primary_bindings"]
                assert pairs and all(set(pair) == {"id", "feature_id", "source_slot"}
                                     for pair in pairs)
            return super().complete(stage=stage, payload=payload, result_type=result_type, **kwargs)

    result = probe.plan(SchemaProvider(), "offline").model_dump(mode="json")
    assert "primary_binding" not in result["test_points"][0]
    assert result["test_points"][0]["primary_feature_id"]
    assert result["test_points"][0]["source_refs"]



def test_controlled_clock_v2_changes_setup_not_product_rules():
    requirement, context = probe.fixture()
    assert probe.RULES_SHA256 == (
        "696f40934241b9707d28ec8b2aa2cc1b3925b480153a4d85cfca57ddc345554f")
    assert requirement.business_rules == [f"{key}: {value}" for key, value in probe.RULES.items()]
    assert [item["excerpt"] for item in context["evidence"]] == list(probe.RULES.values())
    assert context["test_setup"] == list(probe.TEST_SETUP)
    assert all(setting in requirement.constraints for setting in probe.TEST_SETUP)
    assert "按整数秒采样" in probe.TEST_SETUP[0]
    assert "不是产品时间精度限制" in probe.TEST_SETUP[0]
    assert "任意 issued_at" in probe.TEST_SETUP[1]
    assert "不是发送或重发能力" in probe.TEST_SETUP[1]
    assert "预置不会重置失败计数" in probe.TEST_SETUP[1]


def test_boundary_artifact_strict_projection_and_legacy_omission():
    raw = artifact().model_dump(mode="json")
    assert "boundary_samples" not in raw["test_points"][0]
    assert all("boundary_contract" not in obligation
               for batch in raw["coverage_review"]["batches"] for obligation in batch["obligations"])
    point = raw["test_points"][0]
    ref = {"source_id": "OTP-1", "document_id": "synthetic-otp-rules", "chunk_id": None,
           "label": "OTP-1", "locator": "OTP-1", "excerpt": probe.RULES["OTP-1"]}
    contract = {"status": "model_proposed", "source_ref": ref,
                "source_literal": probe.RULES["OTP-1"], "threshold": 120.0, "unit": "秒",
                "comparator": "lt", "axis": "验证码", "time_origin": "生成后",
                "sampling_step": None, "sampling_literal": ""}
    point["boundary_samples"] = [{"obligation_id": "boundary", "position": "at", "value": 120,
        "initial_state": "未锁定", "assertion": "过期验证码拒绝", "assertion_role": "primary",
        "assertion_feature_id": point["primary_feature_id"], "assertion_source_ref": ref,
        "unit": "秒", "axis": "验证码", "time_origin": "生成后"}]
    raw["coverage_review"]["batches"][0]["obligations"] = [{"id": "boundary",
        "feature_point_ids": point["feature_point_ids"], "dimension": "boundary",
        "basis": probe.RULES["OTP-1"], "point_ids": [point["id"]], "clarification": "",
        "boundary_contract": contract}]
    restored = probe.PlanningArtifact.model_validate(raw).model_dump(mode="json")
    assert restored == raw
    for target_kind in ("sample", "contract"):
        for bad_kind in ("null_ref", "temporary_slot"):
            malformed = deepcopy(raw)
            if target_kind == "sample":
                target = malformed["test_points"][0]["boundary_samples"][0]
                ref_key, slot_key = "assertion_source_ref", "assertion_source_slot"
            else:
                target = malformed["coverage_review"]["batches"][0]["obligations"][0][
                    "boundary_contract"]
                ref_key, slot_key = "source_ref", "source_slot"
            target[ref_key if bad_kind == "null_ref" else slot_key] = (
                None if bad_kind == "null_ref" else "source:0")
            with pytest.raises(ValidationError):
                probe.PlanningArtifact.model_validate(malformed)
    for location in ("sample", "contract", "sample_source", "contract_source"):
        malformed = deepcopy(raw)
        sample = malformed["test_points"][0]["boundary_samples"][0]
        boundary = malformed["coverage_review"]["batches"][0]["obligations"][0]["boundary_contract"]
        target = {"sample": sample, "contract": boundary,
                  "sample_source": sample["assertion_source_ref"],
                  "contract_source": boundary["source_ref"]}[location]
        target["raw_response"] = "private-secret"
        with pytest.raises(ValidationError):
            probe.PlanningArtifact.model_validate(malformed)



@pytest.mark.parametrize("error_type", ["finite_number", "float_type", "greater_than"])
def test_boundary_numeric_diagnostic_types_are_safe(error_type):
    from agents.exceptions import ModelBehaviorError
    from workbench_safe_diagnostics import safe_structured_failure
    error = ModelBehaviorError("secret-model-body")
    error.casepilot_safe_diagnostic = {
        "stage": "test_point.generated", "schema": "BatchTestPointPlan",
        "exception_chain": ["ModelBehaviorError", "ValidationError"],
        "validation_errors": [{"type": error_type,
            "loc": ["coverage_obligations", 0, "boundary_contract", "sampling_step"],
            "input": "secret", "ctx": {"secret": "secret"}}]}
    safe = safe_structured_failure(error)
    assert safe["validation_errors"][0]["type"] == error_type
    assert safe["validation_errors"][0]["loc"][-2:] == ["boundary_contract", "sampling_step"]
    assert "secret" not in json.dumps(safe)
