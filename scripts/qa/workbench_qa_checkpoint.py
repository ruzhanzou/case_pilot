"""Private, atomic QA evidence checkpoints. NOT a database resume mechanism.

Only fresh synthetic databases marked by the rootless wrapper are accepted.
A checksum detects corruption, not malicious rewriting; load requires a digest
from a separate trusted gate log. No checkpoint can authorize paid calls or DB
restart. Interrupted pending stages remain UNKNOWN, never implicitly passed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from uuid import UUID, uuid4

SCHEMA = 1
CONTINUOUS_CHECKS = frozenset({
    "live_nl_collection_entity_query_is_read_only",
    "live_nl_collection_create_exact_approval_and_select",
    "live_nl_attachment_multiturn_creates_exact_two_cases",
    "live_nl_collection_rename_preserves_entity_and_case_membership",
    "live_nl_priority_exclusion_selects_only_created_cases",
    "live_nl_no_match_request_is_non_mutating",
    "live_nl_scoped_case_update_preserves_all_other_cases",
    "live_nl_target_switch_blocks_old_delete_preview",
    "live_nl_soft_delete_exact_approval_replay_and_guard_preservation",
})
SCOPES = {"independent_short_synthetic_stage", "continuous_synthetic_chain"}
IDENTITY_KEYS = {"system_identifier", "database_oid", "server_version_num",
                 "schema_revision", "synthetic_id", "source_commit"}
FIELDS = {"schema_version", "run_id", "scope", "database", "stage", "state",
          "passed_checks", "workspace_ids", "requests_reserved", "request_limit",
          "continuous_chain_passed", "resume_allowed"}


class CheckpointError(ValueError):
    pass


def _uuid(value):
    try:
        valid = isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        valid = False
    if not valid:
        raise CheckpointError("checkpoint_identity_invalid")
    return value


def database_identity(connection, source_commit):
    """Read only safe server identity; never DSNs, paths, credentials or content."""
    from sqlalchemy import text

    values = {
        "system_identifier": str(connection.scalar(text(
            "SELECT system_identifier::text FROM pg_control_system()"))),
        "database_oid": str(connection.scalar(text(
            "SELECT oid::text FROM pg_database WHERE datname = current_database()"))),
        "server_version_num": str(connection.scalar(text("SHOW server_version_num"))),
        "schema_revision": str(connection.scalar(text("SELECT version_num FROM alembic_version"))),
        "synthetic_id": str(connection.scalar(text("SELECT id FROM casepilot_qa_identity"))),
        "source_commit": source_commit,
    }
    validate_identity(values)
    return values


def validate_identity(value):
    if not isinstance(value, dict) or set(value) != IDENTITY_KEYS:
        raise CheckpointError("checkpoint_database_identity_invalid")
    if not all(isinstance(item, str) for item in value.values()):
        raise CheckpointError("checkpoint_database_identity_invalid")
    for name in ("system_identifier", "database_oid", "server_version_num"):
        if not isinstance(value[name], str) or not re.fullmatch(r"[0-9]{1,24}", value[name]):
            raise CheckpointError("checkpoint_database_identity_invalid")
    if not re.fullmatch(r"[a-f0-9]{40,64}", value["source_commit"]):
        raise CheckpointError("checkpoint_source_revision_invalid")
    if not re.fullmatch(r"[0-9]{8}_[0-9]{4}", value["schema_revision"]):
        raise CheckpointError("checkpoint_schema_revision_invalid")
    _uuid(value["synthetic_id"])


def validate_checkpoint(value, *, stages, checks):
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise CheckpointError("checkpoint_fields_invalid")
    if value["schema_version"] != SCHEMA or value["scope"] not in SCOPES:
        raise CheckpointError("checkpoint_schema_invalid")
    _uuid(value["run_id"])
    validate_identity(value["database"])
    if value["stage"] not in stages or value["state"] not in {"pending", "gate_passed", "finished"}:
        raise CheckpointError("checkpoint_stage_invalid")
    if (not isinstance(value["passed_checks"], list)
            or not all(isinstance(item, str) for item in value["passed_checks"])
            or len(value["passed_checks"]) != len(set(value["passed_checks"]))
            or not set(value["passed_checks"]) <= checks):
        raise CheckpointError("checkpoint_checks_invalid")
    if not isinstance(value["workspace_ids"], list) or len(value["workspace_ids"]) > 20:
        raise CheckpointError("checkpoint_ids_invalid")
    for identifier in value["workspace_ids"]:
        _uuid(identifier)
    if (type(value["request_limit"]) is not int or not 1 <= value["request_limit"] <= 200
            or type(value["requests_reserved"]) is not int
            or not 0 <= value["requests_reserved"] <= value["request_limit"]):
        raise CheckpointError("checkpoint_budget_invalid")
    complete = (value["scope"] == "continuous_synthetic_chain" and value["state"] == "finished"
                and set(value["passed_checks"]) == CONTINUOUS_CHECKS)
    if value["continuous_chain_passed"] is not complete or value["resume_allowed"] is not False:
        raise CheckpointError("checkpoint_resume_forbidden")


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def atomic_save(path, value, *, stages, checks):
    validate_checkpoint(value, stages=stages, checks=checks)
    path = Path(path)
    if path.is_symlink():
        raise CheckpointError("checkpoint_symlink_forbidden")
    data = _encoded(value)
    descriptor, temporary = tempfile.mkstemp(prefix=".qa-checkpoint-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return hashlib.sha256(data).hexdigest()


def load_verified(path, *, expected_digest, expected_database, stages, checks):
    """Evidence inspection only; even verified checkpoints never enable resume."""
    path = Path(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 16384 or info.st_mode & 0o077:
            raise CheckpointError("checkpoint_file_unsafe")
        data = os.read(descriptor, 16385)
    finally:
        os.close(descriptor)
    if hashlib.sha256(data).hexdigest() != expected_digest:
        raise CheckpointError("checkpoint_digest_mismatch")
    value = json.loads(data)
    validate_checkpoint(value, stages=stages, checks=checks)
    if value["database"] != expected_database:
        raise CheckpointError("checkpoint_database_mismatch")
    return value


class CheckpointWriter:
    def __init__(self, path, identity, budget, report, *, stages, checks, emit=None,
                 scope="independent_short_synthetic_stage"):
        self.scope = scope
        self.path, self.identity, self.budget, self.report = path, identity, budget, report
        self.stages, self.checks, self.emit = frozenset(stages), frozenset(checks), emit
        self.run_id, self.stage = str(uuid4()), "setup"
        self.lock = threading.Lock()
        self.maximum_reserved = 0

    def save(self, state="pending"):
        with self.lock:
            self.maximum_reserved = max(self.maximum_reserved, self.budget.count)
            value = {
                "schema_version": SCHEMA, "run_id": self.run_id,
                "scope": self.scope, "database": self.identity,
                "stage": self.stage, "state": state,
                "passed_checks": [item["check"] for item in self.report.get("checks", [])
                                  if item.get("passed") is True],
                "workspace_ids": list(self.report.get("workspace_ids", [])),
                "requests_reserved": self.maximum_reserved, "request_limit": self.budget.limit,
                "continuous_chain_passed": False, "resume_allowed": False,
            }
            if self.scope == "continuous_synthetic_chain" and state == "finished":
                if self.report.get("passed") is not True:
                    raise CheckpointError("checkpoint_continuous_not_complete")
                value["continuous_chain_passed"] = set(value["passed_checks"]) == CONTINUOUS_CHECKS
            digest = atomic_save(self.path, value, stages=self.stages, checks=self.checks)
            if self.emit:
                self.emit({"event": "qa_checkpoint", "sha256": digest,
                           "stage": self.stage, "state": state,
                           "requests_reserved": self.maximum_reserved})
            return digest

    def before_request(self, _record):
        self.save("pending")


def create_writer(path, root, budget, report, *, stages, checks, emit=None,
                  scope="independent_short_synthetic_stage"):
    sys.path[:0] = [str(root / "apps/api/src"), str(root / "apps/agent/src")]
    from casepilot_api.database import get_engine

    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    with get_engine().connect() as connection:
        identity = database_identity(connection, revision)
    return CheckpointWriter(path, identity, budget, report, stages=stages, checks=checks,
                            emit=emit, scope=scope)
