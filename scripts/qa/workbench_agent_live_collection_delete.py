#!/usr/bin/env python3
"""Synthetic NL collection soft-delete acceptance; no hard-delete or restore claim.

Only the harness driver is selected. Real API, model and business outputs remain
untouched. Direct DB writes are limited to an explicit synthetic shared-membership
fixture; all subsequent DB access is read-only, scoped and never serialized.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import workbench_agent_live_crud as crud
import workbench_agent_live_journey as base
from workbench_agent_live_acceptance import (
    RequestBudget,
    SafetyStop,
    disable_sensitive_logging,
    emit_json,
    exception_name,
    parser,
    read_key,
)
from workbench_collection_continuation import (
    await_collection_proposal,
    finish_collection_approval,
)

CODES = crud.FAILURE_CODES | frozenset(
    {
        "collection_delete_journey_failed",
        "durable_binding_missing",
        "durable_approval_step_invalid",
        "durable_approval_event_invalid",
        "durable_approval_outbox_invalid",
        "durable_approval_not_completed",
        "durable_binding_changed",
        "durable_proposal_binding_invalid",
        "durable_proposal_receipt_missing",
        "durable_no_deliverable_continuation",
        "durable_proposal_not_ready",
        "durable_wait_timeout",
        "outbox_continuation_scope_mismatch",
        "outbox_delivery_failed",
        "durable_worker_failed",
        "unexpected_task_dispatch",
        "delete_proposal_invalid",
        "delete_receipt_missing",
        "delete_impact_invalid",
        "delete_preapproval_write",
        "delete_wrong_payload_accepted",
        "delete_changed_impact_accepted",
        "delete_rejection_failed",
        "delete_result_invalid",
        "delete_replay_changed_result",
        "delete_assets_or_memberships_changed",
        "delete_soft_state_invalid",
        "delete_audit_count_invalid",
        "delete_canonical_invalid",
        "delete_foreign_changed",
        "delete_collection_visibility_invalid",
    }
)


def exact_proposal(turn, collection, name, count):
    proposal = turn.get("action", {}).get("proposal") or {}
    base.require(
        turn.get("action", {}).get("type") == "collection_proposal"
        and proposal.get("status") == "pending"
        and proposal.get("action") == "delete"
        and proposal.get("collection_id") == collection
        and proposal.get("name") == name,
        "delete_proposal_invalid",
    )
    base.require(
        crud.has_receipt(turn, {"delete_collection"}, "prepare"),
        "delete_receipt_missing",
    )
    base.require(
        proposal.get("impact")
        == {
            "member_case_count": count,
            "affected_conversation_count": 1,
        },
        "delete_impact_invalid",
    )
    return proposal


def verify_catalog_removal(before, after, target):
    expected = {item["id"]: item["name"] for item in before}
    base.require(target in expected, "delete_collection_visibility_invalid")
    del expected[target]
    actual = {item["id"]: item["name"] for item in after}
    base.require(
        len(actual) == len(after) and actual == expected,
        "delete_collection_visibility_invalid",
    )


def seed_shared_membership(collection, case):
    from casepilot_api.database import get_session_factory
    from casepilot_api.models import CollectionCaseMembership

    with get_session_factory()() as db:
        db.add(
            CollectionCaseMembership(
                collection_id=UUID(collection),
                test_case_id=UUID(case),
                position=0,
            )
        )
        db.commit()


def snapshot(collection, cases):
    """Internal synthetic IDs only; return value is never logged or emitted."""
    from casepilot_api.database import get_session_factory
    from casepilot_api.models import (
        AuditEvent,
        CaseCollection,
        CollectionCaseMembership,
        TestCase,
        TestCaseRevision,
    )
    from sqlalchemy import select

    ids = [UUID(value) for value in cases]
    with get_session_factory()() as db:
        row = db.get(CaseCollection, UUID(collection))
        return {
            "deleted": row.deleted_at is not None,
            "cases": sorted(
                (str(row.id), str(row.current_revision_id), str(row.deleted_at))
                for row in db.scalars(select(TestCase).where(TestCase.id.in_(ids)))
            ),
            "revisions": sorted(
                str(row.id)
                for row in db.scalars(
                    select(TestCaseRevision).where(
                        TestCaseRevision.test_case_id.in_(ids)
                    )
                )
            ),
            "memberships": sorted(
                (str(row.id), str(row.collection_id), str(row.test_case_id))
                for row in db.scalars(
                    select(CollectionCaseMembership).where(
                        CollectionCaseMembership.test_case_id.in_(ids)
                    )
                )
            ),
            "audit_count": len(
                list(
                    db.scalars(
                        select(AuditEvent.id).where(
                            AuditEvent.resource_id == UUID(collection),
                            AuditEvent.action == "collection.deleted",
                        )
                    )
                )
            ),
        }


def preserved(before, after):
    base.require(
        all(before[key] == after[key] for key in ("cases", "revisions", "memberships")),
        "delete_assets_or_memberships_changed",
    )


class CollectionDeleteJourney(base.Journey):
    async def proposal(self, cid, collection, name, cases):
        before = snapshot(collection, cases)
        self.stage = "selection_update"
        turn = await self.message(
            cid,
            f"请软删除当前集合 {name}（仅删除集合实体），保留全部用例资产和历史版本。先给出影响汇总并等待我精确确认，不能直接删除。",
        )
        self._approval_source_turn = turn
        turn = await await_collection_proposal(cid, turn, self.tasks, self.report)
        proposed = exact_proposal(turn, collection, name, len(cases) - 1)
        base.require(snapshot(collection, cases) == before, "delete_preapproval_write")
        return proposed

    async def run(self, scenarios):
        self.stage = "setup"
        user = await self.post(
            "/auth/register",
            {
                "email": f"delete-synthetic-{uuid4().hex}@casepilot.test",
                "display_name": "Synthetic collection deletion QA",
                "password": "SyntheticFixture123!",
            },
        )
        sid = user["spaces"][0]["id"]
        name = "Synthetic delete target " + uuid4().hex[:8]
        cid, collection = await self.create_workspace(sid, name)
        other = await self.post(
            f"/spaces/{sid}/collections", {"name": "Synthetic retained collection"}
        )
        shared = await self.seed_case(collection, "SYNTHETIC-SHARED", "P1")
        exclusive = await self.seed_case(collection, "SYNTHETIC-TARGET-ONLY", "P2")
        protected = await self.seed_case(other["id"], "SYNTHETIC-PROTECTED", "P0")
        seed_shared_membership(other["id"], shared["id"])
        self.report["synthetic_db_membership_seeded"] = True
        cases = [shared["id"], exclusive["id"], protected["id"]]
        # Explicit QA state setup, not a claim that model selected these fixtures.
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
                    for case in (shared, exclusive)
                ],
            },
        )
        foreign, decoy = await self.foreign_fixture("SYNTHETIC-FOREIGN-DELETE-GUARD")
        try:
            foreign_before = await foreign.get(f"/api/v1/test-cases/{decoy['id']}")
            base.require(foreign_before.status_code == 200, "delete_foreign_changed")
            first = await self.proposal(cid, collection, name, cases)
            path = f"/workspaces/{cid}/collection-proposals/{first['id']}"
            payload = {"name": name, "collection_id": collection}
            before = snapshot(collection, cases)
            for wrong in (
                {**payload, "name": name + " wrong"},
                {**payload, "collection_id": other["id"]},
            ):
                result = await self.client.post(
                    "/api/v1" + path + "/confirm", json=wrong
                )
                base.require(result.status_code == 409, "delete_wrong_payload_accepted")
                base.require(
                    snapshot(collection, cases) == before, "delete_preapproval_write"
                )
            self.passed("nl_delete_proposal_exact_identity_impact_and_no_early_write")
            added = await self.seed_case(collection, "SYNTHETIC-IMPACT-CHANGE", "P2")
            cases.append(added["id"])
            before = snapshot(collection, cases)
            stale = await self.client.post("/api/v1" + path + "/confirm", json=payload)
            base.require(stale.status_code == 409, "delete_changed_impact_accepted")
            base.require(
                snapshot(collection, cases) == before, "delete_preapproval_write"
            )
            rejected = await self.post(path + "/reject", {})
            base.require(rejected == {"status": "rejected"}, "delete_rejection_failed")
            self.passed("changed_membership_blocks_old_approval_then_reject")
            fresh = await self.proposal(cid, collection, name, cases)
            path = f"/workspaces/{cid}/collection-proposals/{fresh['id']}/confirm"
            selected_before = (await self.workspace(cid))["context"][
                "workbench_selection"
            ]
            before = snapshot(collection, cases)
            catalog_before = await self.request("GET", f"/spaces/{sid}/collections")
            result = await self.post(path, payload)
            base.require(
                result
                == {
                    "action": "delete",
                    "collection_id": collection,
                    "name": name,
                    "deleted": True,
                    "preserved_assets": True,
                },
                "delete_result_invalid",
            )
            after = snapshot(collection, cases)
            preserved(before, after)
            base.require(
                not before["deleted"] and after["deleted"], "delete_soft_state_invalid"
            )
            base.require(
                before["audit_count"] == 0 and after["audit_count"] == 1,
                "delete_audit_count_invalid",
            )
            workspace = await self.workspace(cid)
            state = workspace["context"]["workbench_selection"]
            base.require(
                workspace["id"] == cid
                and workspace.get("collection_id") is None
                and state.get("active_collection_id") is None
                and state["version"] > selected_before["version"]
                and state.get("changed_by") == "approved_collection_delete"
                and len(state.get("items", [])) == 1
                and state["items"][0].get("case_id") == shared["id"]
                and state["items"][0].get("collection_ids") == [other["id"]],
                "delete_canonical_invalid",
            )
            visible = await self.request("GET", f"/spaces/{sid}/collections")
            verify_catalog_removal(catalog_before, visible, collection)
            self.passed(
                "exact_approval_soft_deletes_collection_preserves_assets_and_unbinds_workspace"
            )
            replay = await self.post(path, payload)
            base.require(replay == result, "delete_replay_changed_result")
            base.require(
                snapshot(collection, cases) == after, "delete_replay_changed_result"
            )
            remaining = await self.request(
                "GET", f"/collections/{other['id']}/test-cases"
            )
            base.require(
                {item["id"] for item in remaining} == {shared["id"], protected["id"]},
                "delete_assets_or_memberships_changed",
            )
            foreign_after = await foreign.get(f"/api/v1/test-cases/{decoy['id']}")
            base.require(
                foreign_after.status_code == 200
                and foreign_after.json() == foreign_before.json(),
                "delete_foreign_changed",
            )
            self.passed(
                "duplicate_confirmation_single_audit_and_foreign_guard_preserved"
            )
            await finish_collection_approval(
                cid, self._approval_source_turn, fresh, self.tasks, self.report)
            base.require(snapshot(collection, cases) == after, "delete_replay_changed_result")
        finally:
            await foreign.aclose()


async def execute_delete(key, model, budget, report, storage):
    with patch.object(base, "Journey", CollectionDeleteJourney):
        await base.execute(key, model, budget, {"collection_delete"}, report, storage)


def main(argv=None):
    arguments = parser(__doc__)
    arguments.set_defaults(max_requests=40)
    arguments.add_argument(
        "--storage-dir",
        default=str(Path(tempfile.gettempdir()) / "casepilot-live-collection-delete"),
    )
    args = arguments.parse_args(argv)
    disable_sensitive_logging()
    budget = RequestBudget(args.max_requests, emit_json)
    report = {
        "event": "summary",
        "scope": "synthetic_nl_collection_soft_delete",
        "passed": False,
        "hard_delete_tested": False,
        "restore_tested": False,
        "browser_ui_tested": False,
        "checks": [],
        "workspace_ids": [],
        "embedding_provider": "disabled",
    }
    key = ""
    try:
        key = read_key(args)
        Path(args.storage_dir).mkdir(parents=True, exist_ok=True)
        asyncio.run(execute_delete(key, args.model, budget, report, args.storage_dir))
        report["passed"] = len(report["checks"]) == 4 and all(
            item["passed"] for item in report["checks"]
        )
    except Exception as exc:  # noqa: BLE001 -- Never expose provider messages or credential-bearing errors.
        code = (
            exc.args[0]
            if isinstance(exc, (base.JourneyFailure, SafetyStop)) and exc.args
            else None
        )
        observed = budget.stop_code or code
        report["error_code"] = (
            observed
            if isinstance(observed, str) and observed in CODES
            else "collection_delete_journey_failed"
        )
        report["exception_class"] = exception_name(exc)
    finally:
        key = ""
    report.update(budget.summary())
    emit_json(report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
