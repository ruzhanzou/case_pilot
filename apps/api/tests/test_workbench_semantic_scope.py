"""Real bridge/domain regression: canonical selection must not bypass NL scope."""

import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from test_workbench_bridge_integration import activate, setup

from casepilot_api import conversations
from casepilot_api.agent_router import CaseScopeDecision
from casepilot_api.main import app
from casepilot_api.workbench_agent import FinalAnswer, ModelTurn


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("instruction", "matches"),
    [
        ("仅修改选中用例中的P1用例，把标题改为已更新", True),
        ("除保护用例外，修改选中用例，把标题改为已更新", True),
        ("仅修改选中用例中的P2用例，把标题改为已更新", False),
        ("修改选中用例的标题为已更新，不要修改保护用例", True),
        ("不要修改任何选中用例，保持所有用例不变", False),
    ],
)
async def test_chat_rewrite_narrows_scope_and_preserves_others(monkeypatch, instruction, matches):
    from casepilot_agent import tasks

    monkeypatch.setattr(tasks.settings, "provider", "mock")
    monkeypatch.setattr(tasks.settings, "embedding_provider", "mock")
    provider = activate(monkeypatch, [("prepare_rewrite", {})])
    if not matches:
        first_call = provider.complete

        def clarify_after_tool(messages, tools, instructions):
            if provider.observations:
                return ModelTurn(
                    final=FinalAnswer(kind="clarify", message="没有匹配用例，请重新选择。")
                )
            return first_call(messages, tools, instructions)

        provider.complete = clarify_after_tool
    monkeypatch.setattr(conversations.settings, "agent_provider", "openai_compatible")
    observations = []
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, collection, conversation = await setup(client)
        cases = []
        for title, priority in [("保护用例", "P0"), ("可修改用例", "P1"), ("未选中用例", "P1")]:
            response = await client.post(
                f"/api/v1/collections/{collection['id']}/test-cases",
                json={
                    "title": title,
                    "priority": priority,
                    "steps": [{"action": "Run", "expected": "Pass"}],
                },
            )
            assert response.status_code == 201, response.text
            cases.append(response.json())
        protected, target, outside = cases
        cid = conversation["id"]
        selected = await client.patch(
            f"/api/v1/workspaces/{cid}/selection",
            json={
                "base_version": 0,
                "sources": [
                    {"ref": f"asset:{case['id']}", "version": case["current_revision_id"]}
                    for case in cases[:2]
                ],
            },
        )
        assert selected.status_code == 200, selected.text

        def select_scope(content, catalog, context, **kwargs):
            observations.append((content, catalog, context))
            return CaseScopeDecision(
                ids=[target["id"]] if matches else [],
                ambiguous=False,
                clarification="",
                reference="selection",
                referenced_case_keys=[],
                requested_count=None,
            )

        monkeypatch.setattr(conversations, "select_case_scope", select_scope)
        response = await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={
                "content": instruction,
                "selection_version": 1,
                "client_request_id": str(uuid4()),
            },
        )
        assert response.status_code == 202, response.text
        body = response.json()
        expected = [target["id"]] if matches else []
        operation = body["operation_plan"]["operations"][0]
        # Assert the persisted proposal, not just the injected selector invocation.
        if matches:
            assert operation["target"]["case_ids"] == expected, body
        assert bool(body["action"].get("job_id")) == bool(matches), body
        if matches:
            confirmation = operation["payload"]["prepared_modification"]
            assert [item["ref"] for item in confirmation["cases"]] == expected
        else:
            assert not body["assistant_message"]["metadata"].get("modification_confirmation")
            assert not operation["target"].get("resolved"), operation
        assert observations and observations[0][0] == instruction
        assert {str(row["id"]) for row in observations[0][1]} == {protected["id"], target["id"]}
        for case in cases:
            current = (await client.get(f"/api/v1/test-cases/{case['id']}")).json()
            assert current["current_revision_id"] == case["current_revision_id"]
            assert current["title"] == case["title"]
        if matches:
            await asyncio.to_thread(
                tasks.rewrite_test_cases_batch.run, body["action"]["job_id"]
            )
            state = (await client.get(f"/api/v1/conversations/{cid}")).json()
            saved = next(row for row in state["operation_history"] if row["id"] == operation["id"])
            change_id = saved["related_change_set_id"]
            change = (await client.get(f"/api/v1/case-change-sets/{change_id}")).json()
            assert [item["ref"] for item in change["items"]] == expected, change
            applied = await client.post(f"/api/v1/case-change-sets/{change_id}/apply", json={})
            assert applied.status_code == 200, applied.text
            changed = (await client.get(f"/api/v1/test-cases/{target['id']}")).json()
            assert changed["current_revision_id"] != target["current_revision_id"]
            for case in [protected, outside]:
                current = (await client.get(f"/api/v1/test-cases/{case['id']}")).json()
                assert current["current_revision_id"] == case["current_revision_id"]
                assert current["title"] == case["title"]
                assert current["priority"] == case["priority"]
