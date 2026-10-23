"""An asset review may continue an existing case modification, without generating a collection."""

from uuid import UUID, uuid4
import pytest
from httpx import ASGITransport, AsyncClient
from casepilot_api import conversations
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import Conversation, ConversationOperation, GenerationJob, WorkspaceTestBrief, KnowledgeSource, KnowledgeDocument


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit_targets", [True, False])
@pytest.mark.parametrize("source_kind", ["formal", "excel"])
async def test_asset_confirmation_hands_off_to_reviewed_modification(monkeypatch, explicit_targets, source_kind):
    monkeypatch.setattr(conversations.settings, "agent_provider", "mock")
    monkeypatch.setattr(conversations, "enqueue_task", lambda *a, **k: None)
    scope_intents = []
    resolve_scope = conversations._resolve_action_scope

    def capture_scope(db, conversation, payload, intent, *args, **kwargs):
        scope_intents.append(intent)
        return resolve_scope(db, conversation, payload, intent, *args, **kwargs)

    monkeypatch.setattr(conversations, "_resolve_action_scope", capture_scope)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:

        async def post(route, payload):
            response = await client.post("/api/v1" + route, json=payload)
            assert response.status_code in {200, 201, 202}, response.text
            return response.json()

        user = await post(
            "/auth/register",
            {
                "email": f"handoff-{uuid4().hex}@casepilot.test",
                "password": "CasePilot123!",
                "display_name": "Handoff",
            },
        )
        space = user["spaces"][0]["id"]
        collections = [
            await post(f"/spaces/{space}/collections", {"name": name})
            for name in ["Source", "Target"]
        ]
        cases = [
            await post(
                f"/collections/{collection['id']}/test-cases",
                {
                    "title": "Account login",
                    "module": "Account system",
                    "priority": "P1",
                    "case_type": "functional",
                    "preconditions": ["Enabled account"],
                    "steps": [{"action": "Login", "expected": "Session created"}],
                },
            )
            for collection in collections
        ]
        workspace = await post(
            "/conversations", {"collection_id": collections[1]["id"], "title": "Reference rewrite"}
        )
        sibling = await post(f"/collections/{collections[1]['id']}/test-cases", {
            "title": "Account logout", "module": "Account system", "priority": "P1",
            "case_type": "functional", "preconditions": ["Logged in"],
            "steps": [{"action": "Logout", "expected": "Session closed"}],
        })
        cid = UUID(workspace["id"])
        turn = await post(
            f"/conversations/{cid}/messages",
            {
                "content": f"测试对象：Account system。查找已有资产，参考改写用例 {cases[1]['case_key']} 的步骤，预期保持不变。",
                **({"target_case_ids": [cases[1]["id"]],
                    "source_collection_ids": [collections[0]["id"]]} if explicit_targets else {}),
            },
        )
        job_id = UUID(turn["action"]["job_id"])
        assert scope_intents[0] == "CASE_MODIFY"
        source = {
            "key": f"asset:{cases[0]['id']}",
            "case_id": cases[0]["id"],
            "kind": "formal",
            "snapshot": cases[0],
            "revision": cases[0]["current_revision_id"],
            "test_object_match": "same",
            "collections": [collections[0]],
        }
        if source_kind == "excel":
            source_id, document_id = uuid4(), uuid4()
            with get_session_factory()() as db:
                job = db.get(GenerationJob, job_id)
                db.add(KnowledgeSource(id=source_id, space_id=UUID(space), account_id=job.account_id,
                    name="old.xlsx", persistence="temporary", status="ready"))
                db.flush()
                db.add(KnowledgeDocument(id=document_id, source_id=source_id, space_id=UUID(space),
                    original_name="old.xlsx", mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    storage_key=str(document_id), size_bytes=100, checksum="a" * 64, version=1, status="ready"))
                db.commit()
            source = {**source, "kind": "excel", "key": f"excel:{document_id}:Sheet1:2",
                "case_id": f"excel:{document_id}:Sheet1:2", "document_id": str(document_id),
                "document_version": 1, "document_checksum": "a" * 64, "collections": []}
        selection = {
            "status": "awaiting_confirmation",
            "strategy": "select_and_generate",
            "job_id": str(job_id),
            "test_object": "Account system",
            "sources": [source],
            "target_points": [],
            "followup_intent": "CASE_MODIFY",
        }
        with get_session_factory()() as db:
            job = db.get(GenerationJob, job_id)
            assert job.input_payload["asset_followup_intent"] == "CASE_MODIFY"
            assert job.input_payload["asset_target_request"]["target_case_ids"] == [cases[1]["id"]]
            job.status = "completed"
            job.stage = "completed"
            content = {
                "test_object": "Account system",
                "asset_selection": selection,
                "planning": {},
            }
            job.output_payload = {"test_brief": content}
            operation_id = UUID(turn["operation_plan"]["operations"][0]["id"])
            db.add(
                WorkspaceTestBrief(
                    conversation_id=cid,
                    source_operation_id=operation_id,
                    version=1,
                    status="draft",
                    content=content,
                )
            )
            conversation = db.get(Conversation, cid)
            conversation.context = {
                **conversation.context,
                "phase": "brief_review",
                "active_job_id": None,
            }
            db.commit()
        confirmed = await post(
            f"/workspaces/{cid}/generation-assets/confirm",
            {"version": 1, "case_ids": [source["case_id"]]},
        )
        assert confirmed["intent"] == "CASE_MODIFY"
        assert not confirmed["action"].get("job_id")
        assert confirmed["assistant_message"]["metadata"]["modification_confirmation"]
        assert confirmed["assistant_message"]["target_case_ids"] == [cases[1]["id"]]
        with get_session_factory()() as db:
            assert db.get(ConversationOperation, operation_id).payload["task_intent"] == "CASE_MODIFY"
        before = (await client.get(f"/api/v1/collections/{collections[1]['id']}/test-cases")).json()
        assert {item["id"]: item for item in before} == {item["id"]: item for item in [cases[1], sibling]}
        resumed = await post(
            f"/conversation-operations/{operation_id}/resume", {"confirm_modification": True}
        )
        with get_session_factory()() as db:
            job = db.get(GenerationJob, UUID(resumed["action"]["job_id"]))
            assert job.operation == "conversation_modify"
            assert job.input_payload["asset_reference_sources"] == [source]
            assert [target["case_id"] for target in job.input_payload["formal_targets"]] == [
                cases[1]["id"]
            ]


