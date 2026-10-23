"""Deletion reviews must treat candidate and formal members as one explicit scope."""
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import Account, Space, WorkspaceCandidate, Conversation, ConversationMessage, ConversationOperation


@pytest.mark.asyncio
async def test_mixed_deletion_partial_apply_refresh_and_duplicate_apply():
    account_id = space_id = None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            r = await client.post('/api/v1/auth/register', json={
                'email': f'delete-{uuid4().hex}@casepilot.test',
                'display_name': 'Deletion acceptance', 'password': 'CasePilot123!',
            })
            assert r.status_code == 201, r.text
            account_id = UUID(r.json()['id'])
            space_id = UUID(r.json()['spaces'][0]['id'])
            collection = (await client.get(f'/api/v1/spaces/{space_id}/collections')).json()[0]
            case = (await client.post(f"/api/v1/collections/{collection['id']}/test-cases", json={
                'title': '保留至确认的正式用例', 'module': '登录',
                'steps': [{'action': '提交凭据', 'expected': '成功'}],
            })).json()
            workspace = (await client.put(f"/api/v1/collections/{collection['id']}/workspace")).json()
            cid = workspace['id']
            with get_session_factory()() as db:
                candidate = WorkspaceCandidate(conversation_id=UUID(cid), ref='C-DELETE',
                    snapshot={'title': '待丢弃候选', 'module': '登录', 'priority': 'P1',
                              'steps': [{'action': '提交凭据', 'expected': '成功'}]},
                    created_by=account_id)
                db.add(candidate)
                message = ConversationMessage(conversation_id=UUID(cid), role="user", content="生成登录候选")
                db.add(message)
                db.flush()
                task = ConversationOperation(conversation_id=UUID(cid), message_id=message.id,
                    sequence=0, intent="CASE_GENERATE", status="completed", payload={})
                db.add(task)
                db.flush()
                task.payload = {"task_id": str(task.id), "task_intent": "CASE_GENERATE"}
                conv = db.get(Conversation, UUID(cid))
                conv.context = {**conv.context, "phase": "candidate_review",
                    "active_mutation_task_id": str(task.id), "active_mutation_operation_id": str(task.id)}
                db.commit()
            r = await client.post(f'/api/v1/conversations/{cid}/messages', json={
                'content': '删除当前选中的正式用例和候选', 'intent_override': 'CASE_DELETE',
                'targets': [{'kind': 'case', 'case_ids': [case['id']], 'candidate_refs': ['C-DELETE']}],
            })
            assert r.status_code == 202, r.text
            change_id = r.json()['action']['change_set_id']
            change = (await client.get(f'/api/v1/case-change-sets/{change_id}')).json()
            assert {item['target_type'] for item in change['items']} == {'formal', 'candidate'}
            request = {'review_refs': ['C-DELETE'], 'accepted_fields': {'C-DELETE': ['delete']}}
            r = await client.post(f'/api/v1/case-change-sets/{change_id}/apply', json=request)
            assert r.status_code == 200, r.text
            assert r.json()['change_set']['status'] == 'ready'
            state = (await client.get(f'/api/v1/conversations/{cid}')).json()
            assert state['candidates'] == []
            assert state['context']['active_mutation_task_id'] is None
            assert state['context']['phase'] == 'maintenance'
            assert len((await client.get(f"/api/v1/collections/{collection['id']}/test-cases")).json()) == 1
            repeated = await client.post(f'/api/v1/case-change-sets/{change_id}/apply', json=request)
            assert repeated.status_code == 200
            r = await client.post(f'/api/v1/case-change-sets/{change_id}/apply', json={
                'review_refs': [case['id']], 'accepted_fields': {case['id']: ['delete']},
            })
            assert r.status_code == 200, r.text
            assert r.json()['change_set']['status'] == 'applied'
            assert (await client.get(f"/api/v1/collections/{collection['id']}/test-cases")).json() == []
            with get_session_factory()() as db:
                saved = db.get(WorkspaceCandidate, candidate.id)
                assert saved.status == 'discarded' and saved.version == 2
    finally:
        if account_id and space_id:
            with get_session_factory()() as db:
                db.execute(delete(Space).where(Space.id == space_id))
                db.execute(delete(Account).where(Account.id == account_id))
                db.commit()
