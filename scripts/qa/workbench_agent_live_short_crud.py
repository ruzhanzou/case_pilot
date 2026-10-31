#!/usr/bin/env python3
"""Opt-in independent SHORT synthetic CRUD gates with private evidence checkpoints.

Each invocation seeds fresh fixtures. This is NOT a continuation of an interrupted
continuous journey and cannot establish continuous-chain acceptance. No DB boot,
restart, PID removal, credential storage, or checkpoint resume is implemented.
Use the fresh rootless wrapper with CASEPILOT_QA_MARK_SYNTHETIC=1.
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import workbench_agent_live_crud as crud
import workbench_agent_live_journey as base
from workbench_agent_live_acceptance import (
    STAGES,
    RequestBudget,
    disable_sensitive_logging,
    emit_json,
    exception_name,
    parser,
    read_key,
)
from workbench_domain_diagnostics import safe_domain_failure
from workbench_qa_checkpoint import create_writer

CHECKS = frozenset({
    "short_collection_create_rename_exact_review",
    "short_query_selection_is_read_only",
    "short_delete_exact_review_replay_and_guards",
    "live_canonical_payload_binding_and_exact_two_case_ready_preview",
    "live_canonical_two_case_exact_apply_preserves_unselected_and_foreign",
    "live_canonical_reapply_preserves_revisions_and_selection",
})
EXPECTED = {"collection": 1, "query_selection": 1, "rewrite": 3, "delete": 1}


class CheckpointBudget(RequestBudget):
    checkpoint = None

    def reserve(self):
        record = super().reserve()
        # A durable pending record is written BEFORE transport sends this call.
        # Persistence failure aborts the request, conservatively counting it.
        if self.checkpoint is not None:
            self.checkpoint.before_request(record)
        return record


class ShortCrudJourney(crud.CrudJourney):
    short_stage = "query_selection"
    checkpoint = None

    async def run(self, _scenarios):
        self.stage = "setup"
        user = await self.post("/auth/register", {
            "email": f"short-synthetic-{uuid4().hex}@casepilot.test",
            "display_name": "Synthetic independent short QA", "password": "SyntheticFixture123!",
        })
        sid = user["spaces"][0]["id"]
        if self.short_stage == "rewrite":
            # Same exact two-case diff/apply/replay and foreign-preservation gates.
            await self.canonical_rewrite(sid)
            return
        cid, collection = await self.create_workspace(sid, "Synthetic short scope")
        chosen = await self.seed_case(collection, "SYNTHETIC-SHORT-TARGET", "P2")
        protected = await self.seed_case(collection, "SYNTHETIC-SHORT-PROTECTED", "P0")
        foreign, decoy = await self.foreign_fixture("SYNTHETIC-SHORT-FOREIGN")
        snapshots = {case["id"]: case["current_revision_id"] for case in (chosen, protected)}
        try:
            if self.short_stage == "collection":
                name = "Synthetic short new " + uuid4().hex[:8]
                created = await self.collection_proposal(cid, sid,
                    f"创建集合，名称严格为 {name}，先让我确认，不创建用例。", "create", name)
                renamed = name + " renamed"
                await self.collection_proposal(cid, sid,
                    f"将集合 {name} 重命名为 {renamed}，先让我确认，不修改用例。",
                    "rename", renamed, created["id"])
                base.require(await self.request("GET", f"/collections/{created['id']}/test-cases")
                             == [], "crud_collection_create_created_cases")
            else:
                self.stage = "asset_query"
                turn = await self.message(cid,
                    "查询当前集合用例，列出标题和优先级，不修改、不生成、不删除。")
                base.require(crud.has_receipt(turn, {"query_assets"}, "read"),
                             "crud_collection_query_receipt_missing")
                base.require(not self.dispatch.queue and not (
                    await self.workspace(cid)).get("candidates"), "asset_query_created_candidates")
                await self.select_language(cid,
                    "只选中标题为 SYNTHETIC-SHORT-TARGET 的用例，保留其他用例不变。",
                    {chosen["id"]: chosen}, collection, snapshots)
                if self.short_stage == "delete":
                    change, review, version = await self.prepare_delete(
                        cid, chosen, collection, snapshots)
                    self.stage = "rewrite_apply"
                    await self.post(f"/case-change-sets/{change}/apply", review)
                    base.require((await self.client.get(
                        f"/api/v1/test-cases/{chosen['id']}")).status_code == 404,
                        "crud_delete_replay_restored_case")
                    repeated = await self.client.post(
                        f"/api/v1/case-change-sets/{change}/apply", json=review)
                    base.require(repeated.status_code in {200, 409},
                                 "crud_delete_replay_unexpected_status")
                    state = base.validate_selection(await self.workspace(cid), {}, collection,
                                                    previous=version)
                    base.require(not state["items"], "crud_deleted_target_left_in_selection")
                    formal = await self.request("GET", f"/collections/{collection}/test-cases")
                    base.require({case["id"] for case in formal} == {protected["id"]},
                                 "crud_delete_changed_nontarget_membership")
                    snapshots.pop(chosen["id"])
            await self.assert_revisions(snapshots)
            after = await foreign.get(f"/api/v1/test-cases/{decoy['id']}")
            base.require(after.status_code == 200 and after.json()["current_revision_id"]
                         == decoy["current_revision_id"], "crud_foreign_guard_changed")
            self.passed({
                "collection": "short_collection_create_rename_exact_review",
                "query_selection": "short_query_selection_is_read_only",
                "delete": "short_delete_exact_review_replay_and_guards",
            }[self.short_stage])
        finally:
            await foreign.aclose()


async def execute_short(key, model, budget, report, storage, stage, checkpoint):
    class Driver(ShortCrudJourney):
        pass
    Driver.short_stage, Driver.checkpoint = stage, checkpoint
    with patch.object(base, "Journey", Driver):
        await base.execute(key, model, budget, {stage}, report, storage)


def make_checkpoint(path, budget, report):
    return create_writer(path, base.ROOT, budget, report, stages=STAGES, checks=CHECKS,
                         emit=emit_json)


def main(argv=None):
    arguments = parser(__doc__)
    arguments.set_defaults(max_requests=30)
    arguments.add_argument("--stage", required=True, choices=EXPECTED)
    arguments.add_argument("--checkpoint", required=True,
                           help="Explicit private local checkpoint file; no resume")
    arguments.add_argument("--storage-dir", default=str(
        Path(tempfile.gettempdir()) / "casepilot-live-short-synthetic"))
    args = arguments.parse_args(argv)
    disable_sensitive_logging()
    budget = CheckpointBudget(args.max_requests, emit_json)
    report = {"event": "summary", "scope": "independent_short_synthetic_stage",
              "short_stage": args.stage, "passed": False, "checks": [], "workspace_ids": [],
              "continuous_chain_passed": False, "resume_allowed": False,
              "browser_ui_tested": False, "embedding_provider": "disabled"}
    key = ""
    try:
        key = read_key(args)
        checkpoint = make_checkpoint(args.checkpoint, budget, report)
        budget.checkpoint = checkpoint
        checkpoint.save("pending")
        Path(args.storage_dir).mkdir(parents=True, exist_ok=True)
        asyncio.run(execute_short(key, args.model, budget, report, args.storage_dir,
                                 args.stage, checkpoint))
        report["passed"] = (len(report["checks"]) == EXPECTED[args.stage]
                            and all(item["passed"] is True for item in report["checks"]))
        checkpoint.save("finished" if report["passed"] else "pending")
    except Exception as error:  # noqa: BLE001 -- Never leak provider/credential exception text.
        report["passed"] = False
        report["exception_class"] = exception_name(error)
        report["domain_failure"] = safe_domain_failure(error)
        code = error.args[0] if error.args and isinstance(error.args[0], str) else None
        report["error_code"] = (code if code in crud.FAILURE_CODES
                                else "short_stage_failed")
    finally:
        key = ""
    report.update(budget.summary())
    emit_json(report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