@pytest.mark.asyncio
async def test_explicit_asset_request_cancels_running_job_before_starting_followup(monkeypatch):
    from casepilot_api import generation
    monkeypatch.setattr(conversations.settings, 'agent_provider', 'mock')
    monkeypatch.setattr(conversations, 'enqueue_task', lambda *a, **k: None)
    monkeypatch.setattr(generation.task_client.control, 'revoke', lambda *a, **k: None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        async def post(route, data):
            r = await client.post('/api/v1'+route, json=data)
            assert r.status_code in {200, 201, 202}, r.text
            return r.json()
        user = await post('/auth/register', {'email': f'redirect-{uuid4().hex}@casepilot.test',
            'password': 'CasePilot123!', 'display_name': 'Redirect'})
        space = user['spaces'][0]['id']
        collection = await post(f'/spaces/{space}/collections', {'name': '账号系统'})
        workspace = await post('/conversations', {'collection_id': collection['id'], 'title': '运行中调整'})
        cid = workspace['id']
        first = await post(f'/conversations/{cid}/messages', {'content': '测试对象：账号系统。全新生成登录成功用例，不复用历史。'})
        old_id = UUID(first['action']['job_id'])
        with get_session_factory()() as db:
            old = db.get(GenerationJob, old_id)
            old.status = 'running'
            old.stage = 'requirement.analyzed'
            db.commit()
        followup = await post(f'/conversations/{cid}/messages', {'content': '测试对象：账号系统。查找已有用例参考，其他要求保持。'})
        new_id = UUID(followup['action']['job_id'])
        assert old_id != new_id
        with get_session_factory()() as db:
            assert db.get(GenerationJob, old_id).status == 'cancelled'
            new = db.get(GenerationJob, new_id)
            assert new.input_payload['generation_strategy'] == 'select_and_generate'
            assert new.input_payload['predecessor_job_id'] == str(old_id)
            assert db.get(Conversation, UUID(cid)).context['active_job_id'] == str(new_id)


@pytest.mark.asyncio
async def test_new_module_guard_does_not_inherit_asset_rewrite_mode(monkeypatch):
    monkeypatch.setattr(conversations.settings, "agent_provider", "mock")
    monkeypatch.setattr(conversations, "enqueue_task", lambda *a, **k: None)
    scope_intents = []
    resolve_scope = conversations._resolve_action_scope

    def capture_scope(db, conversation, payload, intent, *args, **kwargs):
        scope_intents.append(intent)
        return resolve_scope(db, conversation, payload, intent, *args, **kwargs)

    monkeypatch.setattr(conversations, "_resolve_action_scope", capture_scope)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async def post(route, data):
            response = await client.post("/api/v1" + route, json=data)
            assert response.status_code in {200, 201, 202}, response.text
            return response.json()

        user = await post("/auth/register", {
            "email": f"new-module-{uuid4().hex}@casepilot.test",
            "password": "CasePilot123!", "display_name": "New module",
        })
        space = user["spaces"][0]["id"]
        collection = await post(f"/spaces/{space}/collections", {"name": "Existing suite"})
        await post(f"/collections/{collection['id']}/test-cases", {
            "title": "Existing login", "module": "Login", "priority": "P1",
            "case_type": "functional", "preconditions": [],
            "steps": [{"action": "Login", "expected": "Success"}],
        })
        workspace = await post("/conversations", {
            "collection_id": collection["id"], "title": "Add invoice module",
        })
        turn = await post(f"/conversations/{workspace['id']}/messages", {
            "content": (
                "新增「发票管理」模块，并生成恰好10条新的候选用例。"
                "现有用例和其他模块不得改写或删除，先生成候选供我审阅。"
            ),
            # Simulate stale UI state from an earlier asset-reuse turn.
            "generation_strategy": "select_and_generate",
        })
        assert scope_intents == ["CASE_GENERATE"]
        assert turn["assistant_message"]["status"] != "awaiting_clarification"
        with get_session_factory()() as db:
            job = db.get(GenerationJob, UUID(turn["action"]["job_id"]))
            assert job.input_payload["generation_strategy"] == "generate"
            assert job.input_payload["target_module_path"] == "发票管理"
            assert job.input_payload["target_module_exact"] is True
