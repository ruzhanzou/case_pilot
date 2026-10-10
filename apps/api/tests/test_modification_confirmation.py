"""Persisted pre-execution gate; no worker or model is dispatched."""

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from casepilot_api import conversations
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import ConversationOperation, GenerationJob


@pytest.mark.asyncio
@pytest.mark.parametrize("target_scope", ["inferred", "selected"])
@pytest.mark.parametrize("confirmation", [
    {"confirm_modification": True}, {"content": "确认"},
    {"content": "确认", "echo_targets": True},
    {"content": "确认", "echo_case_ids": True},
])
async def test_confirmation_rejects_bypass_and_refreshes_changed_assets(monkeypatch, confirmation, target_scope):
    dispatched = []
    monkeypatch.setattr(
        conversations, "enqueue_task", lambda *args, **kwargs: dispatched.append(args)
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        registration = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"confirmation-{uuid4().hex}@casepilot.test",
                "display_name": "Confirmation test",
                "password": "CasePilot123!",
            },
        )
        assert registration.status_code == 201
        space = registration.json()["spaces"][0]["id"]
        collection = (await client.get(f"/api/v1/spaces/{space}/collections")).json()[0]["id"]
        case = (
            await client.post(
                f"/api/v1/collections/{collection}/test-cases",
                json={
                    "title": "登录成功",
                    "module": "登录",
                    "steps": [{"action": "登录", "expected": "成功"}],
                },
            )
        ).json()
        workspace = (await client.put(f"/api/v1/collections/{collection}/workspace")).json()["id"]
        turn = await client.post(
            f"/api/v1/conversations/{workspace}/messages",
            json={
                "content": "把当前用例优先级改为P0",
                "intent_override": "CASE_MODIFY",
                "target_case_ids": [case["id"]],
                "target_scope": target_scope,
                "targets": [{"kind": "case", "case_ids": [case["id"]]}],
            },
        )
        assert turn.status_code == 202, turn.text
        body = turn.json()
        assert body["assistant_message"]["metadata"]["modification_confirmation"]
        assert not body["action"].get("job_id")
        assert not dispatched
        operation_id = body["operation_plan"]["operations"][0]["id"]
        resume = f"/api/v1/conversation-operations/{operation_id}/resume"
        bypass = await client.post(resume, json={})
        assert bypass.status_code == 202, bypass.text
        assert not bypass.json()["action"].get("job_id")
        assert not dispatched
        invalid = await client.post(
            resume, json={"confirm_modification": True, "content": "改为P2"}
        )
        assert invalid.status_code == 422
        unclear = await client.post(
            resume, json={"content": "修改「不存在的确认模块」模块，标题改为新标题"}
        )
        assert unclear.status_code == 202, unclear.text
        assert not unclear.json()["action"].get("job_id")
        expired = await client.post(resume, json={"confirm_modification": True})
        assert expired.status_code == 422
        corrected = await client.post(
            resume, json={"content": "优先级改为P0", "target_case_ids": [case["id"]]}
        )
        assert corrected.status_code == 202, corrected.text
        assert corrected.json()["assistant_message"]["metadata"]["modification_confirmation"]
        assert not dispatched
        changed = await client.patch(
            f"/api/v1/test-cases/{case['id']}",
            json={
                **case,
                "base_revision_id": case["current_revision_id"],
                "title": "人工修改后的标题",
            },
        )
        assert changed.status_code == 200, changed.text
        stale = await client.post(resume, json={"confirm_modification": True})
        assert stale.status_code == 202, stale.text
        assert stale.json()["assistant_message"]["metadata"]["modification_confirmation"]
        assert "人工修改后的标题" in stale.json()["assistant_message"]["content"]
        assert not dispatched
        confirmation = dict(confirmation)
        if confirmation.pop("echo_targets", False):
            # Scope resolution had no selectors, but the browser echoes IDs.
            confirmation["targets"] = [{"kind": "case", "case_ids": [case["id"]]}]
        if confirmation.pop("echo_case_ids", False):
            confirmation["target_case_ids"] = [case["id"]]
        confirmed = await client.post(resume, json=confirmation)
        assert confirmed.status_code == 202, confirmed.text
        assert confirmed.json()["action"]["job_id"]
        assert len(dispatched) == 1
        duplicate = await client.post(resume, json={"confirm_modification": True})
        assert duplicate.status_code == 409


