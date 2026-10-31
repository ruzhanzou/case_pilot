"""Real parsed-sheet/selection guards with deterministic model calls."""

import json
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from test_workbench_bridge_integration import activate, setup
from test_workbench_uploaded_bridge import observed_sources, seed_sheet

from casepilot_api.main import app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "select,action,expected",
    [
        (False, "CASE_MODIFY", "uploaded_preview_requires_selection"),
        (True, "CASE_DELETE", "workbench_plan_step_mismatch"),
        (True, "CASE_MODIFY", None),
    ],
)
async def test_uploaded_prepare_guard_matrix(monkeypatch, tmp_path, select, action, expected):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, collection, conversation = await setup(client)
        cid = conversation["id"]
        doc = seed_sheet(tmp_path, account, conversation)
        calls = [
            ("query_uploaded_cases", {}),
            (
                "preview_uploaded_cases",
                lambda m: {"sources": observed_sources(m, "query_uploaded_cases")},
            ),
        ]
        if select:
            calls.append(
                (
                    "select_assets",
                    lambda m: {
                        "base_version": 0,
                        "sources": observed_sources(m, "preview_uploaded_cases"),
                    },
                )
            )
        calls.append(("prepare_rewrite", {}))
        provider = activate(
            monkeypatch,
            calls,
            fixture_plan={"steps": ["Explicit synthetic goal"], "plan_actions": [action]},
        )
        response = await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={
                "content": "改写历史用例，先给预览，不批准",
                "document_ids": [doc],
                "client_request_id": str(uuid4()),
            },
        )
        assert response.status_code == 202
        outputs = [
            json.loads(x["output"])
            for x in provider.observations[-1]
            if x.get("type") == "function_call_output"
        ]
        if expected:
            assert any(x.get("error_code") == expected for x in outputs)
            assert not response.json()["action"].get("job_id")
            events = response.json()["assistant_message"]["metadata"]["workbench_agent"]["events"]
            diagnostic = next(
                e["diagnostic"]
                for e in events
                if e["type"] == "tool_rejected" and e.get("tool") == "prepare_rewrite"
            )
            assert diagnostic["rejection_code"] == expected
            assert diagnostic["plan_action"] == action
            assert diagnostic["plan_cursor"] == 0
            assert diagnostic["canonical_present"] is select
            if select:
                assert diagnostic["canonical_count"] == 1 and diagnostic["canonical_version"] == 1
        else:
            assert response.json()["action"].get("job_id")
        assert (await client.get(f"/api/v1/collections/{collection['id']}/test-cases")).json() == []
