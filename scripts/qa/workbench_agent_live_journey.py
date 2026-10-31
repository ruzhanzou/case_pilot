#!/usr/bin/env python3
"""Opt-in synthetic real API/Agents SDK/worker/domain journeys (no browser claim).

Requires lead-provided migrated PostgreSQL/Redis. No credential or infra setup.
Only transport client construction and task dispatch are scoped: provider outputs,
model decisions, actual workers, domain validation and approval APIs remain real.
All fixtures are synthetic. Raw model responses/arguments are never logged; only bounded,
redacted assistant display clarification may enter private diagnostic evidence.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
import threading
from collections import deque
from contextlib import ExitStack
from io import BytesIO
from pathlib import Path
from time import monotonic
from unittest.mock import patch
from uuid import uuid4

import httpx
from workbench_agent_live_acceptance import (
    BASE_URL,
    STAGES,
    ROOT,
    RequestBudget,
    bounded_clients,
    disable_sensitive_logging,
    emit_json,
    exception_name,
    parser,
    read_key,
    set_stage,
    synthetic_png,
)
from workbench_domain_diagnostics import safe_domain_failure
from workbench_safe_diagnostics import safe_structured_failure

os.environ["ORT_DISABLE_TELEMETRY"] = "1"
TASKS = {
    "casepilot.agent.draft_brief": "draft_test_brief",
    "casepilot.agent.generate": "generate_test_cases",
    "casepilot.agent.rewrite_batch": "rewrite_test_cases_batch",
    "casepilot.agent.index_knowledge_source": "index_knowledge_source",
}
TOOLS = frozenset(
    {
        "plan_work",
        "query_collections",
        "query_candidates",
        "select_assets",
        "select_collection",
        "query_uploaded_cases",
        "prepare_generation",
        "prepare_review",
        "prepare_dedup",
        "prepare_coverage",
        "answer_knowledge",
        "list_collections",
        "query_assets",
        "query_cases",
        "select_sources",
        "preview_uploaded_cases",
        "prepare_reuse",
        "get_workspace_context",
        "read_attachment_evidence",
        "plan_test_points",
        "generate_cases",
        "prepare_rewrite",
        "prepare_delete",
        "review_cases",
        "find_duplicates",
        "analyze_coverage",
        "answer_from_knowledge",
        "create_collection",
        "rename_collection",
        "delete_collection",
        "prepare_delete_collection",
    }
)
SAFE_CODES = frozenset(
    {
        "agent_final_effect_invalid",
        "agent_final_receipt_invalid",
        "agent_final_receipt_required",
        "agent_model_contract_invalid",
        "agent_output_validation_failed",
        "agent_sdk_configuration_invalid",
        "agent_stopped",
        "agent_configuration_missing",
        "agent_tool_failed",
        "agent_provider_error",
        "agent_provider_connection_error",
        "agent_provider_timeout",
        "agent_provider_incomplete_response",
        "agent_provider_request_rejected",
        "agent_provider_authentication_failed",
        "agent_provider_access_denied",
        "agent_endpoint_or_model_not_found",
        "agent_model_not_enabled",
        "agent_provider_rate_limited",
        "agent_provider_unavailable",
        "agent_tool_budget_exhausted",
        "agent_turn_budget_exhausted",
        "agent_invalid_tool_call",
        "agent_tool_call_id_conflict",
        "agent_cancelled",
        "agent_empty_response",
        "tool_not_allowed",
        "invalid_tool_arguments",
        "agent_turn_failed",
        "workbench_selection_changed",
        "workbench_scope_requires_selection",
        "workbench_approval_binding_required",
        "workbench_approval_binding_delta_invalid",
        "workbench_approval_delta_outside_artifact",
        "workbench_approval_artifact_changed",
        "workbench_approval_destination_invalid",
        "workbench_approval_effect_mismatch",
        "workbench_approval_version_changed",
        "workbench_run_binding_changed",
        "workbench_run_source_changed",
        "workbench_run_paused",
        "workbench_question_in_progress",
        "workbench_continuation_obsolete",
        "conversation_busy",
        "test_brief_version_changed",
        "generation_destination_changed",
        "generation_new_collection_required",
        "generation_asset_selection_not_pending",
        "generation_asset_confirmation_required",
        "attachment_not_ready_or_expired",
        "conversation_collection_locked",
    }
)


NATURAL_PRIORITIES = (("A", ("P1", "P2")), ("B", ("P2", "P1")))


class JourneyFailure(Exception):
    pass


def require(condition, code):
    if not condition:
        raise JourneyFailure(code)


def preview_requires_confirmation(turn, operation):
    confirmation = (
        turn.get("assistant_message", {})
        .get("metadata", {})
        .get("modification_confirmation")
    )
    if confirmation:
        return True
    action = turn.get("action", {})
    require(
        bool(
            action.get("job_id")
            or action.get("change_set_id")
            or operation.get("related_job_id")
            or operation.get("related_change_set_id")
        ),
        "selection_rewrite_confirmation_missing",
    )
    return False


def validate_preview_scope(preview, cases):
    items = preview.get("items", [])
    require(
        preview.get("status") == "ready" and len(items) == len(cases),
        "selection_preview_scope_invalid",
    )
    require(
        {item.get("test_case_id") for item in items} == set(cases),
        "selection_preview_scope_invalid",
    )
    for item in items:
        case = cases[item["test_case_id"]]
        require(
            item.get("target_type") == "formal"
            and item.get("ref") == case["id"]
            and item.get("base_revision_id") == case["current_revision_id"]
            and item.get("operation") in {None, "update"},
            "selection_preview_scope_invalid",
        )


def validate_priority_diff(preview, priority):
    require(bool(preview.get("items")), "rewrite_priority_diff_missing")
    for item in preview["items"]:
        priority_changes = [
            diff
            for diff in item.get("field_diff", [])
            if diff.get("field") == "priority"
        ]
        require(
            len(priority_changes) == 1
            and priority_changes[0].get("after") == priority
            and priority_changes[0].get("before") != priority,
            "rewrite_priority_diff_missing",
        )


def validate_candidate_preview(preview, candidate):
    items = preview.get("items", [])
    require(
        preview.get("status") == "ready" and len(items) == 1,
        "spreadsheet_preview_not_ready",
    )
    item = items[0]
    require(
        item.get("target_type") == "candidate"
        and item.get("ref") == candidate["ref"]
        and item.get("base_version") == candidate["version"]
        and item.get("operation") in {None, "update"},
        "spreadsheet_preview_scope_invalid",
    )


def validate_operation_binding(operation, state, collection):
    payload = operation.get("payload") or {}
    require(
        type(payload.get("selection_version")) is int
        and payload["selection_version"] == state["version"]
        and payload.get("destination_collection_id") == collection,
        "selection_proposal_not_bound",
    )


def created_destination(before, after, name):
    old = {item["id"]: item["name"] for item in before}
    new = {item["id"]: item["name"] for item in after}
    added = set(new) - set(old)
    require(
        len(added) == 1
        and len(new) == len(after)
        and all(new.get(key) == value for key, value in old.items()),
        "reuse_destination_mismatch",
    )
    identifier = next(iter(added))
    require(new[identifier] == name, "reuse_destination_mismatch")
    return {"id": identifier, "name": name}


def exact_candidate_commit(candidates):
    require(bool(candidates), "adoption_candidate_id_missing")
    identifiers, versions = [], {}
    for candidate in candidates:
        item = candidate_commit_payload(candidate)
        identifier = item["candidate_ids"][0]
        require(identifier not in versions, "adoption_candidate_id_missing")
        identifiers.append(identifier)
        versions.update(item["candidate_versions"])
    return {"candidate_ids": identifiers, "candidate_versions": versions}


def single_prepared_operation(turn):
    operations = (turn.get("operation_plan") or {}).get("operations", [])
    require(
        len(operations) == 1 and bool(operations[0].get("id")),
        "selection_proposal_not_bound",
    )
    preview_requires_confirmation(turn, operations[0])
    return operations[0]


def case_audit_ids(case_id):
    """Scoped, read-only audit evidence; IDs are never emitted."""
    from uuid import UUID

    from casepilot_api.database import get_session_factory
    from casepilot_api.models import AuditEvent
    from sqlalchemy import select

    with get_session_factory()() as db:
        return frozenset(
            db.scalars(
                select(AuditEvent.id).where(AuditEvent.resource_id == UUID(case_id))
            )
        )


def safe_code(value):
    return (
        value
        if isinstance(value, str) and value in SAFE_CODES
        else (None if value is None else "unrecognized")
    )


def runtime_diagnostics(metadata):
    events = metadata.get("events")
    observed, counts = [], []
    terminal = None
    completion = None
    final_kind, final_effect = None, None
    for event in events[-100:] if isinstance(events, list) else []:
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind in {
            "run_failed",
            "run_completed",
            "run_cancelled",
            "run_awaiting_input",
        }:
            terminal = kind
            if "completion" in event:
                from casepilot_api.workbench_tool_diagnostics import (
                    safe_tool_diagnostic,
                )
                completion = safe_tool_diagnostic(event["completion"])
            final_kind = (
                event.get("final_kind")
                if isinstance(event.get("final_kind"), str)
                and event.get("final_kind") in {"answer", "clarify", "action"}
                else None
            )
            final_effect = (
                event.get("final_effect")
                if isinstance(event.get("final_effect"), str)
                and event.get("final_effect") in {"none", "read", "prepare"}
                else None
            )
        if kind in {
            "tool_started",
            "tool_completed",
            "tool_failed",
            "tool_rejected",
            "tool_replayed",
        }:
            name = event.get("tool")
            name = name if isinstance(name, str) and name in TOOLS else "unrecognized"
            item = {"type": kind, "tool": name}
            if kind in {"tool_rejected", "tool_failed"} and "diagnostic" in event:
                from casepilot_api.workbench_tool_diagnostics import (
                    safe_tool_diagnostic,
                )
                item["diagnostic"] = safe_tool_diagnostic(event["diagnostic"])
            observed.append(item)
            count = event.get("returned_count")
            if kind == "tool_completed" and type(count) is int and 0 <= count <= 10000:
                measured = {"tool": name, "returned_count": count}
                for flag in ("truncated", "has_more"):
                    if type(event.get(flag)) is bool:
                        measured[flag] = event[flag]
                counts.append(measured)
    if "completion" in metadata:
        from casepilot_api.workbench_tool_diagnostics import (
            safe_tool_diagnostic,
        )
        completion = safe_tool_diagnostic(metadata["completion"])
    return {
        **({"completion": completion} if completion is not None else {}),
        "runtime_error_code": safe_code(metadata.get("error_code")),
        "terminal_event": terminal,
        "final_kind": final_kind,
        "final_effect": final_effect,
        "tool_events": observed,
        "query_returned_counts": counts or None,
    }


class Dispatch:
    def __init__(self):
        self.queue, self.seen, self.executed = deque(), set(), 0
        self.lock = threading.Lock()

    def enqueue(self, db, name, args, **kwargs):
        require(name in TASKS and len(args) == 1, "unexpected_task_dispatch")
        item = (name, str(args[0]))
        with self.lock:
            if item not in self.seen:
                self.seen.add(item)
                self.queue.append(item)

    async def drain(self, tasks):
        while self.queue:
            require(self.executed < 30, "worker_task_budget_exhausted")
            name, identifier = self.queue.popleft()
            result = await asyncio.to_thread(
                getattr(tasks, TASKS[name]).run, identifier
            )
            self.executed += 1
            require(
                not isinstance(result, dict)
                or result.get("status") not in {"failed", "cancelled"},
                "worker_task_failed",
            )


def semantic_case_payload(title, denied):
    return {
        "title": title,
        "module": "合成认证",
        "priority": "P2",
        "case_type": "functional",
        "description": "验证码不正确时禁止登录" if denied else "验证码正确时允许登录",
        "preconditions": ["合成用户已注册，尚未登录"],
        "steps": [
            {
                "action": "输入不正确的验证码后提交"
                if denied
                else "输入有效验证码后提交",
                "expected": "提示验证码错误，拒绝登录，用户仍未认证"
                if denied
                else "认证通过，成功进入用户首页",
            }
        ],
    }


def turn_has_tool(turn, tool):
    metadata = (
        turn.get("assistant_message", {}).get("metadata", {}).get("workbench_agent", {})
    )
    return any(
        isinstance(item, dict) and item.get("tool") == tool
        for item in metadata.get("receipts", [])
    )


def verify_semantic_read_state(workspace, collection, allowed_ids, forbidden_ids):
    require(
        workspace.get("collection_id") == collection, "semantic_destination_changed"
    )
    require(
        not workspace.get("candidates") and not workspace.get("operation_history"),
        "semantic_query_created_write_proposal",
    )
    catalog = (
        workspace.get("context", {}).get("workbench_plan", {}).get("source_catalog", {})
    )
    require(
        not {f"asset:{identifier}" for identifier in forbidden_ids}.intersection(
            catalog
        ),
        "semantic_query_wrong_scope",
    )
    require(
        {ref for ref in catalog if ref.startswith("asset:")}
        <= {f"asset:{identifier}" for identifier in allowed_ids},
        "semantic_query_wrong_scope",
    )


def synthetic_spreadsheet():
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "历史登录"
    sheet.append(
        ["用例编号", "用例标题", "模块", "优先级", "前置条件", "操作步骤", "预期结果"]
    )
    sheet.append(
        [
            "SYNTHETIC-1",
            "验证码登录成功",
            "登录",
            "P2",
            "测试账号已注册",
            "输入有效验证码并登录",
            "显示登录成功",
        ]
    )
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def mixed_gap_case(adopted, source_id, forbidden):
    require(len(adopted) == 2, "reuse_adoption_quantity_mismatch")
    require(
        sum(case["id"] == source_id for case in adopted) == 1,
        "original_reuse_not_linked",
    )
    gaps = [case for case in adopted if case["id"] != source_id]
    require(len(gaps) == 1 and gaps[0]["id"] not in forbidden, "gap_identity_invalid")
    content = json.dumps(
        {"title": gaps[0].get("title"), "steps": gaps[0].get("steps")},
        ensure_ascii=False,
    ).lower()
    require(
        any(word in content for word in ("错误", "无效", "invalid")),
        "new_gap_error_case_missing",
    )
    return gaps[0]


def candidate_commit_payload(candidate):
    require(
        type(candidate.get("version")) is int and candidate["version"] > 0,
        "adoption_candidate_version_missing",
    )
    require(bool(candidate.get("id")), "adoption_candidate_id_missing")
    return {
        "candidate_ids": [candidate["id"]],
        "candidate_versions": {candidate["id"]: candidate["version"]},
    }


def verify_adopted_candidate_selection(before, after, ref):
    def selected(state):
        return any(
            item.get("candidate_ref") == ref or item.get("ref") == "candidate:" + ref
            for item in state.get("items", [])
        )

    require(selected(before), "adoption_candidate_not_canonically_selected")
    require(
        type(before.get("version")) is int
        and type(after.get("version")) is int
        and after["version"] > before["version"],
        "adoption_selection_version_not_advanced",
    )
    require(not selected(after), "adoption_left_stale_candidate_selection")


def validate_selection(workspace, expected, collection, *, previous=None):
    state = workspace.get("context", {}).get("workbench_selection", {})
    require(
        type(state.get("version")) is int and state["version"] > 0,
        "selection_version_missing",
    )
    if previous is not None:
        require(state["version"] > previous, "selection_version_not_advanced")
    require(
        state.get("active_collection_id") == collection, "selection_collection_mismatch"
    )
    items = state.get("items", [])
    require(len(items) == len(expected), "selection_count_mismatch")
    actual = {item.get("case_id"): item for item in items}
    require(set(actual) == set(expected), "selection_identity_mismatch")
    for identifier, case in expected.items():
        item = actual[identifier]
        require(
            item.get("kind") == "asset" and item.get("ref") == f"asset:{identifier}",
            "selection_reference_mismatch",
        )
        require(
            item.get("version") == str(case["current_revision_id"]),
            "selection_revision_mismatch",
        )
        require(
            collection in item.get("collection_ids", []),
            "selection_membership_mismatch",
        )
    return state


def safe_turn_evidence(response, workspace, request, stage, secret=""):
    """Only synthetic user-visible clarification and bounded state, never raw model data."""
    state = workspace.get("context", {}).get("workbench_selection")
    state = state if isinstance(state, dict) else {}
    metadata = response.get("assistant_message", {}).get("metadata", {}).get("workbench_agent", {})
    diagnostics = runtime_diagnostics(metadata)
    result = {
        "stage": stage if stage in STAGES else "unrecognized",
        "canonical_present": bool(state),
        "canonical_version": state.get("version") if type(state.get("version")) is int else None,
        "canonical_count": min(len(state.get("items", [])), 100),
        "request_selection_version": request.get("selection_version")
            if type(request.get("selection_version")) is int else None,
        "request_case_count": min(len(set(request.get("target_case_ids", []))), 100),
        "target_scope": request.get("target_scope")
            if request.get("target_scope") in {"selected", "inferred"} else None,
        "run_status": metadata.get("status") if metadata.get("status") in {
            "completed", "awaiting_input", "failed", "cancelled", "running"} else None,
        "final_kind": diagnostics["final_kind"],
    }
    if diagnostics["final_kind"] in {"clarify", "answer"}:
        text = response.get("assistant_message", {}).get("content")
        if isinstance(text, str):
            if secret:
                text = text.replace(secret, "[REDACTED]")
            text = re.sub(r"(?i)(?:bearer\s+|sk-)[^\s,;]+", "[REDACTED]", text)
            text = re.sub(r"[A-Za-z0-9_+/=-]{24,}", "[REDACTED]", text)
            text = " ".join(text.split())[:600]
            result["display_clarification" if diagnostics["final_kind"] == "clarify"
                   else "display_answer"] = text
    return result


class Journey:
    def __init__(self, client, dispatch, tasks, report, model):
        self.client, self.dispatch, self.tasks = client, dispatch, tasks
        self.report, self.model = report, model
        self._stage = "setup"
        self.last_check = monotonic()

    @property
    def stage(self):
        return self._stage

    @stage.setter
    def stage(self, stage):
        self._stage = stage
        set_stage(stage)
        checkpoint = getattr(self, "checkpoint", None)
        if checkpoint is not None:
            checkpoint.stage = stage
            checkpoint.save("pending")

    def passed(self, name):
        now = monotonic()
        self.report["checks"].append(
            {
                "check": name,
                "passed": True,
                "elapsed_seconds": round(now - self.last_check, 3),
            }
        )
        self.last_check = now
        checkpoint = getattr(self, "checkpoint", None)
        if checkpoint is not None:
            checkpoint.save("gate_passed")

    async def request(self, method, path, **kwargs):
        response = await self.client.request(method, "/api/v1" + path, **kwargs)
        if response.status_code not in {200, 201, 202}:
            self.report["last_api_status"] = response.status_code
            try:
                self.report["api_error_code"] = safe_code(response.json().get("detail"))
            except (ValueError, AttributeError):
                self.report["api_error_code"] = "unrecognized"
            raise JourneyFailure("api_request_failed")
        return response.json()

    async def post(self, path, body):
        return await self.request("POST", path, json=body)

    async def workspace(self, cid):
        return await self.request("GET", f"/conversations/{cid}")

    async def message(self, cid, content, **kwargs):
        before = await self.workspace(cid)
        response = await self.post(
            f"/conversations/{cid}/messages",
            {
                "content": content,
                "client_request_id": str(uuid4()),
                "model_id": self.model,
                **kwargs,
            },
        )
        metadata = (
            response.get("assistant_message", {})
            .get("metadata", {})
            .get("workbench_agent", {})
        )
        self.report["runtime_diagnostics"] = runtime_diagnostics(metadata)
        self.report["last_turn_evidence"] = safe_turn_evidence(
            response, before, kwargs, self.stage, getattr(self, "_redact_secret", ""))
        emit_json({"event": "synthetic_turn_observation", **self.report["last_turn_evidence"]})
        require(bool(metadata), "workbench_agent_not_used")
        require(
            metadata.get("agent_turn_status", metadata.get("status"))
            not in {"failed", "cancelled"},
            "workbench_agent_failed",
        )
        return response

    async def create_workspace(self, sid, name):
        collection = await self.post(f"/spaces/{sid}/collections", {"name": name})
        conversation = await self.post(
            "/conversations", {"collection_id": collection["id"]}
        )
        self.report["workspace_ids"].append(conversation["id"])
        return conversation["id"], collection["id"]

    async def assert_revisions(self, snapshots, *, changed_id=None):
        for identifier, revision in snapshots.items():
            current = await self.request("GET", f"/test-cases/{identifier}")
            if identifier != changed_id:
                require(
                    current["current_revision_id"] == revision,
                    "unselected_revision_changed",
                )

    async def run(self, scenarios):
        self.stage = "setup"
        user = await self.post(
            "/auth/register",
            {
                "email": f"live-synthetic-{uuid4().hex}@casepilot.test",
                "display_name": "Synthetic live QA",
                "password": "SyntheticFixture123!",
            },
        )
        sid = user["spaces"][0]["id"]
        if "asset_reuse" in scenarios:
            await self.asset_reuse(sid)
        if "canonical_rewrite" in scenarios:
            await self.canonical_rewrite(sid)
        if "semantic_selection" in scenarios:
            await self.semantic_selection(sid)
        if "natural_selection" in scenarios:
            await self.natural_selection(sid)
        if "generation" in scenarios:
            await self.generation(sid)
        if "spreadsheet" in scenarios:
            await self.spreadsheet(sid)
        if "image" in scenarios:
            await self.image(sid)

    async def seed_case(self, collection, title, priority="P2"):
        result = await self.post(
            f"/collections/{collection}/test-cases",
            {
                "title": title,
                "module": "合成登录",
                "priority": priority,
                "case_type": "functional",
                "preconditions": ["合成账号已注册"],
                "steps": [
                    {"action": "输入有效验证码并登录", "expected": "显示登录成功"}
                ],
            },
        )
        self.report["synthetic_seeded_cases"] = (
            self.report.get("synthetic_seeded_cases", 0) + 1
        )
        return result

    async def selected_preview(self, cid, case, collection, priority, snapshots):
        return await self.scoped_preview(
            cid, {case["id"]: case}, collection, priority, snapshots
        )

    async def compute_prepared_preview(self, cid, turn):
        """Compute only; final review/apply remains an independent caller action."""
        operation = single_prepared_operation(turn)
        if preview_requires_confirmation(turn, operation):
            self.stage = "rewrite_confirm"
            await self.post(
                f"/conversation-operations/{operation['id']}/resume",
                {"confirm_modification": True},
            )
        self.stage = "rewrite_worker"
        await self.dispatch.drain(self.tasks)
        workspace = await self.workspace(cid)
        history = next(
            (
                item
                for item in workspace.get("operation_history", [])
                if item["id"] == operation["id"]
            ),
            {},
        )
        change = history.get("related_change_set_id")
        require(bool(change), "selection_preview_missing")
        return change, await self.request("GET", f"/case-change-sets/{change}")

    async def scoped_preview(self, cid, cases, collection, priority, snapshots):
        self.stage = "rewrite_request"
        state = validate_selection(await self.workspace(cid), cases, collection)
        turn = await self.message(
            cid,
            f"只把当前选中的{len(cases)}条用例优先级改为{priority}，保留标题和步骤。"
            "不要修改其他用例，先准备改写预览，最终应用必须等待我明确确认。",
        )
        operations = turn.get("operation_plan", {}).get("operations", [])
        require(len(operations) == 1, "selection_proposal_not_bound")
        validate_operation_binding(operations[0], state, collection)
        operation = operations[0]["id"]
        await self.assert_revisions(snapshots)
        if preview_requires_confirmation(turn, operations[0]):
            self.stage = "rewrite_confirm"
            await self.post(
                f"/conversation-operations/{operation}/resume",
                {"confirm_modification": True},
            )
        self.stage = "rewrite_worker"
        await self.dispatch.drain(self.tasks)
        workspace = await self.workspace(cid)
        item = next(
            (
                item
                for item in workspace["operation_history"]
                if item["id"] == operation
            ),
            {},
        )
        change = item.get("related_change_set_id")
        require(bool(change), "selection_preview_missing")
        preview = await self.request("GET", f"/case-change-sets/{change}")
        validate_preview_scope(preview, cases)
        validate_priority_diff(preview, priority)
        validate_selection(workspace, cases, collection)
        await self.assert_revisions(snapshots)
        return change, state["version"]

    async def apply_selected(
        self, cid, case, collection, priority, snapshots, change, version
    ):
        self.stage = "rewrite_apply"
        await self.post(
            f"/case-change-sets/{change}/apply",
            {
                "selection_version": version,
                "review_refs": [case["id"]],
                "accepted_fields": {case["id"]: ["priority"]},
            },
        )
        after = await self.request("GET", f"/test-cases/{case['id']}")
        require(
            after["priority"] == priority
            and after["current_revision_id"] != case["current_revision_id"],
            "selection_rewrite_not_applied",
        )
        require(
            after["title"] == case["title"] and after["steps"] == case["steps"],
            "selection_preservation_failed",
        )
        await self.assert_revisions(snapshots, changed_id=case["id"])
        snapshots[case["id"]] = after["current_revision_id"]
        state = validate_selection(
            await self.workspace(cid), {case["id"]: after}, collection, previous=version
        )
        require(
            state.get("changed_by") == "approved_apply",
            "selection_own_apply_not_refreshed",
        )
        return after, state

    async def canonical_rewrite(self, sid):
        self.stage = "setup"
        cid, collection = await self.create_workspace(
            sid, "Synthetic canonical rewrite"
        )
        chosen = [
            await self.seed_case(collection, f"SYNTHETIC-CANONICAL-{index}", "P2")
            for index in (1, 2)
        ]
        outside = await self.seed_case(collection, "SYNTHETIC-UNSELECTED-GUARD", "P0")
        foreign, decoy = await self.foreign_fixture("SYNTHETIC-FOREIGN-CANONICAL-GUARD")
        cases = {case["id"]: case for case in chosen}
        snapshots = {
            case["id"]: case["current_revision_id"] for case in [*chosen, outside]
        }
        self.report["selection_setup"] = "explicit_synthetic_api_fixture"
        try:
            outside_before = await self.request("GET", f"/test-cases/{outside['id']}")
            foreign_before = await foreign.get(f"/api/v1/test-cases/{decoy['id']}")
            require(foreign_before.status_code == 200, "canonical_foreign_changed")
            await self.request(
                "PATCH",
                f"/workspaces/{cid}/selection",
                json={
                    "base_version": 0,
                    "sources": [
                        {
                            "ref": f"asset:{case['id']}",
                            "version": case["current_revision_id"],
                        }
                        for case in chosen
                    ],
                },
            )
            change, version = await self.scoped_preview(
                cid, cases, collection, "P1", snapshots
            )
            self.passed(
                "live_canonical_payload_binding_and_exact_two_case_ready_preview"
            )
            review = {
                "selection_version": version,
                "review_refs": list(cases),
                "accepted_fields": {identifier: ["priority"] for identifier in cases},
            }
            self.stage = "rewrite_apply"
            await self.post(f"/case-change-sets/{change}/apply", review)
            updated = {}
            for identifier, before in cases.items():
                after = await self.request("GET", f"/test-cases/{identifier}")
                require(
                    after["priority"] == "P1"
                    and after["current_revision_id"] != before["current_revision_id"],
                    "selection_rewrite_not_applied",
                )
                require(
                    after["title"] == before["title"]
                    and after["steps"] == before["steps"],
                    "selection_preservation_failed",
                )
                updated[identifier] = after
                snapshots[identifier] = after["current_revision_id"]
            state = validate_selection(
                await self.workspace(cid), updated, collection, previous=version
            )
            require(
                state.get("changed_by") == "approved_apply",
                "selection_own_apply_not_refreshed",
            )
            require(
                await self.request("GET", f"/test-cases/{outside['id']}")
                == outside_before,
                "selection_preservation_failed",
            )
            await self.assert_revisions(snapshots)
            foreign_after = await foreign.get(f"/api/v1/test-cases/{decoy['id']}")
            require(
                foreign_after.status_code == 200
                and foreign_after.json() == foreign_before.json(),
                "canonical_foreign_changed",
            )
            self.passed(
                "live_canonical_two_case_exact_apply_preserves_unselected_and_foreign"
            )
            replay = await self.client.post(
                f"/api/v1/case-change-sets/{change}/apply", json=review
            )
            require(replay.status_code in {200, 409}, "reapply_unexpected_status")
            await self.assert_revisions(snapshots)
            require(
                (await self.workspace(cid))["context"]["workbench_selection"] == state,
                "canonical_replay_changed_selection",
            )
            self.passed("live_canonical_reapply_preserves_revisions_and_selection")
        finally:
            await foreign.aclose()

    async def semantic_selection(self, sid):
        self.stage = "setup"
        cid, collection = await self.create_workspace(sid, "Synthetic semantic scope")
        cases = []
        for title, denied in (
            ("SYNTHETIC-ITEM-X17", True),
            ("SYNTHETIC-ITEM-Y42", False),
        ):
            cases.append(
                await self.post(
                    f"/collections/{collection}/test-cases",
                    semantic_case_payload(title, denied),
                )
            )
        bad, good = cases
        other = await self.post(
            f"/spaces/{sid}/collections", {"name": "Synthetic semantic decoy"}
        )
        same_space = await self.post(
            f"/collections/{other['id']}/test-cases",
            semantic_case_payload("SYNTHETIC-ITEM-Z63", True),
        )
        self.report["synthetic_seeded_cases"] = (
            self.report.get("synthetic_seeded_cases", 0) + 3
        )
        foreign, foreign_case = await self.foreign_fixture(
            "SYNTHETIC-ITEM-W85",
            case_payload=semantic_case_payload("SYNTHETIC-ITEM-W85", True),
        )
        snapshots = {
            case["id"]: case["current_revision_id"] for case in [*cases, same_space]
        }
        allowed = {bad["id"], good["id"]}
        forbidden = {same_space["id"], foreign_case["id"]}
        try:
            foreign_before = await foreign.get(
                f"/api/v1/test-cases/{foreign_case['id']}"
            )
            require(foreign_before.status_code == 200, "semantic_foreign_guard_changed")
            denied = await self.client.get(f"/api/v1/test-cases/{foreign_case['id']}")
            require(denied.status_code in {403, 404}, "foreign_case_read_not_denied")
            self.stage = "selection_update"
            turn = await self.message(
                cid,
                "选择当前集合中验证码输错后无法登录的场景，不选择成功的，不修改用例。请根据描述和操作预期理解场景，不把这句概述当作标题关键词。",
            )
            require(
                turn_has_tool(turn, "query_assets")
                and turn_has_tool(turn, "select_assets"),
                "semantic_selection_tool_receipt_missing",
            )
            workspace = await self.workspace(cid)
            selected = validate_selection(workspace, {bad["id"]: bad}, collection)
            verify_semantic_read_state(workspace, collection, allowed, forbidden)
            await self.assert_revisions(snapshots)
            self.passed(
                "live_semantic_selection_from_steps_excludes_success_and_cross_scope_decoys"
            )
            self.stage = "asset_query"
            turn = await self.message(
                cid,
                "仅在当前集合按标题做字面包含查询，标题必须包含 SYNTHETIC-NO-MATCH-NEVER-908172。不要按语义放宽查询，不更改选择，不创建或修改任何数据；如果没有匹配就说明没有。",
            )
            require(
                turn_has_tool(turn, "query_assets"), "semantic_no_match_query_missing"
            )
            counts = (
                self.report["runtime_diagnostics"].get("query_returned_counts") or []
            )
            query_counts = [
                item["returned_count"]
                for item in counts
                if item["tool"] == "query_assets"
            ]
            require(
                bool(query_counts) and query_counts[-1] == 0,
                "semantic_literal_no_match_not_observed",
            )
            workspace = await self.workspace(cid)
            verify_semantic_read_state(workspace, collection, allowed, forbidden)
            require(
                workspace.get("context", {}).get("workbench_selection") == selected,
                "semantic_no_match_changed_selection",
            )
            await self.assert_revisions(snapshots)
            foreign_after = await foreign.get(
                f"/api/v1/test-cases/{foreign_case['id']}"
            )
            require(
                foreign_after.status_code == 200
                and foreign_after.json() == foreign_before.json(),
                "semantic_foreign_guard_changed",
            )
            self.passed(
                "live_literal_no_match_returns_zero_and_preserves_selection_and_all_revisions"
            )
        finally:
            await foreign.aclose()

    async def natural_selection(self, sid):
        self.stage = "setup"
        collections, cases = {}, {}
        for label, priorities in NATURAL_PRIORITIES:
            collection = await self.post(
                f"/spaces/{sid}/collections", {"name": f"Synthetic natural {label}"}
            )
            collections[label] = collection["id"]
            for index, priority in enumerate(priorities, 1):
                name = f"{label}{index}"
                cases[name] = await self.seed_case(
                    collection["id"], f"SYNTHETIC-NATURAL-{name} 登录", priority
                )
        conversation = await self.post("/conversations", {"space_id": sid})
        cid = conversation["id"]
        self.report["workspace_ids"].append(cid)
        snapshots = {case["id"]: case["current_revision_id"] for case in cases.values()}
        selected = None

        async def select(content, names, collection):
            nonlocal selected
            self.stage = "selection_update"
            previous = selected["version"] if selected else None
            await self.message(
                cid, content
            )  # No target IDs, forced intent, or selection API mutation.
            workspace = await self.workspace(cid)
            require(
                workspace.get("collection_id") == collections[collection],
                "selection_workspace_collection_mismatch",
            )
            selected = validate_selection(
                workspace,
                {cases[name]["id"]: cases[name] for name in names},
                collections[collection],
                previous=previous,
            )
            await self.assert_revisions(snapshots)

        await select(
            "找到集合 Synthetic natural A，切换工作集合并选择其中全部2条用例。只建立选择，不修改用例。",
            ["A1", "A2"],
            "A",
        )
        old_change, old_version = await self.scoped_preview(
            cid,
            {cases[name]["id"]: cases[name] for name in ("A1", "A2")},
            collections["A"],
            "P0",
            snapshots,
        )
        protected_before = await self.request("GET", f"/test-cases/{cases['A2']['id']}")
        protected_audits = case_audit_ids(cases["A2"]["id"])
        await select(
            "从当前选择移除 SYNTHETIC-NATURAL-A2 登录，保留A1。只更新选择，不修改用例。",
            ["A1"],
            "A",
        )
        self.passed("live_nl_collection_selection_and_remove")
        self.stage = "selection_stale_apply"
        for payload in (
            {},
            {
                "selection_version": old_version,
                "review_refs": [cases["A2"]["id"]],
                "accepted_fields": {cases["A2"]["id"]: ["priority"]},
            },
        ):
            rejected = await self.client.post(
                f"/api/v1/case-change-sets/{old_change}/apply",
                json=payload,
            )
            require(rejected.status_code == 409, "stale_selection_apply_not_blocked")
            await self.assert_revisions(snapshots)
            require(
                await self.request("GET", f"/test-cases/{cases['A2']['id']}")
                == protected_before
                and case_audit_ids(cases["A2"]["id"]) == protected_audits,
                "selection_excluded_case_changed",
            )
        change, version = await self.selected_preview(
            cid, cases["A1"], collections["A"], "P0", snapshots
        )
        cases["A1"], selected = await self.apply_selected(
            cid, cases["A1"], collections["A"], "P0", snapshots, change, version
        )
        require(
            await self.request("GET", f"/test-cases/{cases['A2']['id']}")
            == protected_before
            and case_audit_ids(cases["A2"]["id"]) == protected_audits,
            "selection_excluded_case_changed",
        )
        old_preview = await self.request("GET", f"/case-change-sets/{old_change}")
        require(
            old_preview.get("status") == "ready", "selection_old_preview_not_retained"
        )
        await self.post(f"/case-change-sets/{old_change}/reject", {})
        self.passed(
            "live_nl_narrowed_selection_fresh_apply_preserves_excluded_case_and_audit"
        )
        self.passed("live_nl_selected_rewrite_refreshes_canonical_version")
        await select(
            "在当前选择上添加 SYNTHETIC-NATURAL-A2 登录，不要替换已有A1；不修改用例。",
            ["A1", "A2"],
            "A",
        )
        await select(
            "只保留当前选择中优先级为P2的用例。仅筛选选择，不修改任何用例的优先级。",
            ["A2"],
            "A",
        )
        self.passed("live_nl_add_and_current_priority_filter")
        stale_change, stale_version = await self.selected_preview(
            cid, cases["A2"], collections["A"], "P1", snapshots
        )
        await select(
            "切换到集合 Synthetic natural B，只选择 SYNTHETIC-NATURAL-B1 登录，替换先前选择。已有改写预览保持未应用，暂不改写。",
            ["B1"],
            "B",
        )
        self.stage = "selection_stale_apply"
        stale = await self.client.post(
            f"/api/v1/case-change-sets/{stale_change}/apply",
            json={"selection_version": stale_version},
        )
        require(
            stale.status_code == 409
            and stale.json().get("detail") == "workbench_selection_changed",
            "stale_selection_apply_not_blocked",
        )
        await self.assert_revisions(snapshots)
        await self.post(f"/case-change-sets/{stale_change}/reject", {})
        self.passed("live_nl_scope_switch_blocks_stale_preview")
        change, version = await self.selected_preview(
            cid, cases["B1"], collections["B"], "P0", snapshots
        )
        cases["B1"], selected = await self.apply_selected(
            cid, cases["B1"], collections["B"], "P0", snapshots, change, version
        )
        self.passed("live_nl_new_scope_fresh_preview")
        await select(
            "回到集合 Synthetic natural A，只选择 SYNTHETIC-NATURAL-A2 登录，替换当前B1选择。只更新选择。",
            ["A2"],
            "A",
        )
        change, version = await self.selected_preview(
            cid, cases["A2"], collections["A"], "P1", snapshots
        )
        cases["A2"], selected = await self.apply_selected(
            cid, cases["A2"], collections["A"], "P1", snapshots, change, version
        )
        self.passed("live_nl_return_to_a2_preserves_other_cases")

    async def foreign_fixture(self, title, *, case_payload=None):
        from casepilot_api.main import app

        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://synthetic.test"
        )
        other = Journey(
            client,
            self.dispatch,
            self.tasks,
            {"checks": [], "workspace_ids": []},
            self.model,
        )
        try:
            user = await other.post(
                "/auth/register",
                {
                    "email": f"foreign-synthetic-{uuid4().hex}@casepilot.test",
                    "display_name": "Foreign synthetic decoy",
                    "password": "SyntheticFixture123!",
                },
            )
            collection = await other.post(
                f"/spaces/{user['spaces'][0]['id']}/collections",
                {"name": "Foreign synthetic assets"},
            )
            case = (
                await other.post(
                    f"/collections/{collection['id']}/test-cases", case_payload
                )
                if case_payload is not None
                else await other.seed_case(collection["id"], title)
            )
            self.report["foreign_synthetic_seeded_cases"] = (
                self.report.get("foreign_synthetic_seeded_cases", 0) + 1
            )
            return client, case
        except BaseException:
            await client.aclose()
            raise

    async def asset_reuse(self, sid):
        self.stage = "setup"
        source_collection = await self.post(
            f"/spaces/{sid}/collections", {"name": "Synthetic reuse source"}
        )
        source = await self.seed_case(
            source_collection["id"], "SYNTHETIC-MIXED-LOGIN 有效验证码登录成功"
        )
        unrelated = await self.seed_case(
            source_collection["id"], "SYNTHETIC-UNRELATED 控制用例"
        )
        destination_name = "Synthetic mixed destination"
        catalog_before = await self.request("GET", f"/spaces/{sid}/collections")
        conversation = await self.post("/conversations", {"space_id": sid})
        cid = conversation["id"]
        self.report["workspace_ids"].append(cid)
        snapshots = {
            case["id"]: case["current_revision_id"] for case in [source, unrelated]
        }
        foreign, decoy = await self.foreign_fixture(source["title"])
        try:
            self.stage = "asset_query"
            denied = await self.client.get(f"/api/v1/test-cases/{decoy['id']}")
            require(denied.status_code in {403, 404}, "foreign_case_read_not_denied")
            await self.message(
                cid,
                "只查询当前空间中标题包含 SYNTHETIC-MIXED-LOGIN 的历史用例，不创建或修改任何用例。",
            )
            workspace = await self.workspace(cid)
            catalog = (
                workspace.get("context", {})
                .get("workbench_plan", {})
                .get("source_catalog", {})
            )
            require(
                f"asset:{source['id']}" in catalog, "model_asset_query_missing_source"
            )
            require(
                f"asset:{decoy['id']}" not in catalog,
                "foreign_asset_leaked_into_catalog",
            )
            require(not workspace.get("candidates"), "asset_query_created_candidates")
            self.passed("live_asset_query_excludes_foreign_space")
            self.stage = "asset_reuse"
            turn = await self.message(
                cid,
                "测试对象：SYNTHETIC-MIXED-LOGIN 验证码登录。复用刚才找到的登录成功用例，"
                "并补充1条错误验证码被拒绝的缺口用例，总计2条，请新建集合 Synthetic mixed destination 作为输出目的地。"
                "先让我确认复用资产与测试点，不修改原始历史用例。",
            )
            require(
                turn.get("action", {}).get("type") == "collection_confirmation",
                "reuse_collection_confirmation_missing",
            )
            operation = turn["operation_plan"]["operations"][0]["id"]
            await self.post(
                f"/conversation-operations/{operation}/confirm-collection",
                {"create_collection_name": destination_name},
            )
            target = created_destination(
                catalog_before,
                await self.request("GET", f"/spaces/{sid}/collections"),
                destination_name,
            )
            await self.dispatch.drain(self.tasks)
            workspace = await self.workspace(cid)
            require(
                workspace.get("collection_id") == target["id"],
                "reuse_destination_mismatch",
            )
            require(bool(workspace.get("test_briefs")), "reuse_asset_brief_missing")
            brief = workspace["test_briefs"][-1]
            selection = brief.get("content", {}).get("asset_selection", {})
            require(
                selection.get("status") == "awaiting_confirmation"
                and selection.get("strategy") == "select_and_generate",
                "reuse_asset_review_gate_missing",
            )
            sources = {row["case_id"] for row in selection.get("sources", [])}
            require(
                source["id"] in sources and decoy["id"] not in sources,
                "reuse_asset_scope_invalid",
            )
            await self.assert_revisions(snapshots)
            self.passed("live_mixed_reuse_asset_review_gate")
            self.stage = "asset_confirm"
            points = (brief["content"].get("asset_base_planning") or {}).get(
                "test_points", []
            )
            await self.post(
                f"/workspaces/{cid}/generation-assets/confirm",
                {
                    "version": brief["version"],
                    "case_ids": [source["id"]],
                    "test_point_ids": [point["id"] for point in points],
                },
            )
            await self.dispatch.drain(self.tasks)
            workspace = await self.workspace(cid)
            latest = workspace["test_briefs"][-1]
            require(
                latest["version"] > brief["version"]
                and bool(
                    latest.get("content", {}).get("planning", {}).get("test_points")
                ),
                "reuse_gap_planning_missing",
            )
            self.stage = "gap_generation"
            await self.post(
                f"/workspaces/{cid}/test-briefs/confirm",
                {"version": latest["version"], "model_id": self.model},
            )
            await self.dispatch.drain(self.tasks)
            workspace = await self.workspace(cid)
            require(
                len(workspace.get("candidates", [])) == 2,
                "reuse_gap_candidate_quantity_mismatch",
            )
            self.stage = "adoption"
            adopted = await self.post(
                f"/workspaces/{cid}/candidates/commit",
                exact_candidate_commit(workspace["candidates"]),
            )
            gap = mixed_gap_case(adopted, source["id"], {unrelated["id"], decoy["id"]})
            await self.assert_revisions(snapshots)
            snapshots[gap["id"]] = gap["current_revision_id"]
            response = await foreign.get(f"/api/v1/test-cases/{decoy['id']}")
            require(
                response.status_code == 200
                and response.json()["current_revision_id"]
                == decoy["current_revision_id"],
                "foreign_source_revision_changed",
            )
            self.passed("live_reuse_gap_adoption_preserves_original")
            self.stage = "gap_selection"
            await self.message(
                cid,
                "在 Synthetic mixed destination 中只选择刚补生成的错误验证码被拒绝的缺口用例。"
                "不要选择或修改原始复用的登录成功用例，其他用例不变，先只更新选择。",
            )
            validate_selection(
                await self.workspace(cid), {gap["id"]: gap}, target["id"]
            )
            await self.assert_revisions(snapshots)
            self.passed("live_mixed_followup_nl_selects_only_new_gap")
            priority = "P1" if gap["priority"] != "P1" else "P2"
            change, version = await self.selected_preview(
                cid, gap, target["id"], priority, snapshots
            )
            await self.apply_selected(
                cid, gap, target["id"], priority, snapshots, change, version
            )
            response = await foreign.get(f"/api/v1/test-cases/{decoy['id']}")
            require(
                response.status_code == 200
                and response.json()["current_revision_id"]
                == decoy["current_revision_id"],
                "gap_rewrite_changed_foreign_source",
            )
            self.passed(
                "live_mixed_gap_rewrite_preserves_reused_unrelated_foreign_assets"
            )
        finally:
            await foreign.aclose()

    async def generation(self, sid):
        cid, collection = await self.create_workspace(sid, "Synthetic live generation")
        self.stage = "generation_request"
        await self.message(
            cid,
            "测试对象：合成验证码登录。需求：有效验证码登录成功，错误验证码显示错误。"
            "请新生成2条测试用例，先规划测试点供我确认；不要查询外部资料。",
        )
        self.stage = "brief_worker"
        await self.dispatch.drain(self.tasks)
        workspace = await self.workspace(cid)
        require(bool(workspace.get("test_briefs")), "generation_brief_missing")
        brief = workspace["test_briefs"][-1]
        require(
            bool(brief.get("content", {}).get("planning", {}).get("test_points")),
            "generation_test_points_missing",
        )
        self.passed("live_agent_test_point_planning")
        self.stage = "brief_confirm"
        await self.post(
            f"/workspaces/{cid}/test-briefs/confirm",
            {"version": brief["version"], "model_id": self.model},
        )
        self.stage = "generation_worker"
        await self.dispatch.drain(self.tasks)
        workspace = await self.workspace(cid)
        require(
            len(workspace.get("candidates", [])) == 2, "generation_quantity_mismatch"
        )
        self.passed("live_worker_generated_two_candidates")
        self.stage = "adoption"
        adopted = await self.post(f"/workspaces/{cid}/candidates/commit", {})
        require(len(adopted) == 2, "adoption_quantity_mismatch")
        snapshots = {case["id"]: case["current_revision_id"] for case in adopted}
        case = adopted[0]
        self.passed("live_candidates_adopted")
        current_state = (await self.workspace(cid)).get("context", {}).get("workbench_selection") or {}
        await self.request("PATCH", f"/workspaces/{cid}/selection", json={
            "base_version": current_state.get("version", 0), "action": "replace",
            "sources": [{"ref": f"asset:{case['id']}", "version": case["current_revision_id"]}],
        })
        selected = validate_selection(await self.workspace(cid), {case["id"]: case}, collection)
        self.report["selection_setup"] = "explicit_synthetic_api_fixture"
        priority = "P1" if case["priority"] != "P1" else "P2"
        targets = {
            "selection_version": selected["version"],
            "target_scope": "selected",
            "target_case_ids": [case["id"]],
            "targets": [{"kind": "case", "case_ids": [case["id"]]}],
        }
        self.stage = "rewrite_request"
        turn = await self.message(
            cid,
            f"只把当前选中的这条用例优先级改为{priority}，保留标题和步骤。",
            **targets,
        )
        single_prepared_operation(turn)
        await self.assert_revisions(snapshots)
        change_id, preview = await self.compute_prepared_preview(cid, turn)
        validate_preview_scope(preview, {case["id"]: case})
        validate_priority_diff(preview, priority)
        await self.assert_revisions(snapshots)
        self.passed("live_rewrite_preview_requires_approval")
        self.stage = "rewrite_apply"
        review = {
            "selection_version": selected["version"],
            "review_refs": [case["id"]],
            "accepted_fields": {case["id"]: ["priority"]},
        }
        await self.post(f"/case-change-sets/{change_id}/apply", review)
        after = await self.request("GET", f"/test-cases/{case['id']}")
        require(
            after["priority"] == priority
            and after["current_revision_id"] != case["current_revision_id"],
            "rewrite_not_applied",
        )
        require(
            after["title"] == case["title"] and after["steps"] == case["steps"],
            "rewrite_preservation_failed",
        )
        await self.assert_revisions(snapshots, changed_id=case["id"])
        snapshots[case["id"]] = after["current_revision_id"]
        self.passed("live_rewrite_selected_only_and_preserves_fields")
        replay = await self.client.post(
            f"/api/v1/case-change-sets/{change_id}/apply", json=review
        )
        require(replay.status_code in {200, 409}, "reapply_unexpected_status")
        await self.assert_revisions(snapshots)
        self.passed("live_apply_idempotency")
        current_selection = validate_selection(await self.workspace(cid), {after["id"]: after}, collection)
        targets["selection_version"] = current_selection["version"]
        self.stage = "cancel_request"
        turn = await self.message(
            cid,
            "只把当前选中的用例优先级改成P0，先让我确认，不修改其他用例。",
            **targets,
        )
        operation = single_prepared_operation(turn)
        cancel_change = None
        if preview_requires_confirmation(turn, operation):
            require(not self.dispatch.queue, "cancel_worker_dispatched_early")
        else:
            cancel_change, cancellation_preview = await self.compute_prepared_preview(
                cid, turn
            )
            validate_preview_scope(cancellation_preview, {after["id"]: after})
            await self.assert_revisions(snapshots)
        cancelled = await self.request(
            "POST", f"/conversation-operations/{operation['id']}/cancel"
        )
        require(
            cancelled.get("status") == "cancelled", "cancel_operation_not_cancelled"
        )
        if cancel_change:
            rejected = await self.request("GET", f"/case-change-sets/{cancel_change}")
            require(rejected.get("status") == "rejected", "cancel_preview_not_rejected")
        await self.assert_revisions(snapshots)
        self.passed("live_proposal_cancel_preserves_selected_and_unselected")

    async def spreadsheet(self, sid):
        cid, collection_id = await self.create_workspace(
            sid, "Synthetic historical spreadsheet"
        )
        self.stage = "spreadsheet_upload"
        upload = await self.request(
            "POST",
            f"/conversations/{cid}/attachments",
            files={
                "files": (
                    "synthetic-history.xlsx",
                    synthetic_spreadsheet(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        self.stage = "spreadsheet_index"
        await self.dispatch.drain(self.tasks)
        self.stage = "spreadsheet_select"
        turn = await self.message(
            cid,
            "读取上传的历史表格，把其中这1条用例作为草稿，只把优先级P2改为P1，"
            "其他字段不变。先准备改写范围让我确认，不要保存正式用例。",
            document_ids=upload["document_ids"],
        )
        single_prepared_operation(turn)
        workspace = await self.workspace(cid)
        require(
            len(workspace.get("candidates", [])) == 1, "spreadsheet_candidate_missing"
        )
        original = workspace["candidates"][0]
        require(not original["included"], "spreadsheet_adopted_without_review")
        require(
            original["snapshot"].get("source_provenance", {}).get("document_id")
            in upload["document_ids"],
            "spreadsheet_provenance_missing",
        )
        require(
            await self.request("GET", f"/collections/{collection_id}/test-cases") == [],
            "spreadsheet_formal_asset_created_early",
        )
        self.passed("live_spreadsheet_preview_and_provenance")
        self.stage = "spreadsheet_rewrite"
        change_id, preview = await self.compute_prepared_preview(cid, turn)
        validate_candidate_preview(preview, original)
        validate_priority_diff(preview, "P1")
        before_apply = await self.workspace(cid)
        unchanged = next(
            (
                item
                for item in before_apply.get("candidates", [])
                if item["ref"] == original["ref"]
            ),
            {},
        )
        require(
            unchanged.get("version") == original["version"]
            and unchanged.get("snapshot") == original["snapshot"],
            "spreadsheet_candidate_changed_before_apply",
        )
        require(
            await self.request("GET", f"/collections/{collection_id}/test-cases") == [],
            "spreadsheet_formal_asset_created_early",
        )
        await self.post(
            f"/case-change-sets/{change_id}/apply",
            {
                "review_refs": [original["ref"]],
                "accepted_fields": {original["ref"]: ["priority"]},
            },
        )
        workspace = await self.workspace(cid)
        rewritten = next(
            (
                item
                for item in workspace["candidates"]
                if item["ref"] == original["ref"]
            ),
            {},
        )
        require(
            rewritten.get("version", 0) > original["version"],
            "spreadsheet_version_unchanged",
        )
        require(
            rewritten["snapshot"]["priority"] == "P1"
            and rewritten["snapshot"]["steps"] == original["snapshot"]["steps"],
            "spreadsheet_rewrite_failed",
        )
        require(
            rewritten["snapshot"].get("source_provenance")
            == original["snapshot"].get("source_provenance"),
            "spreadsheet_provenance_changed",
        )
        included = await self.request(
            "PATCH",
            f"/workspace-candidates/{rewritten['id']}",
            json={"included": True, "base_version": rewritten["version"]},
        )
        canonical_before = (
            (await self.workspace(cid))
            .get("context", {})
            .get("workbench_selection", {})
        )
        adopted = await self.post(
            f"/workspaces/{cid}/candidates/commit", candidate_commit_payload(included)
        )
        require(
            len(adopted) == 1 and adopted[0]["priority"] == "P1",
            "spreadsheet_adoption_failed",
        )
        canonical_after = (
            (await self.workspace(cid))
            .get("context", {})
            .get("workbench_selection", {})
        )
        verify_adopted_candidate_selection(
            canonical_before, canonical_after, original["ref"]
        )
        self.passed("live_spreadsheet_rewrite_review_apply_adopt")

    async def image(self, sid):
        cid, _ = await self.create_workspace(sid, "Synthetic image conversation")
        self.stage = "image_upload"
        upload = await self.request(
            "POST",
            f"/conversations/{cid}/attachments",
            files={"files": ("synthetic-color.png", synthetic_png(), "image/png")},
        )
        self.stage = "image_index"
        await self.dispatch.drain(self.tasks)
        self.stage = "image_question"
        turn = await self.message(
            cid,
            "只回答这张合成图片的主要颜色，不生成或修改用例。",
            document_ids=upload["document_ids"],
        )
        content = turn.get("assistant_message", {}).get("content", "")
        require(
            "红" in content or "red" in content.lower(), "image_understanding_failed"
        )
        followup = await self.message(
            cid, "延续刚才那张图片：它是单色还是多色？请用中文只回答单色或多色。"
        )
        require(
            "单色" in followup.get("assistant_message", {}).get("content", ""),
            "image_multiturn_context_failed",
        )
        require(
            not (await self.workspace(cid)).get("candidates"),
            "image_question_created_candidates",
        )
        self.passed("live_image_understanding_and_multiturn_context")


def configuration_overrides(key, model, storage):
    """Same explicit in-memory configuration used by execute and offline readiness checks."""
    return (
        {
            "workbench_agent_enabled": True,
            "agent_provider": "openai_compatible",
            "agent_api_type": "responses",
            "agent_api_key": key,
            "agent_base_url": BASE_URL,
            "agent_model": model,
            "agent_pro_model": model,
            "agent_local_model": model,
            "agent_routing_model": model,
            "agent_models": model,
            "image_models": model,
            "agent_tracing_enabled": False,
            "ai_mode": "live",
            "knowledge_storage_path": storage,
        },
        {
            "provider": "openai_compatible",
            "api_type": "responses",
            "api_key": key,
            "base_url": BASE_URL,
            "model": model,
            "pro_model": model,
            "local_model": model,
            "models": model,
            "image_models": model,
            "embedding_provider": "disabled",
            "tracing_enabled": False,
            "knowledge_storage_path": storage,
        },
    )


async def execute(key, model, budget, scenarios, report, storage, *, checkpoint=None):
    sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "apps/agent/src")]
    from agents import set_tracing_disabled
    from casepilot_agent.config import get_settings as agent_settings
    from casepilot_api.config import get_settings as api_settings

    set_tracing_disabled(True)
    api, worker = api_settings(), agent_settings()
    require(
        hasattr(api, "workbench_agent_enabled")
        and hasattr(api, "agent_api_type")
        and hasattr(worker, "api_type"),
        "rebuilt_backend_not_ready",
    )
    with ExitStack() as stack:
        for settings, values in zip(
            (api, worker), configuration_overrides(key, model, storage), strict=True
        ):
            for name, value in values.items():
                require(hasattr(settings, name), "rebuilt_backend_setting_missing")
                stack.enter_context(patch.object(settings, name, value))
        from casepilot_agent import tasks
        from casepilot_api import conversations, knowledge
        from casepilot_api.main import app

        journey_type = Journey
        if "natural_selection" in scenarios or "crud_continuous" in scenarios:
            require(scenarios in ({"natural_selection"}, {"crud_continuous"}),
                    "durable_scenario_must_be_isolated")
            from workbench_request_continuation import (
                NaturalDurableJourney,
                RequestWorkerDispatch,
            )
            journey_type, dispatch = NaturalDurableJourney, RequestWorkerDispatch()
            if scenarios == {"crud_continuous"}:
                from workbench_crud_continuation import CrudDispatch, DurableCrudJourney
                journey_type, dispatch = DurableCrudJourney, CrudDispatch()
            # Keep actual transactional outbox creation for both domain workers
            # and continuations. The helper substitutes broker transport only.
        else:
            dispatch = Dispatch()
            stack.enter_context(
                patch.object(conversations, "enqueue_task", dispatch.enqueue)
            )
            stack.enter_context(patch.object(knowledge, "enqueue_task", dispatch.enqueue))
        stack.enter_context(
            patch.object(
                tasks.celery_app,
                "send_task",
                side_effect=JourneyFailure("external_worker_dispatch_blocked"),
            )
        )
        async with (
            bounded_clients(key, budget),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://synthetic.test"
            ) as client,
        ):
            journey = journey_type(client, dispatch, tasks, report, model)
            if scenarios in ({"natural_selection"}, {"crud_continuous"}):
                dispatch.journey = journey
            journey._redact_secret = key
            if checkpoint is not None:
                journey.checkpoint = checkpoint
            try:
                await journey.run(scenarios)
            finally:
                journey._redact_secret = ""
                report["last_stage"] = journey.stage
                report["worker_tasks_executed"] = dispatch.executed


def main(argv=None):
    arguments = parser(__doc__)
    arguments.set_defaults(max_requests=60)
    arguments.add_argument(
        "--scenarios",
        nargs="+",
        choices=[
            "generation",
            "spreadsheet",
            "image",
            "natural_selection",
            "semantic_selection",
            "canonical_rewrite",
            "asset_reuse",
        ],
        default=["generation"],
    )
    arguments.add_argument(
        "--storage-dir",
        default=str(Path(tempfile.gettempdir()) / "casepilot-live-synthetic"),
    )
    args = arguments.parse_args(argv)
    disable_sensitive_logging()
    budget = RequestBudget(args.max_requests, emit_json)
    report = {
        "event": "summary",
        "scope": "synthetic_live_api_worker_domain_journey",
        "passed": False,
        "browser_ui_tested": False,
        "checks": [],
        "workspace_ids": [],
        "embedding_provider": "disabled",
    }
    key = ""
    try:
        key = read_key(args)
        Path(args.storage_dir).mkdir(parents=True, exist_ok=True)
        asyncio.run(
            execute(
                key, args.model, budget, set(args.scenarios), report, args.storage_dir
            )
        )
        report["passed"] = bool(report["checks"]) and all(
            check["passed"] for check in report["checks"]
        )
    except Exception as exc:  # noqa: BLE001 -- Never expose exception text from SDK/API/domain.
        code = safe_domain_failure(exc)["code"]
        if code == "unclassified_domain_failure":
            code = "journey_failed"
        report["error_code"] = budget.stop_code or code
        report["exception_class"] = exception_name(exc)
        report["domain_failure"] = safe_domain_failure(exc)
        diagnostic = safe_structured_failure(exc)
        if diagnostic is not None:
            report["structured_failure"] = diagnostic
    finally:
        key = ""
    report.update(budget.summary())
    emit_json(report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
