"""Source-owned review notes remain unverified before and after human adoption."""

from copy import deepcopy
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_planning_review_lifecycle import PLAN
from test_workbench_bridge_integration import setup

from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import (
    ConversationMessage,
    GenerationJob,
    WorkspaceCandidate,
    WorkspaceTestBrief,
)


@pytest.mark.asyncio
async def test_review_state_is_projected_without_messages_and_adoption_does_not_certify():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, collection, workspace = await setup(client)
        quality = {
            "passed": True,
            "structural_passed": True,
            "grounding_status": "unverified",
            "issues": [
                {
                    "code": "planning_source_unverified",
                    "object_id": "p1",
                    "severity": "warning",
                    "message": "独立原文未规定该环境，规划仍待复核",
                }
            ],
        }
        plan = deepcopy(PLAN)
        snapshot = {
            "id": "TC-p1",
            "title": "Synthetic case",
            "module": "Synthetic",
            "priority": "P1",
            "case_type": "功能",
            "preconditions": [],
            "steps": [
                {
                    "action": "Execute the specified operation",
                    "expected": "Observe source-defined result",
                }
            ],
            "test_point_ids": ["p1"],
            "source_refs": [],
        }
        with get_session_factory()() as db:
            job = GenerationJob(
                space_id=UUID(workspace["space_id"]),
                account_id=UUID(account["id"]),
                collection_id=UUID(collection["id"]),
                operation="generate",
                status="completed",
                stage="completed",
                input_payload={
                    "conversation_id": workspace["id"],
                    "confirmed_test_brief_version": 1,
                },
                output_payload={"quality": quality, "test_cases": [snapshot]},
            )
            db.add(job)
            db.flush()
            brief = WorkspaceTestBrief(
                conversation_id=UUID(workspace["id"]),
                version=1,
                content={"test_object": "Synthetic", "planning": plan},
                status="confirmed",
            )
            db.add(brief)
            candidate = WorkspaceCandidate(
                conversation_id=UUID(workspace["id"]),
                generation_job_id=job.id,
                ref="TC-p1",
                version=1,
                position=0,
                snapshot=snapshot,
                included=True,
                status="candidate",
            )
            db.add(candidate)
            db.commit()
            job_id = str(job.id)
            candidate_id = str(candidate.id)
        # No job-linked message: disclosure must follow each candidate's real job.
        view = (await client.get("/api/v1/conversations/" + workspace["id"])).json()
        review = view["generation_reviews"][job_id]
        assert review["status"] == "pending_manual"
        assert review["independent_quality_verified"] is False
        assert review["issues"] == quality["issues"]
        adopted = await client.post(
            "/api/v1/workspaces/" + workspace["id"] + "/candidates/commit",
            json={"candidate_ids": [candidate_id], "candidate_versions": {candidate_id: 1}},
        )
        assert adopted.status_code == 200, adopted.text
        with get_session_factory()() as db:
            assert db.get(GenerationJob, UUID(job_id)).output_payload["quality"] == quality
            saved = db.scalar(
                select(WorkspaceTestBrief).where(
                    WorkspaceTestBrief.conversation_id == UUID(workspace["id"])
                )
            )
            assert saved.content["planning"]["coverage_review"] == plan["coverage_review"]
            message = db.scalar(
                select(ConversationMessage).where(
                    ConversationMessage.conversation_id == UUID(workspace["id"]),
                    ConversationMessage.message_metadata["action"].astext == "candidates_committed",
                )
            )
            assert (
                message.message_metadata["generation_review_states"][job_id][
                    "independent_quality_verified"
                ]
                is False
            )
        after = (await client.get("/api/v1/conversations/" + workspace["id"])).json()
        assert after["generation_reviews"][job_id] == review


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    ["foreign_conversation", "foreign_owner", "malformed", "malformed_output", "self_certified"],
)
async def test_unreadable_or_foreign_review_never_becomes_certified_or_leaks(kind):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, collection, workspace = await setup(client)
        other = (
            await client.post("/api/v1/conversations", json={"collection_id": collection["id"]})
        ).json()
        owner_id = UUID(account["id"])
        if kind == "foreign_owner":
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as stranger:
                foreign, _, _ = await setup(stranger)
                owner_id = UUID(foreign["id"])
        quality = {
            "passed": True,
            "independent_quality_verified": True,
            "grounding_status": "model_reviewed",
            "issues": [{"code": "note", "message": "private_foreign_note", "severity": "warning"}],
        }
        if kind == "malformed":
            quality = {"passed": True, "grounding_status": {}, "issues": 42}
        with get_session_factory()() as db:
            job = GenerationJob(
                space_id=UUID(workspace["space_id"]),
                account_id=owner_id,
                operation="generate",
                status="completed",
                stage="completed",
                input_payload={
                    "conversation_id": other["id"]
                    if kind == "foreign_conversation"
                    else workspace["id"]
                },
                output_payload=["malformed"]
                if kind == "malformed_output"
                else {"quality": quality},
            )
            db.add(job)
            db.flush()
            from casepilot_api.models import GenerationJobStage

            if kind in {"foreign_conversation", "foreign_owner"}:
                db.add(
                    GenerationJobStage(
                        generation_job_id=job.id,
                        stage="test_case.semantics_checked",
                        attempt=1,
                        status="completed",
                        input_payload={},
                        input_hash="foreign-history",
                        output_payload={
                            "checks": [{"slot": 1, "assertion_risks": ["private_foreign_risk"]}]
                        },
                    )
                )
            db.add(
                WorkspaceCandidate(
                    conversation_id=UUID(workspace["id"]),
                    generation_job_id=job.id,
                    ref="Synthetic",
                    version=1,
                    position=0,
                    snapshot={},
                    included=True,
                    status="candidate",
                )
            )
            db.commit()
            jid = str(job.id)
        response = await client.get("/api/v1/conversations/" + workspace["id"])
        assert response.status_code == 200, response.text
        review = response.json()["generation_reviews"][jid]
        assert review["independent_quality_verified"] is False
        if kind in {"foreign_conversation", "foreign_owner", "malformed_output"}:
            assert "private_foreign_note" not in response.text
            assert "private_foreign_risk" not in response.text
            assert review["status"] == "not_assessed" and review["issues"] == []
        elif kind == "malformed":
            assert review["status"] == "not_assessed"
            assert review["issues"][0]["code"] == "review_record_incomplete"
        else:
            assert (
                review["status"] == "pending_manual"
                and review["grounding_status"] == "model_reviewed"
            )


