import pytest
from test_workbench_agent import Args, Provider, action, answer, call, run

from casepilot_api.workbench_agent import FinalAnswer, ModelTurn, ToolSpec


def clarification():
    return ModelTurn(final=FinalAnswer(kind="clarify", message="Please fix parameters"))


def rejection():
    return {"error_code": "workbench_plan_step_mismatch", "recoverable_plan_step": True,
            "requires_user_input": False, "current_action": "CASE_QUERY", "applied": False}


def test_model_can_recover_internal_mismatch_within_same_five_turn_budget():
    reads, drafts = [], []

    def prepare(_):
        if not reads:
            return rejection()
        drafts.append(True)
        return {"status": "queued", "applied": False}

    provider = Provider(call("prepare"), clarification(), call("query", "two"),
                        call("prepare", "three"), action)
    result = run(provider, [
        ToolSpec("prepare", "Draft only", Args, prepare, "prepare"),
        ToolSpec("query", "Read only", Args, lambda _: reads.append(True) or {}),
    ], max_turns=5)
    assert result.error_code is None and len(provider.requests) == 5
    assert reads == [True] and drafts == [True]
    assert sum(e["type"] == "final_correction" for e in result.events) == 1


def test_repeated_internal_mismatch_is_explicit_failure_not_fake_approval():
    result = run(Provider(call("prepare"), clarification(), clarification()), [
        ToolSpec("prepare", "Draft only", Args, lambda _: rejection(), "prepare"),
    ], max_turns=3)
    assert result.status == "failed" and result.error_code == "agent_preparation_unresolved"
    assert result.final is None


@pytest.mark.parametrize("code", ["plan_authority_changed", "workbench_source_changed",
                                  "reuse_destination_name_ambiguous"])
def test_real_authority_or_user_ambiguity_is_never_auto_retried(code):
    provider = Provider(call("prepare"), clarification())
    result = run(provider, [ToolSpec("prepare", "Draft only", Args,
        lambda _: {"error_code": code}, "prepare")])
    assert result.status == "awaiting_input" and len(provider.requests) == 2
    assert not any(e["type"] == "final_correction" for e in result.events)


def test_plain_explanation_does_not_create_a_plan_or_preparation():
    provider = Provider(answer("An explanation"))
    result = run(provider)
    assert result.status == "completed" and result.tool_results == []


@pytest.mark.asyncio
async def test_real_pg_plan_mismatch_recovers_to_exact_unapplied_proposal(monkeypatch):
    from uuid import UUID, uuid4

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import select
    from test_workbench_bridge_integration import setup
    from test_workbench_required_plan import activate_explicit

    from casepilot_api.database import get_session_factory
    from casepilot_api.main import app
    from casepilot_api.models import CaseCollection, WorkbenchRun

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, collection, workspace = await setup(client)
        args = {"collection_id": collection["id"], "name": "Reviewed rename"}
        provider = activate_explicit(monkeypatch, [
            ("rename_collection", {**args, "plan": {
                "steps": ["读取集合", "提出重命名供审阅"],
                "plan_actions": ["COLLECTION_QUERY", "COLLECTION_RENAME"],
            }}),
            FinalAnswer(kind="clarify", message="Please confirm internal parameters"),
            ("query_collections", {"search": ""}),
            ("rename_collection", args),
        ])
        response = await client.post(f"/api/v1/conversations/{workspace['id']}/messages", json={
            "content": "先查询当前集合，再将它重命名为Reviewed rename，只给我预览，不应用。",
            "client_request_id": str(uuid4()),
        })
        assert response.status_code == 202
        rejection = next(x for x in provider.outputs()
                         if x.get("error_code") == "workbench_plan_step_mismatch")
        assert rejection["current_action"] == "COLLECTION_QUERY"
        assert rejection["recoverable_plan_step"] is True
        with get_session_factory()() as db:
            run_row = db.scalar(select(WorkbenchRun).where(
                WorkbenchRun.conversation_id == UUID(workspace["id"])))
            assert run_row.status == "waiting_approval" and run_row.cursor == 1
            assert run_row.plan["steps"][0]["receipt_ids"]
            assert run_row.checkpoint["waiting_artifact_kind"] == "collection_proposal"
            assert db.get(CaseCollection, UUID(collection["id"])).name == collection["name"]
