"""Known-code completeness, privacy, and diagnostic noninterference; no live calls."""
import ast
import json
from pathlib import Path

import pytest
from casepilot_agent.compact_generation import StageContractError
from workbench_agent_live_acceptance import exception_name
from workbench_domain_diagnostics import (
    DOMAIN_CODES,
    HARNESS_CODES,
    PREFIX_CODES,
    emit_domain_failure,
    safe_domain_failure,
    safe_job_failure,
)


@pytest.mark.parametrize("message,code", sorted(DOMAIN_CODES.items()))
def test_every_audited_domain_constant_retained(message, code):
    assert safe_domain_failure(ValueError(message)) == {"exception_class": "ValueError", "code": code}


@pytest.mark.parametrize("code", sorted(HARNESS_CODES))
def test_every_harness_contract_constant_retained(code):
    assert safe_domain_failure(RuntimeError(code))["code"] == code


@pytest.mark.parametrize("prefix,code", sorted(PREFIX_CODES.items()))
def test_only_fixed_prefix_retained_never_dynamic_tail(prefix, code):
    result = safe_domain_failure(ValueError(prefix + "private-secret-user-id"))
    assert result["code"] == code
    assert "private-secret" not in json.dumps(result)


def test_domain_literal_registry_covers_current_production_contracts():
    root = Path(__file__).resolve().parents[2] / "apps/agent/src/casepilot_agent"
    for name in ("planning", "reuse", "quantity", "output_obligations", "pipeline", "tasks",
                 "compact_generation", "planning_sources", "planning_coverage"):
        for node in ast.walk(ast.parse((root / f"{name}.py").read_text())):
            if (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)
                    and isinstance(node.exc.func, ast.Name)
                    and node.exc.func.id in {"ValueError", "RuntimeError", "StageContractError"} and node.exc.args
                    and isinstance(node.exc.args[0], ast.Constant)
                    and type(node.exc.args[0].value) is str):
                assert node.exc.args[0].value in DOMAIN_CODES


@pytest.mark.parametrize("error", [ValueError, TypeError, KeyError, RuntimeError,
                                     AttributeError, AssertionError, IndexError, LookupError,
                                     StageContractError])
def test_runtime_classes_known_but_secret_args_never_emitted(error):
    value = error("private-secret-input", {"key": "private-secret-key"})
    assert exception_name(value) == error.__name__
    result = safe_domain_failure(value)
    assert result["code"] == "unclassified_domain_failure"
    assert "private-secret" not in json.dumps(result)


def test_untrusted_str_repr_and_mapping_not_evaluated():
    class Hostile:
        def __str__(self):
            raise AssertionError("private-secret")
        def __repr__(self):
            raise AssertionError("private-secret")
    assert safe_domain_failure(ValueError(Hostile()))["code"] == "unclassified_domain_failure"
    assert safe_domain_failure(ValueError({"code": "required_reuse_source_invalid"}))["code"] == (
        "unclassified_domain_failure")


def test_lookup_failure_and_output_failure_never_mask_original():
    def broken():
        raise RuntimeError("private-secret-DSN")
    result = safe_job_failure("11111111-1111-4111-8111-111111111111", session_factory=broken)
    assert result == {"lookup": "unavailable"}
    events = []
    original = ValueError("required_reuse_source_invalid")
    with pytest.raises(ValueError) as caught:
        try:
            raise original
        except ValueError as error:
            emit_domain_failure(error, events.append,
                                job_id="11111111-1111-4111-8111-111111111111",
                                session_factory=broken)
            raise
    assert caught.value is original
    assert events[0]["job"] == {"lookup": "unavailable"}
    assert events[0]["failure"]["code"] == "required_reuse_source_invalid"
    emit_domain_failure(original, lambda event: broken())
    assert "private-secret" not in json.dumps(events)


@pytest.mark.parametrize("module_name,entry", [
    ("workbench_planning_quality_probe", "execute"),
    ("workbench_agent_short_reuse_schema", "execute"),
    ("workbench_agent_reuse_compare_probe", "execute"),
    ("workbench_agent_live_journey", "execute"),
    ("workbench_agent_live_crud", "execute_crud"),
    ("workbench_agent_live_continuation", "execute"),
])
@pytest.mark.parametrize("message,expected", [
    ("required_reuse_coverage_missing_replan_required", "required_reuse_coverage_missing_replan_required"),
    ("private-secret-response", "unclassified_domain_failure"),
])
def test_all_harness_summaries_preserve_known_code_not_secret(
    monkeypatch, capsys, tmp_path, module_name, entry, message, expected,
):
    import importlib

    module = importlib.import_module(module_name)

    async def fail(*args, **kwargs):
        raise ValueError(message)

    monkeypatch.setattr(module, "read_key", lambda *args: "private-secret-key")
    monkeypatch.setattr(module, entry, fail)
    if hasattr(module, "Path"):
        monkeypatch.setattr(module.Path, "mkdir", lambda *args, **kwargs: None)
    arguments = ["--allow-live", "--key-stdin"]
    if module_name == "workbench_planning_quality_probe":
        arguments += ["--artifact-path", str(tmp_path / "planning.json")]
    assert module.main(arguments) == 1
    output = capsys.readouterr().out
    report = json.loads(output.splitlines()[-1])
    assert report["exception_class"] == "ValueError"
    assert report["domain_failure"]["code"] == expected
    assert "private-secret" not in output
    assert report["requests_attempted"] == 0


@pytest.mark.parametrize("message", [
    "reserved_reuse_source_revoked", "reserved_reuse_plan_changed",
    "reserved_reuse_budget_required",
])
def test_stage_contract_codes_preserve_class_without_dynamic_message(message):
    assert safe_domain_failure(StageContractError(message)) == {
        "exception_class": "StageContractError", "code": message,
    }
    result = safe_domain_failure(StageContractError(message + ":private-secret"))
    assert result == {"exception_class": "StageContractError",
                      "code": "unclassified_domain_failure"}


@pytest.mark.parametrize("prefix", [
    "required_point_duration_missing_seconds:", "required_point_path_missing:",
    "required_point_status_missing:",
])
def test_dynamic_stage_contract_messages_are_not_added_as_general_prefixes(prefix):
    result = safe_domain_failure(StageContractError(prefix + "private-secret"))
    assert result["code"] == "unclassified_domain_failure"
    assert "private-secret" not in json.dumps(result)
