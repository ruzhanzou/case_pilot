"""Generation explanations survive refresh without altering stored messages."""
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import Account, ConversationMessage, GenerationJob, Space


@pytest.mark.asyncio
async def test_conversation_projects_generation_notes_without_changing_saved_metadata():
    account_id = space_id = None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            registration = await client.post("/api/v1/auth/register", json={
                "email": f"quality-{uuid4().hex}@casepilot.test",
                "display_name": "Quality projection", "password": "CasePilot123!",
            })
            assert registration.status_code == 201
            account_id = UUID(registration.json()["id"])
            space_id = UUID(registration.json()["spaces"][0]["id"])
            created = await client.post("/api/v1/conversations", json={"space_id": str(space_id)})
            assert created.status_code == 201, created.text
            cid = UUID(created.json()["id"])
            notes = [{"code": "independent_scenarios_below_target", "severity": "warning",
                      "message": "请求50条，已确认独立场景仅24条；未循环测试点凑数。"}]
            with get_session_factory()() as db:
                job = GenerationJob(space_id=space_id, account_id=account_id,
                    operation="generate", status="completed", stage="completed",
                    input_payload={"conversation_id": str(cid)},
                    output_payload={"quality": {"passed": True, "issues": notes}})
                db.add(job)
                db.flush()
                message = ConversationMessage(conversation_id=cid, role="assistant",
                    content="已生成24条", intent="CASE_GENERATE", status="completed",
                    related_job_id=job.id, message_metadata={"candidate_count": 24},
                    target_case_ids=[], citations=[])
                db.add(message)
                db.commit()
                mid = message.id
            for _ in range(2):
                response = await client.get(f"/api/v1/conversations/{cid}")
                assert response.status_code == 200, response.text
                message_view = next(m for m in response.json()["messages"] if m["id"] == str(mid))
                assert message_view["metadata"]["generation_quality_issues"] == notes
                assert message_view["metadata"]["candidate_count"] == 24
            with get_session_factory()() as db:
                assert db.get(ConversationMessage, mid).message_metadata == {"candidate_count": 24}
    finally:
        if space_id and account_id:
            with get_session_factory()() as db:
                db.execute(delete(Space).where(Space.id == space_id))
                db.execute(delete(Account).where(Account.id == account_id))
                db.commit()
