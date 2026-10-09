"""Persisted workflow boundaries; model output is controlled and no worker is dispatched."""

import asyncio
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from casepilot_api import conversations
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import Account, Space


@pytest.mark.asyncio
async def test_analysis_to_candidates_keeps_history_and_blocks_overlapping_messages(monkeypatch):
    from casepilot_agent.store import JobStore

    monkeypatch.setattr(conversations, "enqueue_task", lambda *args, **kwargs: None)
    store = JobStore(conversations.settings.database_url, conversations.settings.redis_url)
    space_id = account_id = None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            registration = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"workflow-{uuid4().hex}@casepilot.test",
                    "display_name": "Workflow test",
                    "password": "CasePilot123!",
                },
            )
            assert registration.status_code == 201
            account_id = registration.json()["id"]
            space_id = registration.json()["spaces"][0]["id"]
            collections = (await client.get(f"/api/v1/spaces/{space_id}/collections")).json()
            collection_id = collections[0]["id"]
            case = (
                await client.post(
                    f"/api/v1/collections/{collection_id}/test-cases",
                    json={
                        "title": "登录成功",
                        "module": "登录",
                        "steps": [{"action": "提交有效凭据", "expected": "显示首页"}],
                    },
                )
            ).json()
            workspace_responses = await asyncio.gather(*[
                client.put(f"/api/v1/collections/{collection_id}/workspace") for _ in range(4)
            ])
            assert len({response.json()["id"] for response in workspace_responses}) == 1
            workspace_response = workspace_responses[0]
            assert workspace_response.status_code == 200
            workspace_id = workspace_response.json()["id"]
            messages_url = f"/api/v1/conversations/{workspace_id}/messages"
            turn = await client.post(
                messages_url,
                json={
                    "content": "检查登录模块遗漏",
                    "intent_override": "COVERAGE_ANALYZE",
                },
            )
            assert turn.status_code == 202, turn.text
            analysis = turn.json()
            operation_id = analysis["operation_plan"]["operations"][0]["id"]
            blocked = await client.post(messages_url, json={"content": "查询用例"})
            assert blocked.status_code == 409
            assert blocked.json()["detail"] == "conversation_task_running"
            report = {
                "summary": "缺少锁定账户场景",
                "findings": [
                    {
                        "title": "锁定账户拒绝登录",
                        "severity": "high",
                        "case_refs": [case["id"]],
                        "evidence": "账户锁定规则",
                        "recommendation": "补充锁定账户场景",
                        "basis": "requirement",
                        "requirement_refs": ["账户规则"],
                    }
                ],
                "limitations": [],
            }
            with store.connection() as connection:
                job_id = UUID(analysis["action"]["job_id"])
                job = store.get_job(connection, job_id)
                store.update_job(
                    connection,
                    job_id,
                    status="completed",
                    stage="completed",
                    output_payload={"analysis_report": report},
                )
                store.complete_job_message(
                    connection,
                    job,
                    content="发现一个覆盖缺口",
                    metadata_values={"analysis_report": report},
                )
            decision = await client.patch(
                f"/api/v1/conversation-operations/{operation_id}/review",
                json={"selected": [0], "ignored": [], "keep_by_finding": {}},
            )
            assert decision.status_code == 200, decision.text
            assert (
                decision.json()["result"]["scope_versions"][case["id"]]
                == case["current_revision_id"]
            )
            turn = await client.post(
                messages_url,
                json={
                    "content": "补充锁定账户登录用例",
                    "intent_override": "CASE_GENERATE",
                    "source_operation_id": operation_id,
                    "targets": [{"kind": "previous_result", "source_operation_id": operation_id}],
                },
            )
            assert turn.status_code == 202, turn.text
            generated = turn.json()
            generation_operation_id = generated["operation_plan"]["operations"][0]["id"]
            preview_draft = {
                "id": "C-LOCKED", "title": "锁定账户无法登录", "module": "登录", "priority": "P1",
                "case_type": "功能", "preconditions": ["账户已锁定"],
                "steps": [{"action": "提交凭据", "expected": "拒绝登录并显示锁定提示"}],
            }
            with store.connection() as connection:
                job_id = UUID(generated["action"]["job_id"])
                job = store.get_job(connection, job_id)
                store.persist_workspace_previews(connection, job, [preview_draft])
                store.persist_workspace_previews(connection, job, [preview_draft])
            preview = (await client.get(f"/api/v1/conversations/{workspace_id}")).json()
            assert preview["candidates"] == []
            assert len(preview["candidate_history"]) == 1
            preview_id = preview["candidate_history"][0]["id"]
            assert preview["candidate_history"][0]["status"] == "generating"
            blocked = await client.post(f"/api/v1/workspaces/{workspace_id}/candidates/commit", json={})
            assert blocked.status_code == 409
            with store.connection() as connection:
                candidate_ids = store.persist_workspace_candidates(
                    connection,
                    job,
                    [
                        {
                            "id": "C-LOCKED",
                            "title": "锁定账户无法登录",
                            "module": "登录",
                            "priority": "P1",
                            "case_type": "功能",
                            "preconditions": ["账户已锁定"],
                            "steps": [{"action": "提交凭据", "expected": "拒绝登录并显示锁定提示"}],
                        }
                    ],
                )
                store.update_job(
                    connection,
                    job_id,
                    status="completed",
                    stage="completed",
                    output_payload={"workspace_candidate_ids": candidate_ids},
                )
                store.complete_job_message(connection, job, content="已生成一条候选用例")
            result = (await client.get(f"/api/v1/conversations/{workspace_id}")).json()
            assert result["candidates"][0]["id"] == preview_id
            assert len(result["candidate_history"]) == 1
            assert len(result["operation_history"]) == 2
            assert result["operation_history"][1]["status"] == "awaiting_confirmation"
            assert result["operation_history"][1]["payload"]["source_operation_id"] == operation_id
            committed = await client.post(
                f"/api/v1/workspaces/{workspace_id}/candidates/commit", json={}
            )
            assert committed.status_code == 200, committed.text
            result = (await client.get(f"/api/v1/conversations/{workspace_id}")).json()
            assert result["operation_history"][1]["status"] == "completed"
            assert result["operation_history"][0]["result"]["review_decisions"]["selected"] == [0]
            assert result["candidate_history"][0]["status"] == "incorporated"
            assert result["messages"][-1]["metadata"]["operation_id"] == generation_operation_id
            empty_module = await client.post(
                messages_url,
                json={
                    "content": "只创建退款模块，不生成用例",
                    "intent_override": "CASE_GENERATE",
                },
            )
            assert empty_module.status_code == 202, empty_module.text
            assert empty_module.json()["action"]["type"] == "module_created"
            collection = (await client.get(f"/api/v1/collections/{collection_id}")).json()
            assert any(
                note.get("kind") == "module" and note["module"] == "退款"
                for note in collection["mind_map_notes"]
            )
            clarification_turn = (
                await client.post(
                    messages_url,
                    json={
                        "content": "修改不存在模块的用例",
                        "intent_override": "CASE_MODIFY",
                    },
                )
            ).json()
            clarification_id = clarification_turn["operation_plan"]["operations"][0]["id"]
            clarification = "仅将标题改为「澄清后更新的标题」，其他字段保持不变。"
            resumed = await client.post(
                f"/api/v1/conversation-operations/{clarification_id}/resume",
                json={"content": clarification, "target_case_ids": [case["id"]]},
            )
            assert resumed.status_code == 202, resumed.text
            assert resumed.json()["assistant_message"]["metadata"].get("modification_confirmation"), resumed.text
            resumed = await client.post(
                f"/api/v1/conversation-operations/{clarification_id}/resume",
                json={"confirm_modification": True},
            )
            assert resumed.status_code == 202, resumed.text
            from casepilot_api.models import GenerationJob

            with get_session_factory()() as db:
                job = db.get(GenerationJob, UUID(resumed.json()["action"]["job_id"]))
                assert clarification in job.input_payload["instruction"]
            state = (await client.get(f"/api/v1/conversations/{workspace_id}")).json()
            assert any(
                m["role"] == "user" and m["content"] == clarification for m in state["messages"]
            )
    finally:
        with get_session_factory()() as db:
            if space_id:
                db.execute(delete(Space).where(Space.id == UUID(space_id)))
            if account_id:
                db.execute(delete(Account).where(Account.id == UUID(account_id)))
            db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("modification", [False, True])