def test_confirmation_compares_assets_instead_of_selector_representation():
    from types import SimpleNamespace
    from casepilot_api.schemas import ConversationOperationResumeRequest

    ids = [uuid4(), uuid4()]
    operation = SimpleNamespace(target={"selectors": []}, payload={
        "modification_confirmation": {"cases": [
            {"ref": str(item), "target_type": "formal"} for item in ids
        ] + [{"ref": "candidate-one", "target_type": "candidate"}]},
    })
    same = ConversationOperationResumeRequest(
        content="确认", targets=[
            {"kind": "case", "case_ids": list(reversed(ids)), "candidate_refs": ["candidate-one"]},
        ],
    )
    assert conversations._same_confirmation_targets(operation, same)
    changed = same.model_copy(update={"targets": []})
    assert conversations._same_confirmation_targets(operation, changed)
    for targets in [
        [{"kind": "case", "case_ids": ids[:1], "candidate_refs": ["candidate-one"]}],
        [{"kind": "case", "case_ids": [*ids, uuid4()], "candidate_refs": ["candidate-one"]}],
        [{"kind": "case", "case_ids": ids}],
    ]:
        assert not conversations._same_confirmation_targets(
            operation, ConversationOperationResumeRequest(content="确认", targets=targets),
        )


def test_recover_polluted_instruction_preserves_actual_supplements():
    assert conversations._without_confirmation_supplements(
        "改写多端模块用例\n补充说明：确认\n补充说明：步骤更清晰\n补充说明：确认！"
    ) == "改写多端模块用例\n补充说明：步骤更清晰"


@pytest.mark.asyncio
async def test_changed_selection_is_previewed_and_old_confirmation_pollution_is_recovered(monkeypatch):
    dispatched = []
    monkeypatch.setattr(conversations, "enqueue_task", lambda *args, **kwargs: dispatched.append(args))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        registration = await client.post("/api/v1/auth/register", json={
            "email": f"confirmation-scope-{uuid4().hex}@casepilot.test",
            "display_name": "Confirmation scope", "password": "CasePilot123!",
        })
        space = registration.json()["spaces"][0]["id"]
        collection = (await client.get(f"/api/v1/spaces/{space}/collections")).json()[0]["id"]
        cases = []
        for title in ["登录成功", "取消登录"]:
            response = await client.post(f"/api/v1/collections/{collection}/test-cases", json={
                "title": title, "module": "登录",
                "steps": [{"action": "操作", "expected": "符合要求"}],
            })
            assert response.status_code == 201, response.text
            cases.append(response.json())
        workspace = (await client.put(f"/api/v1/collections/{collection}/workspace")).json()["id"]
        instruction = "把当前用例优先级改为P0"
        turn = await client.post(f"/api/v1/conversations/{workspace}/messages", json={
            "content": instruction, "intent_override": "CASE_MODIFY",
            "target_case_ids": [cases[0]["id"]],
        })
        assert turn.status_code == 202, turn.text
        oid = turn.json()["operation_plan"]["operations"][0]["id"]
        resume = f"/api/v1/conversation-operations/{oid}/resume"
        selection = [{"kind": "case", "case_ids": [cases[1]["id"]]}]
        changed = await client.post(resume, json={"content": "确认", "targets": selection})
        assert changed.status_code == 202, changed.text
        assert not changed.json()["action"].get("job_id")
        assert changed.json()["assistant_message"]["metadata"]["modification_confirmation"]
        assert "取消登录" in changed.json()["assistant_message"]["content"]
        assert "补充说明：确认" not in changed.json()["assistant_message"]["content"]
        assert not dispatched
        # Model-resolved scopes used to pollute this persisted gate on each echo.
        with get_session_factory()() as db:
            operation = db.get(ConversationOperation, UUID(oid))
            payload = dict(operation.payload)
            pending = dict(payload["modification_confirmation"])
            polluted = instruction + "\n补充说明：确认\n补充说明：确认"
            pending["instruction"] = polluted
            operation.payload = {**payload, "instruction": polluted,
                                 "modification_confirmation": pending}
            db.commit()
        confirmed = await client.post(resume, json={"content": "确认", "targets": selection})
        assert confirmed.status_code == 202, confirmed.text
        job_id = confirmed.json()["action"]["job_id"]
        assert len(dispatched) == 1
        with get_session_factory()() as db:
            job = db.get(GenerationJob, UUID(job_id))
            assert job.input_payload["prompt"] == instruction
            assert [item["ref"] for item in job.input_payload["case_context"]] == [cases[1]["id"]]
