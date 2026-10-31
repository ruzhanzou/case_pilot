#!/usr/bin/env python3
"""Independent synthetic continuous NL CRUD acceptance; no browser/collection-deletion claim.

Uses the existing credential guard, strict counted transport and real API/worker
setup unchanged. Only the harness driver class is selected; no business/provider
method or output is replaced. Model-selected targets are verified from canonical
state. Explicit QA seed artifacts are distinguished from NL-created entities.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import workbench_agent_live_journey as base
from workbench_agent_live_acceptance import (
    STAGES,
    RequestBudget,
    SafetyStop,
    disable_sensitive_logging,
    emit_json,
    exception_name,
    parser,
    read_key,
)
from workbench_domain_diagnostics import safe_domain_failure
from workbench_qa_checkpoint import CONTINUOUS_CHECKS, create_writer
from workbench_safe_diagnostics import safe_structured_failure

GOOD_MARKER = "SYNTHETIC-CRUD-GOOD"
BAD_MARKER = "SYNTHETIC-CRUD-BAD"


FAILURE_CODES = frozenset(
    [
        "adoption_candidate_id_missing",
        "adoption_candidate_not_canonically_selected",
        "adoption_candidate_version_missing",
        "adoption_left_stale_candidate_selection",
        "adoption_quantity_mismatch",
        "adoption_selection_version_not_advanced",
        "api_request_failed",
        "asset_query_created_candidates",
        "cancel_confirmation_missing",
        "cancel_worker_dispatched_early",
        "client_factory_invalid",
        "credential_missing_or_invalid",
        "crud_attachment_case_identity_mismatch",
        "crud_attachment_priority_mismatch",
        "crud_attachment_read_receipt_missing",
        "crud_candidate_quantity_mismatch",
        "crud_collection_changed_before_approval",
        "crud_collection_confirmation_not_idempotent",
        "crud_collection_create_created_cases",
        "crud_collection_entity_identity_changed",
        "crud_collection_mismatched_approval_not_blocked",
        "crud_collection_proposal_mismatch",
        "crud_collection_proposal_receipt_missing",
        "crud_collection_query_mutated",
        "crud_collection_query_receipt_missing",
        "crud_collection_wrong_approval_mutated",
        "crud_delete_change_set_missing",
        "crud_delete_changed_nontarget_membership",
        "crud_delete_preview_not_ready",
        "crud_delete_receipt_missing",
        "crud_delete_replay_restored_case",
        "crud_delete_replay_unexpected_status",
        "crud_delete_scope_count_mismatch",
        "crud_delete_scope_or_revision_mismatch",
        "crud_delete_unexpected_worker",
        "crud_deleted_target_left_in_selection",
        "crud_foreign_guard_changed",
        "crud_generated_quantity_mismatch",
        "crud_generation_brief_missing",
        "crud_generation_destination_mismatch",
        "crud_generation_points_missing",
        "crud_generation_reused_guard",
        "crud_journey_failed",
        "crud_index_not_new_upload",
        "crud_index_document_mismatch",
        "crud_index_owner_mismatch",
        "crud_index_task_mismatch",
        "crud_index_document_changed",
        "crud_index_not_ready",
        "crud_index_batch_not_drained",
        "crud_no_match_changed_selection",
        "crud_no_match_created_operation",
        "crud_no_match_query_receipt_missing",
        "crud_old_scope_delete_not_blocked",
        "crud_rename_changed_collection_id",
        "crud_rename_changed_membership",
        "crud_soft_deleted_case_still_visible",
        "endpoint_rejected",
        "external_image_rejected",
        "external_worker_dispatch_blocked",
        "foreign_asset_leaked_into_catalog",
        "foreign_case_read_not_denied",
        "foreign_source_revision_changed",
        "gap_identity_invalid",
        "gap_rewrite_changed_foreign_source",
        "generation_brief_missing",
        "generation_contract_failed",
        "generation_quantity_mismatch",
        "generation_test_points_missing",
        "hosted_tool_rejected",
        "image_multiturn_context_failed",
        "image_question_created_candidates",
        "image_understanding_failed",
        "live_permission_required",
        "model_asset_query_missing_source",
        "new_gap_error_case_missing",
        "original_reuse_not_linked",
        "output_budget_invalid",
        "privacy_contract_invalid",
        "provider_incomplete_response",
        "reapply_unexpected_status",
        "rebuilt_backend_not_ready",
        "rebuilt_backend_setting_missing",
        "redirect_rejected",
        "request_contract_invalid",
        "response_contract_invalid",
        "reuse_adoption_quantity_mismatch",
        "reuse_asset_brief_missing",
        "reuse_asset_review_gate_missing",
        "reuse_asset_scope_invalid",
        "reuse_destination_mismatch",
        "reuse_gap_candidate_quantity_mismatch",
        "reuse_gap_planning_missing",
        "rewrite_change_set_missing",
        "rewrite_confirmation_missing",
        "rewrite_contract_failed",
        "rewrite_not_applied",
        "rewrite_priority_diff_missing",
        "rewrite_preservation_failed",
        "rewrite_preview_scope_invalid",
        "sdk_loop_acceptance_failed",
        "selection_collection_mismatch",
        "selection_count_mismatch",
        "selection_identity_mismatch",
        "selection_membership_mismatch",
        "selection_own_apply_not_refreshed",
        "selection_preservation_failed",
        "selection_preview_missing",
        "selection_preview_scope_invalid",
        "selection_proposal_not_bound",
        "selection_reference_mismatch",
        "selection_revision_mismatch",
        "selection_rewrite_confirmation_missing",
        "selection_rewrite_not_applied",
        "selection_version_missing",
        "selection_version_not_advanced",
        "selection_workspace_collection_mismatch",
        "spreadsheet_adopted_without_review",
        "spreadsheet_adoption_failed",
        "spreadsheet_candidate_missing",
        "spreadsheet_change_set_missing",
        "spreadsheet_confirmation_missing",
        "spreadsheet_formal_asset_created_early",
        "spreadsheet_preview_not_ready",
        "spreadsheet_provenance_changed",
        "spreadsheet_provenance_missing",
        "spreadsheet_rewrite_failed",
        "spreadsheet_version_unchanged",
        "stale_selection_apply_not_blocked",
        "stdin_must_be_noninteractive",
        "unexpected_task_dispatch",
        "unselected_revision_changed",
        "workbench_agent_failed",
        "workbench_agent_not_used",
        "worker_task_budget_exhausted",
        "worker_task_failed",
    ]
)


def synthetic_requirements():
    return (
        "合成验证码登录需求，仅用于测试。请新生成且仅生成下面两条测试用例，不复用已有用例。\n"
        f"第一条标题必须包含 {GOOD_MARKER}：有效验证码登录成功，优先级P2。\n"
        "前置条件：合成账号已注册。操作：输入有效验证码并登录。预期：显示登录成功。\n"
        f"第二条标题必须包含 {BAD_MARKER}：错误验证码被拒绝，优先级P1。\n"
        "前置条件：合成账号已注册。操作：输入错误验证码并登录。预期：显示验证码错误且未登录。\n"
        "不要修改已有P0保护用例，不操作其他集合。\n"
    ).encode()


def has_receipt(turn, names, effect=None):
    metadata = (
        turn.get("assistant_message", {}).get("metadata", {}).get("workbench_agent", {})
    )
    return any(
        isinstance(item, dict)
        and item.get("tool") in names
        and (effect is None or item.get("effect") == effect)
        for item in metadata.get("receipts", [])
    )


def identify_generated(cases):
    base.require(len(cases) == 2, "crud_generated_quantity_mismatch")
    good = [case for case in cases if GOOD_MARKER in case.get("title", "")]
    bad = [case for case in cases if BAD_MARKER in case.get("title", "")]
    base.require(
        len(good) == 1 and len(bad) == 1 and good[0]["id"] != bad[0]["id"],
        "crud_attachment_case_identity_mismatch",
    )
    base.require(
        good[0]["priority"] == "P2" and bad[0]["priority"] == "P1",
        "crud_attachment_priority_mismatch",
    )
    return good[0], bad[0]


def exact_delete_review(preview, case):
    base.require(preview.get("status") == "ready", "crud_delete_preview_not_ready")
    items = preview.get("items", [])
    base.require(len(items) == 1, "crud_delete_scope_count_mismatch")
    item = items[0]
    base.require(
        item.get("operation") == "delete"
        and item.get("target_type") == "formal"
        and item.get("test_case_id") == case["id"]
        and item.get("ref") == case["id"]
        and item.get("base_revision_id") == case["current_revision_id"],
        "crud_delete_scope_or_revision_mismatch",
    )
    return {"review_refs": [case["id"]], "accepted_fields": {case["id"]: ["delete"]}}


class CrudJourney(base.Journey):
    async def collection_names(self, sid):
        return {
            item["id"]: item["name"]
            for item in await self.request("GET", f"/spaces/{sid}/collections")
        }

    async def collection_proposal(
        self, cid, sid, content, action, name, collection_id=None
    ):
        before = await self.collection_names(sid)
        self.stage = "selection_update"
        turn = await self.message(cid, content)
        proposal = turn.get("action", {}).get("proposal") or {}
        base.require(
            turn.get("action", {}).get("type") == "collection_proposal"
            and proposal.get("status") == "pending"
            and proposal.get("action") == action
            and proposal.get("name") == name
            and proposal.get("collection_id") == collection_id,
            "crud_collection_proposal_mismatch",
        )
        base.require(
            has_receipt(
                turn,
                {"create_collection" if action == "create" else "rename_collection"},
                "prepare",
            ),
            "crud_collection_proposal_receipt_missing",
        )
        base.require(
            await self.collection_names(sid) == before,
            "crud_collection_changed_before_approval",
        )
        path = f"/workspaces/{cid}/collection-proposals/{proposal['id']}/confirm"
        wrong = await self.client.post(
            "/api/v1" + path,
            json={"name": name + "-WRONG", "collection_id": collection_id},
        )
        base.require(
            wrong.status_code == 409, "crud_collection_mismatched_approval_not_blocked"
        )
        base.require(
            await self.collection_names(sid) == before,
            "crud_collection_wrong_approval_mutated",
        )
        result = await self.post(path, {"name": name, "collection_id": collection_id})
        duplicate = await self.post(
            path, {"name": name, "collection_id": collection_id}
        )
        base.require(duplicate == result, "crud_collection_confirmation_not_idempotent")
        after = await self.collection_names(sid)
        expected = {**before, result["id"]: name}
        base.require(
            after == expected and (action != "rename" or result["id"] == collection_id),
            "crud_collection_entity_identity_changed",
        )
        return result

    async def select_language(self, cid, content, expected, collection, snapshots):
        self.stage = "selection_update"
        await self.message(cid, content)
        state = base.validate_selection(await self.workspace(cid), expected, collection)
        await self.assert_revisions(snapshots)
        return state

    async def prepare_delete(self, cid, case, collection, snapshots):
        self.stage = "rewrite_request"
        selection = base.validate_selection(
            await self.workspace(cid), {case["id"]: case}, collection
        )
        turn = await self.message(
            cid,
            "请软删除刚才选中的这一条用例，保留其余用例不变。先给我精确删除清单，未经确认不要删除。",
        )
        base.require(
            has_receipt(turn, {"prepare_delete"}, "prepare"),
            "crud_delete_receipt_missing",
        )
        change = turn.get("action", {}).get("change_set_id")
        base.require(bool(change), "crud_delete_change_set_missing")
        preview = await self.request("GET", f"/case-change-sets/{change}")
        review = exact_delete_review(preview, case)
        review["selection_version"] = selection["version"]
        await self.assert_revisions(snapshots)
        base.require(not self.dispatch.queue, "crud_delete_unexpected_worker")
        return change, review, selection["version"]

    async def run(self, scenarios):
        self.stage = "setup"
        user = await self.post(
            "/auth/register",
            {
                "email": f"crud-synthetic-{uuid4().hex}@casepilot.test",
                "display_name": "Synthetic continuous CRUD QA",
                "password": "SyntheticFixture123!",
            },
        )
        sid = user["spaces"][0]["id"]
        control_collection = await self.post(
            f"/spaces/{sid}/collections", {"name": "Synthetic CRUD controls"}
        )
        control = await self.seed_case(
            control_collection["id"], "SYNTHETIC-CRUD-OTHER-COLLECTION", "P0"
        )
        snapshots = {control["id"]: control["current_revision_id"]}
        conversation = await self.post("/conversations", {"space_id": sid})
        cid = conversation["id"]
        self.report["workspace_ids"].append(cid)
        foreign, decoy = await self.foreign_fixture("SYNTHETIC-CRUD-FOREIGN-PROTECTED")
        try:
            before = await self.collection_names(sid)
            self.stage = "asset_query"
            turn = await self.message(
                cid,
                "查询当前空间有哪些用例集合，仅列出集合，不查询用例、不创建或修改任何数据。",
            )
            base.require(
                has_receipt(turn, {"query_collections"}, "read"),
                "crud_collection_query_receipt_missing",
            )
            base.require(
                await self.collection_names(sid) == before,
                "crud_collection_query_mutated",
            )
            await self.assert_revisions(snapshots)
            self.passed("live_nl_collection_entity_query_is_read_only")
            name = "Synthetic CRUD target " + uuid4().hex[:8]
            created = await self.collection_proposal(
                cid,
                sid,
                f"创建一个新用例集合，名称严格为 {name}。先让我确认，不要创建用例。",
                "create",
                name,
            )
            collection = created["id"]
            base.require(
                await self.request("GET", f"/collections/{collection}/test-cases")
                == [],
                "crud_collection_create_created_cases",
            )
            await self.select_language(
                cid,
                f"将当前工作集合切换到 {name}，清空用例选择，暂不创建或修改用例。",
                {},
                collection,
                snapshots,
            )
            self.passed("live_nl_collection_create_exact_approval_and_select")
            protected = await self.seed_case(
                collection, "SYNTHETIC-CRUD-PROTECTED-P0", "P0"
            )
            snapshots[protected["id"]] = protected["current_revision_id"]

            self.stage = "spreadsheet_upload"
            upload = await self.request(
                "POST",
                f"/conversations/{cid}/attachments",
                files={
                    "files": (
                        "synthetic-crud-requirements.txt",
                        synthetic_requirements(),
                        "text/plain",
                    )
                },
            )
            self.stage = "spreadsheet_index"
            await self.dispatch.drain(self.tasks)
            turn = await self.message(
                cid,
                "请先读取附件中的合成需求，记住两条用例标题标记、数量和优先级。此轮只阅读，不开始生成、修改或删除。",
                document_ids=upload["document_ids"],
            )
            base.require(
                has_receipt(turn, {"read_attachment_evidence", "answer_knowledge"}),
                "crud_attachment_read_receipt_missing",
            )
            await self.dispatch.drain(self.tasks)
            await self.assert_revisions(snapshots)
            self.stage = "generation_request"
            # Intentionally omit document_ids: this turn must inherit the prior attachment.
            await self.message(
                cid,
                "现在按刚才附件中的需求，在当前新集合生成恰好2条新用例，保留附件要求的标题标记和优先级。"
                "不要复用或修改已有P0保护用例。先规划测试点让我确认。",
            )
            self.stage = "brief_worker"
            await self.dispatch.drain(self.tasks)
            workspace = await self.workspace(cid)
            base.require(
                bool(workspace.get("test_briefs")), "crud_generation_brief_missing"
            )
            brief = workspace["test_briefs"][-1]
            base.require(
                bool(brief.get("content", {}).get("planning", {}).get("test_points")),
                "crud_generation_points_missing",
            )
            self.stage = "brief_confirm"
            await self.post(
                f"/workspaces/{cid}/test-briefs/confirm",
                {"version": brief["version"], "model_id": self.model},
            )
            self.stage = "generation_worker"
            await self.dispatch.drain(self.tasks)
            candidates = (await self.workspace(cid)).get("candidates", [])
            base.require(len(candidates) == 2, "crud_candidate_quantity_mismatch")
            self.stage = "adoption"
            adopted = await self.post(
                f"/workspaces/{cid}/candidates/commit",
                {
                    "candidate_ids": [item["id"] for item in candidates],
                    "candidate_versions": {
                        item["id"]: item["version"] for item in candidates
                    },
                },
            )
            good, bad = identify_generated(adopted)
            base.require(
                all(case["id"] not in snapshots for case in adopted),
                "crud_generation_reused_guard",
            )
            await self.assert_revisions(snapshots)
            snapshots.update(
                {case["id"]: case["current_revision_id"] for case in adopted}
            )
            formal = await self.request("GET", f"/collections/{collection}/test-cases")
            base.require(
                {case["id"] for case in formal}
                == {good["id"], bad["id"], protected["id"]},
                "crud_generation_destination_mismatch",
            )
            self.passed("live_nl_attachment_multiturn_creates_exact_two_cases")

            renamed_name = name + " renamed"
            renamed = await self.collection_proposal(
                cid,
                sid,
                f"只把当前集合 {name} 重命名为 {renamed_name}。不修改任何用例，先让我确认。",
                "rename",
                renamed_name,
                collection,
            )
            base.require(
                renamed["id"] == collection, "crud_rename_changed_collection_id"
            )
            await self.assert_revisions(snapshots)
            formal = await self.request("GET", f"/collections/{collection}/test-cases")
            base.require(
                {case["id"] for case in formal}
                == {good["id"], bad["id"], protected["id"]},
                "crud_rename_changed_membership",
            )
            self.passed(
                "live_nl_collection_rename_preserves_entity_and_case_membership"
            )
            selected = await self.select_language(
                cid,
                "选择当前集合里的全部非P0用例，明确排除P0保护用例。只更新选择，不改写。",
                {good["id"]: good, bad["id"]: bad},
                collection,
                snapshots,
            )
            self.passed("live_nl_priority_exclusion_selects_only_created_cases")
            workspace = await self.workspace(cid)
            operations_before = {
                item["id"] for item in workspace.get("operation_history", [])
            }
            self.stage = "asset_query"
            turn = await self.message(
                cid,
                "仅查询当前集合标题包含 SYNTHETIC-CRUD-NO-MATCH-NEVER 的用例。无匹配就说明没有，不更改选择或创建修改删除建议。",
            )
            base.require(
                has_receipt(turn, {"query_assets"}, "read"),
                "crud_no_match_query_receipt_missing",
            )
            workspace = await self.workspace(cid)
            base.require(
                {item["id"] for item in workspace.get("operation_history", [])}
                == operations_before,
                "crud_no_match_created_operation",
            )
            base.require(
                workspace.get("context", {}).get("workbench_selection") == selected,
                "crud_no_match_changed_selection",
            )
            await self.assert_revisions(snapshots)
            self.passed("live_nl_no_match_request_is_non_mutating")

            await self.select_language(
                cid,
                "只选择刚才新生成的错误验证码被拒绝用例，不选成功用例和P0保护用例。",
                {bad["id"]: bad},
                collection,
                snapshots,
            )
            change, version = await self.selected_preview(
                cid, bad, collection, "P2", snapshots
            )
            bad, _ = await self.apply_selected(
                cid, bad, collection, "P2", snapshots, change, version
            )
            self.passed("live_nl_scoped_case_update_preserves_all_other_cases")
            stale_change, stale_review, _ = await self.prepare_delete(
                cid, bad, collection, snapshots
            )
            await self.select_language(
                cid,
                "暂不应用删除预览，把当前选择切换为新生成的有效验证码登录成功用例，只更新选择。",
                {good["id"]: good},
                collection,
                snapshots,
            )
            self.stage = "selection_stale_apply"
            stale = await self.client.post(
                f"/api/v1/case-change-sets/{stale_change}/apply", json=stale_review
            )
            base.require(stale.status_code == 409, "crud_old_scope_delete_not_blocked")
            await self.assert_revisions(snapshots)
            await self.post(f"/case-change-sets/{stale_change}/reject", {})
            self.passed("live_nl_target_switch_blocks_old_delete_preview")
            await self.select_language(
                cid,
                "重新只选择刚才改写过的错误验证码被拒绝用例，保持其他用例不变。",
                {bad["id"]: bad},
                collection,
                snapshots,
            )
            change, review, selected_version = await self.prepare_delete(
                cid, bad, collection, snapshots
            )
            self.stage = "rewrite_apply"
            await self.post(f"/case-change-sets/{change}/apply", review)
            deleted = await self.client.get(f"/api/v1/test-cases/{bad['id']}")
            base.require(
                deleted.status_code == 404, "crud_soft_deleted_case_still_visible"
            )
            snapshots.pop(bad["id"])
            await self.assert_revisions(snapshots)
            state = base.validate_selection(
                await self.workspace(cid), {}, collection, previous=selected_version
            )
            base.require(
                state.get("items") == [], "crud_deleted_target_left_in_selection"
            )
            repeated = await self.client.post(
                f"/api/v1/case-change-sets/{change}/apply", json=review
            )
            base.require(
                repeated.status_code in {200, 409},
                "crud_delete_replay_unexpected_status",
            )
            base.require(
                (await self.client.get(f"/api/v1/test-cases/{bad['id']}")).status_code
                == 404,
                "crud_delete_replay_restored_case",
            )
            await self.assert_revisions(snapshots)
            formal = await self.request("GET", f"/collections/{collection}/test-cases")
            base.require(
                {case["id"] for case in formal} == {good["id"], protected["id"]},
                "crud_delete_changed_nontarget_membership",
            )
            foreign_after = await foreign.get(f"/api/v1/test-cases/{decoy['id']}")
            base.require(
                foreign_after.status_code == 200
                and foreign_after.json()["current_revision_id"]
                == decoy["current_revision_id"],
                "crud_foreign_guard_changed",
            )
            self.passed(
                "live_nl_soft_delete_exact_approval_replay_and_guard_preservation"
            )
        finally:
            await foreign.aclose()


async def execute_crud(key, model, budget, report, storage):
    # Load the adapter before the scoped driver patch to preserve its base class.
    import workbench_crud_continuation  # noqa: F401
    # Select only the harness driver; production model/tools/domain methods remain untouched.
    with (
        patch.object(base, "Journey", CrudJourney),
        patch.dict(
            base.TASKS, {"casepilot.agent.answer_question": "answer_knowledge_question"}
        ),
    ):
        checkpoint = getattr(budget, "checkpoint", None)
        options = {"checkpoint": checkpoint} if checkpoint is not None else {}
        await base.execute(key, model, budget, {"crud_continuous"}, report, storage, **options)


def main(argv=None):
    arguments = parser(__doc__)
    arguments.set_defaults(max_requests=150)
    arguments.add_argument("--checkpoint-path", default=None,
                           help="Private checkpoint on a marked fresh synthetic DB; never resumes")
    arguments.add_argument(
        "--storage-dir",
        default=str(Path(tempfile.gettempdir()) / "casepilot-live-synthetic-crud"),
    )
    args = arguments.parse_args(argv)
    disable_sensitive_logging()
    budget = RequestBudget(args.max_requests, emit_json)
    report = {
        "event": "summary",
        "scope": "synthetic_continuous_nl_crud",
        "passed": False,
        "browser_ui_tested": False,
        "collection_delete_tested": False,
        "checks": [],
        "workspace_ids": [],
        "embedding_provider": "disabled",
    }
    key = ""
    try:
        key = read_key(args)
        if args.checkpoint_path:
            budget.checkpoint = create_writer(args.checkpoint_path, base.ROOT, budget, report,
                stages=STAGES, checks=CONTINUOUS_CHECKS, emit=emit_json,
                scope="continuous_synthetic_chain")
            budget.before_request = budget.checkpoint.before_request
            budget.checkpoint.save("pending")
        Path(args.storage_dir).mkdir(parents=True, exist_ok=True)
        asyncio.run(execute_crud(key, args.model, budget, report, args.storage_dir))
        report["passed"] = len(report["checks"]) == 9 and all(
            check["passed"] for check in report["checks"]
        )
        if args.checkpoint_path:
            budget.checkpoint.save("finished" if report["passed"] else "pending")
    except Exception as exc:  # noqa: BLE001 -- Same privacy boundary as the base harness.
        report["passed"] = False
        code = (
            exc.args[0]
            if isinstance(exc, (base.JourneyFailure, SafetyStop)) and exc.args
            else None
        )
        observed = budget.stop_code or code
        report["error_code"] = (
            observed
            if isinstance(observed, str) and observed in FAILURE_CODES
            else "crud_journey_failed"
        )
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
