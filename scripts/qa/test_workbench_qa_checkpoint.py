"""Offline checkpoint mechanics only; never simulate paid/domain success evidence."""
import asyncio
import json
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch
from uuid import uuid4

import pytest
import workbench_agent_live_crud as crud
import workbench_agent_live_journey as base
import workbench_agent_live_short_crud as short
from workbench_agent_live_acceptance import STAGES, RequestBudget
from workbench_qa_checkpoint import (
    CONTINUOUS_CHECKS,
    CheckpointError,
    CheckpointWriter,
    atomic_save,
    load_verified,
    validate_checkpoint,
)

STAGE_SET, CHECKS = {"setup", "rewrite_apply"}, {"safe_gate"}


def snapshot():
    return {
        "schema_version": 1, "run_id": str(uuid4()),
        "scope": "independent_short_synthetic_stage",
        "database": {"system_identifier": "123456789", "database_oid": "123",
                     "server_version_num": "170005", "schema_revision": "20261028_0037",
                     "synthetic_id": str(uuid4()), "source_commit": "a" * 40},
        "stage": "setup", "state": "pending", "passed_checks": [], "workspace_ids": [],
        "requests_reserved": 0, "request_limit": 30,
        "continuous_chain_passed": False, "resume_allowed": False,
    }


def test_atomic_private_roundtrip_and_trusted_digest(tmp_path):
    value, path = snapshot(), tmp_path / "checkpoint.json"
    digest = atomic_save(path, value, stages=STAGE_SET, checks=CHECKS)
    assert path.stat().st_mode & 0o777 == 0o600
    assert load_verified(path, expected_digest=digest, expected_database=value["database"],
                         stages=STAGE_SET, checks=CHECKS) == value
    assert list(tmp_path.iterdir()) == [path]
    path.write_text(path.read_text().replace('"pending"', '"finished"'))
    with pytest.raises(CheckpointError, match="checkpoint_digest_mismatch"):
        load_verified(path, expected_digest=digest, expected_database=value["database"],
                      stages=STAGE_SET, checks=CHECKS)


@pytest.mark.parametrize("field,value", [
    ("prompt", "PRIVATE_PROMPT"), ("api_key", "PRIVATE_CREDENTIAL"),
    ("resume_allowed", True), ("continuous_chain_passed", True),
    ("stage", "PRIVATE_MODEL_TEXT"), ("workspace_ids", ["PRIVATE_DOCUMENT"]),
    ("passed_checks", ["PRIVATE_MODEL_TEXT"]), ("requests_reserved", -1),
    ("request_limit", True),
])
def test_tamper_or_free_text_fields_rejected(field, value):
    with pytest.raises(CheckpointError):
        validate_checkpoint({**snapshot(), field: value}, stages=STAGE_SET, checks=CHECKS)


def test_changed_database_or_source_revision_never_resumes(tmp_path):
    value, path = snapshot(), tmp_path / "checkpoint.json"
    digest = atomic_save(path, value, stages=STAGE_SET, checks=CHECKS)
    for field in value["database"]:
        with pytest.raises(CheckpointError, match="checkpoint_database_mismatch"):
            load_verified(path, expected_digest=digest,
                          expected_database={**value["database"], field: "changed"},
                          stages=STAGE_SET, checks=CHECKS)


def test_symlink_and_world_readable_checkpoint_rejected(tmp_path):
    value, path = snapshot(), tmp_path / "checkpoint.json"
    digest = atomic_save(path, value, stages=STAGE_SET, checks=CHECKS)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(CheckpointError, match="checkpoint_symlink_forbidden"):
        atomic_save(link, value, stages=STAGE_SET, checks=CHECKS)
    path.chmod(0o644)
    with pytest.raises(CheckpointError, match="checkpoint_file_unsafe"):
        load_verified(path, expected_digest=digest, expected_database=value["database"],
                      stages=STAGE_SET, checks=CHECKS)


def test_only_allowlisted_ids_and_checks_written_before_transport(tmp_path):
    value, path = snapshot(), tmp_path / "checkpoint.json"
    report = {"checks": [], "workspace_ids": [str(uuid4())],
              "key": "PRIVATE_CREDENTIAL", "prompt": "PRIVATE_PROMPT",
              "runtime_diagnostics": {"raw": "PRIVATE_MODEL"}}
    budget = RequestBudget(3)
    emitted = []
    writer = CheckpointWriter(path, value["database"], budget, report,
                              stages=STAGE_SET, checks=CHECKS, emit=emitted.append)
    budget.before_request = writer.before_request
    record = budget.reserve()
    persisted = json.loads(path.read_text())
    assert persisted["state"] == "pending"
    assert persisted["requests_reserved"] == record["number"] == 1
    assert "PRIVATE" not in path.read_text() + json.dumps(emitted)
    report["checks"].append({"check": "safe_gate", "passed": True, "raw": "PRIVATE_BODY"})
    writer.save("gate_passed")
    assert json.loads(path.read_text())["passed_checks"] == ["safe_gate"]
    budget.reserve()
    interrupted = json.loads(path.read_text())
    assert interrupted["state"] == "pending" and interrupted["requests_reserved"] == 2
    assert interrupted["continuous_chain_passed"] is False
    assert interrupted["resume_allowed"] is False