@pytest.mark.asyncio
async def test_earlier_risks_survive_empty_recheck_without_certifying_current_case():
    from casepilot_api.models import GenerationJobStage

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, _, workspace = await setup(client)
        with get_session_factory()() as db:
            job = GenerationJob(
                space_id=UUID(workspace["space_id"]),
                account_id=UUID(account["id"]),
                operation="generate",
                status="completed",
                stage="completed",
                input_payload={"conversation_id": workspace["id"]},
                output_payload={
                    "quality": {"passed": True, "grounding_status": "unverified", "issues": []}
                },
            )
            db.add(job)
            db.flush()
            for attempt, risks in [(1, ["附加完成标准缺少原文依据"]), (2, []), (3, None)]:
                db.add(
                    GenerationJobStage(
                        generation_job_id=job.id,
                        stage="test_case.semantics_checked",
                        attempt=attempt,
                        status="completed",
                        input_payload={},
                        output_payload={
                            "checks": [{"slot": 1, "errors": [], "assertion_risks": risks}]
                        },
                        input_hash=str(attempt),
                    )
                )
            candidate = WorkspaceCandidate(
                conversation_id=UUID(workspace["id"]),
                generation_job_id=job.id,
                ref="Retried",
                version=1,
                position=0,
                snapshot={
                    "title": "Retried source-defined case",
                    "steps": [
                        {
                            "action": "Execute specified operation",
                            "expected": "Observe source-defined result",
                        }
                    ],
                },
                included=True,
                status="candidate",
            )
            db.add(candidate)
            db.commit()
            jid = str(job.id)
            cid = str(candidate.id)
        response = await client.get("/api/v1/conversations/" + workspace["id"])
        assert response.status_code == 200, response.text
        review = response.json()["generation_reviews"][jid]
        assert (
            review["status"] == "pending_manual" and review["independent_quality_verified"] is False
        )
        history = [i for i in review["issues"] if i["code"] == "prior_assertion_risk"]
        assert len(history) == 1
        assert history[0]["message"].endswith("附加完成标准缺少原文依据")
        assert any(i["code"] == "prior_review_record_unreadable" for i in review["issues"])
        with get_session_factory()() as db:
            assert db.get(GenerationJob, UUID(jid)).output_payload["quality"]["issues"] == []

        adopted = await client.post(
            "/api/v1/workspaces/" + workspace["id"] + "/candidates/commit",
            json={"candidate_ids": [cid], "candidate_versions": {cid: 1}},
        )
        assert adopted.status_code == 200, adopted.text
        after = (await client.get("/api/v1/conversations/" + workspace["id"])).json()
        assert after["generation_reviews"][jid] == review
