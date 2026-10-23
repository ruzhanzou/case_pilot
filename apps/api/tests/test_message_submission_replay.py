import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from casepilot_api import conversations
from casepilot_api.main import app


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrent", [False, True])
async def test_message_retry_identity_is_independent_of_text(monkeypatch, concurrent):
    monkeypatch.setattr(conversations, 'enqueue_task', lambda *a, **k: None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        user = (await client.post('/api/v1/auth/register', json={
            'email': f'message-replay-{uuid4().hex}@casepilot.test',
            'display_name': 'Message replay', 'password': 'CasePilot123!',
        })).json()
        collection = (await client.post(f"/api/v1/spaces/{user['spaces'][0]['id']}/collections",
                                       json={'name': 'Submission replay'})).json()
        conversation = (await client.post('/api/v1/conversations',
                                          json={'collection_id': collection['id']})).json()
        url = f"/api/v1/conversations/{conversation['id']}/messages"
        request = {'content': '查询当前集合的所有用例', 'intent_override': 'CASE_QUERY',
                   'client_request_id': str(uuid4())}
        if concurrent:
            first, simultaneous = await asyncio.gather(
                client.post(url, json=request), client.post(url, json=request),
            )
            assert simultaneous.json() == first.json()
        else:
            first = await client.post(url, json=request)
        assert first.status_code == 202, first.text
        replay = await client.post(url, json=request)
        assert replay.status_code == 202, replay.text
        assert replay.json()['user_message']['id'] == first.json()['user_message']['id']
        assert replay.json()['assistant_message']['id'] == first.json()['assistant_message']['id']
        assert (
            replay.json()['user_message']['metadata']['submission_request_id']
            == request['client_request_id']
        )
        changed = await client.post(url, json={**request, 'content': '查询P0用例'})
        assert changed.status_code == 409
        intentional = await client.post(url, json={**request, 'client_request_id': str(uuid4())})
        assert intentional.status_code == 202, intentional.text
        assert intentional.json()['user_message']['id'] != first.json()['user_message']['id']


@pytest.mark.asyncio
async def test_late_submission_failure_rolls_back_job_messages_and_receipt(monkeypatch):
    from uuid import UUID

    from fastapi import HTTPException
    from sqlalchemy import func, select

    from casepilot_api.database import get_session_factory
    from casepilot_api.models import ConversationMessage, ConversationSubmission, GenerationJob

    monkeypatch.setattr(conversations, 'enqueue_task', lambda *a, **k: None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        user = (await client.post('/api/v1/auth/register', json={
            'email': f'message-rollback-{uuid4().hex}@casepilot.test',
            'display_name': 'Rollback test', 'password': 'CasePilot123!',
        })).json()
        collection = (await client.post(f"/api/v1/spaces/{user['spaces'][0]['id']}/collections",
                                       json={'name': 'Rollback'})).json()
        conversation = (await client.post('/api/v1/conversations',
                                          json={'collection_id': collection['id']})).json()
        cid = UUID(conversation['id'])
        url = f'/api/v1/conversations/{cid}/messages'
        request = {'content': '生成1条账号登录测试用例', 'intent_override': 'CASE_GENERATE',
                   'client_request_id': str(uuid4())}
        original = conversations._send_message
        def fail_after_inner_commit(*args):
            original(*args)
            raise HTTPException(503, 'injected failure before receipt')
        monkeypatch.setattr(conversations, '_send_message', fail_after_inner_commit)
        failed = await client.post(url, json=request)
        assert failed.status_code == 503
        with get_session_factory()() as db:
            assert db.scalar(select(func.count()).select_from(ConversationMessage).where(
                ConversationMessage.conversation_id == cid)) == 0
            assert db.scalar(select(func.count()).select_from(ConversationSubmission).where(
                ConversationSubmission.conversation_id == cid)) == 0
            assert db.scalar(select(func.count()).select_from(GenerationJob).where(
                GenerationJob.collection_id == UUID(collection['id']))) == 0
        monkeypatch.setattr(conversations, '_send_message', original)
        retried = await client.post(url, json=request)
        assert retried.status_code == 202, retried.text
        replay = await client.post(url, json=request)
        assert replay.status_code == 202, replay.text
        assert replay.json() == retried.json()