def test_failed_atomic_replace_preserves_previous_gate_and_blocks_request(tmp_path):
    value, path = snapshot(), tmp_path / "checkpoint.json"
    atomic_save(path, value, stages=STAGE_SET, checks=CHECKS)
    old = path.read_bytes()
    budget = RequestBudget(3)
    writer = CheckpointWriter(path, value["database"], budget, {"checks": [], "workspace_ids": []},
                              stages=STAGE_SET, checks=CHECKS)
    budget.before_request = writer.before_request
    with (
        patch("workbench_qa_checkpoint.os.replace", side_effect=OSError("interrupted")),
        pytest.raises(OSError),
    ):
        budget.reserve()
        pytest.fail("Transport must not run after failed checkpoint persistence")
    assert path.read_bytes() == old
    assert list(tmp_path.iterdir()) == [path]


def test_short_cli_requires_permission_without_opening_database():
    output = StringIO()
    with patch.object(short, "make_checkpoint") as db, redirect_stdout(output):
        assert short.main(["--stage", "delete", "--checkpoint", "/tmp/never-opened-qa.json"]) == 1
    db.assert_not_called()
    report = json.loads(output.getvalue())
    assert report["requests_attempted"] == 0
    assert report["error_code"] == "live_permission_required"
    assert report["continuous_chain_passed"] is False


def test_continuous_checkpoint_is_opt_in_and_permission_precedes_database():
    output = StringIO()
    with patch.object(crud, "create_writer") as writer, redirect_stdout(output):
        assert crud.main(["--checkpoint-path", "/tmp/never-opened-qa.json"]) == 1
    writer.assert_not_called()
    assert json.loads(output.getvalue())["requests_attempted"] == 0


def test_shared_journey_hooks_keep_interrupted_continuous_gate_evidence(tmp_path):
    path, value = tmp_path / "continuous.json", snapshot()
    report = {"checks": [], "workspace_ids": [], "passed": False}
    budget = RequestBudget(30)
    writer = CheckpointWriter(path, value["database"], budget, report,
        stages=STAGES, checks=CONTINUOUS_CHECKS, scope="continuous_synthetic_chain")
    budget.before_request = writer.before_request
    journey = crud.CrudJourney(None, None, None, report, "offline")
    journey.checkpoint = writer
    journey.stage = "asset_query"
    budget.reserve()
    first = min(CONTINUOUS_CHECKS)
    journey.passed(first)
    gate = json.loads(path.read_text())
    assert gate["passed_checks"] == [first] and gate["state"] == "gate_passed"
    journey.stage = "rewrite_request"
    budget.reserve()  # Simulate interruption before this paid stage could return.
    pending = json.loads(path.read_text())
    assert pending["passed_checks"] == [first]
    assert pending["requests_reserved"] == 2 and pending["state"] == "pending"
    assert pending["continuous_chain_passed"] is False
    assert pending["resume_allowed"] is False
    for name in sorted(CONTINUOUS_CHECKS - {first}):
        journey.passed(name)
    with pytest.raises(CheckpointError, match="checkpoint_continuous_not_complete"):
        writer.save("finished")
    report["passed"] = True  # Unit exercise only; never exported as live-run evidence.
    writer.save("finished")
    assert json.loads(path.read_text())["continuous_chain_passed"] is True


def test_continuous_driver_passes_checkpoint_to_actual_base_executor():
    seen = {}

    async def observe(*args, **kwargs):
        seen.update(kwargs)
        assert base.Journey is crud.CrudJourney

    budget = RequestBudget(3)
    budget.checkpoint = object()
    with patch.object(base, "execute", observe):
        asyncio.run(crud.execute_crud("offline", "offline", budget, {}, "/tmp/offline"))
    assert seen == {"checkpoint": budget.checkpoint}


def test_short_stages_reuse_exact_existing_domain_assertions():
    assert short.EXPECTED == {"collection": 1, "query_selection": 1, "rewrite": 3, "delete": 1}
    assert short.ShortCrudJourney.canonical_rewrite is base.Journey.canonical_rewrite
    assert short.ShortCrudJourney.collection_proposal is crud.CrudJourney.collection_proposal
    assert short.ShortCrudJourney.prepare_delete is crud.CrudJourney.prepare_delete
    assert short.ShortCrudJourney.passed is base.Journey.passed