async def test_end_running_task_cancels_group_and_unlocks_conversation(monkeypatch, modification):
    from casepilot_api import generation

    monkeypatch.setattr(conversations.settings, "agent_provider", "mock")
    monkeypatch.setattr(conversations, "enqueue_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(generation.task_client.control, "revoke", lambda *args, **kwargs: None)
    space_id = account_id = None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            registered = (
                await client.post(
                    "/api/v1/auth/register",
                    json={
                        "email": f"cancel-{uuid4().hex}@casepilot.test",
                        "display_name": "Cancel test",
                        "password": "CasePilot123!",
                    },
                )
            ).json()
            account_id = registered["id"]
            space_id = registered["spaces"][0]["id"]
            collection = (await client.get(f"/api/v1/spaces/{space_id}/collections")).json()[0]
            await client.post(
                f"/api/v1/collections/{collection['id']}/test-cases",
                json={
                    "title": "登录",
                    "module": "登录",
                    "steps": [{"action": "登录", "expected": "成功"}],
                },
            )
            workspace = (
                await client.put(f"/api/v1/collections/{collection['id']}/workspace")
            ).json()
            url = f"/api/v1/conversations/{workspace['id']}"
            response = await client.post(
                f"{url}/messages",
                json={
                    "content": "将登录模块的用例标题改为「新登录标题」" if modification else "检查登录模块遗漏；检查登录模块冗余",
                },
            )
            assert response.status_code == 202, response.text
            turn = response.json()
            if modification:
                preview_id = turn["operation_plan"]["operations"][0]["id"]
                confirmed = await client.post(f"/api/v1/conversation-operations/{preview_id}/resume", json={"confirm_modification": True})
                assert confirmed.status_code == 202, confirmed.text
                turn = confirmed.json()
            job_id = turn["action"]["job_id"]
            assert (
                await client.post(f"{url}/messages", json={"content": "你好"})
            ).status_code == 409
            cancelled = await client.post(f"/api/v1/generation-jobs/{job_id}/cancel")
            assert cancelled.status_code == 200, cancelled.text
            state = (await client.get(url)).json()
            assert len(state["operation_history"]) == (1 if modification else 2)
            if modification:
                assert state["context"]["active_mutation_task_id"] is None
                assert state["context"]["active_mutation_operation_id"] is None
                assert state["operation_history"][0]["result"]["task_closed"] is True
            assert all(item["status"] == "cancelled" for item in state["operation_history"])
            message = next(
                m for m in state["messages"] if m["id"] == turn["assistant_message"]["id"]
            )
            assert (
                message["metadata"]["operation_id"] == turn["operation_plan"]["operations"][0]["id"]
            )
            assert message["status"] == "cancelled"
            assert state["context"]["active_job_id"] is None
            assert (
                await client.post(f"{url}/messages", json={"content": "你好"})
            ).status_code == 202
            assert (
                await client.post(f"/api/v1/generation-jobs/{job_id}/cancel")
            ).status_code == 200
    finally:
        with get_session_factory()() as db:
            if space_id:
                db.execute(delete(Space).where(Space.id == UUID(space_id)))
            if account_id:
                db.execute(delete(Account).where(Account.id == UUID(account_id)))
            db.commit()


@pytest.mark.asyncio
async def test_stale_ui_autosave_and_worker_context_merge_preserve_latest_task(monkeypatch):
    from types import SimpleNamespace

    from casepilot_agent.store import JobStore
    from sqlalchemy import update

    from casepilot_api.models import Conversation
    from casepilot_api.schemas import WorkspaceStateUpdate

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        registration = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"context-race-{uuid4().hex}@casepilot.test",
                "display_name": "Context race test",
                "password": "CasePilot123!",
            },
        )
        assert registration.status_code == 201
        account = registration.json()
        space_id = UUID(account["spaces"][0]["id"])
        account_id = UUID(account["id"])
        try:
            collections = (await client.get(f"/api/v1/spaces/{space_id}/collections")).json()
            workspace = (
                await client.put(f"/api/v1/collections/{collections[0]['id']}/workspace")
            ).json()
            conversation_id = UUID(workspace["id"])
            session_factory = get_session_factory()
            latest = str(uuid4())
            with session_factory() as stale:
                loaded = stale.get(Conversation, conversation_id)
                # Hold the old ORM snapshot, then commit a newer task elsewhere.
                original = dict(loaded.context)
                with session_factory() as writer:
                    writer.execute(
                        update(Conversation)
                        .where(Conversation.id == conversation_id)
                        .values(context={**original, "active_mutation_operation_id": latest})
                    )
                    writer.commit()
                assert loaded.context == original
                monkeypatch.setattr(conversations, "_conversation_view", lambda db, row: row)
                conversations.update_workspace_state(
                    conversation_id,
                    WorkspaceStateUpdate(draft_text="draft after new task"),
                    SimpleNamespace(id=account_id),
                    stale,
                )
                assert loaded.context["active_mutation_operation_id"] == latest
                assert loaded.context["draft_text"] == "draft after new task"
            store = JobStore(conversations.settings.database_url, conversations.settings.redis_url)
            with store.connection() as connection:
                store.update_workspace_context(
                    connection, conversation_id, phase="candidate_review"
                )
            with session_factory() as db:
                context = db.get(Conversation, conversation_id).context
                assert context["active_mutation_operation_id"] == latest
                assert context["draft_text"] == "draft after new task"
                assert context["phase"] == "candidate_review"
        finally:
            with get_session_factory()() as db:
                db.execute(delete(Space).where(Space.id == space_id))
                db.execute(delete(Account).where(Account.id == account_id))
                db.commit()
