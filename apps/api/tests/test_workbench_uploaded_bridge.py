"""Uploaded history is observed, previewed and rewritten privately before adoption."""

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from test_workbench_bridge_integration import activate, setup

from casepilot_api.database import get_session_factory
from casepilot_api.main import app


def seed_sheet(tmp_path, account, conversation):
    from casepilot_agent.knowledge import parse_document
    from openpyxl import Workbook

    from casepilot_api.models import (
        Conversation,
        KnowledgeChunk,
        KnowledgeDocument,
        KnowledgeSource,
    )

    book = Workbook()
    sheet = book.active
    sheet.title = "History"
    sheet.append(["用例编号", "用例标题", "模块", "优先级", "操作步骤", "预期结果"])
    sheet.append(["OLD-1", "历史登录", "登录", "P2", "输入验证码", "登录成功"])
    path = tmp_path / "history.xlsx"
    book.save(path)
    blocks = parse_document(path, "")
    with get_session_factory()() as db:
        source = KnowledgeSource(
            space_id=UUID(conversation["space_id"]),
            account_id=UUID(account["id"]),
            name="History",
            kind="upload",
            persistence="temporary",
            status="ready",
        )
        db.add(source)
        db.flush()
        document = KnowledgeDocument(
            source_id=source.id,
            space_id=source.space_id,
            original_name=path.name,
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            storage_key=str(uuid4()),
            size_bytes=path.stat().st_size,
            checksum="a" * 64,
            status="ready",
            version=1,
        )
        db.add(document)
        db.flush()
        for index, block in enumerate(blocks):
            db.add(
                KnowledgeChunk(
                    document_id=document.id,
                    source_id=source.id,
                    space_id=source.space_id,
                    chunk_type="child",
                    ordinal=index,
                    section_path=block.section_path,
                    locator=block.locator,
                    content=block.content,
                    contextual_content=block.content,
                    search_text=block.content,
                    token_count=1,
                    chunk_metadata=block.metadata,
                )
            )
        # Match the attachment endpoint's persisted upload association while using
        # real XLSX parsing rather than a background indexing service in this fixture.
        conv = db.get(Conversation, UUID(conversation["id"]))
        conv.context = {
            **dict(conv.context),
            "document_ids": [str(document.id)],
            "knowledge_source_ids": [str(source.id)],
        }
        db.commit()
        return str(document.id)


def observed_sources(messages, tool_name):
    for item in reversed(messages):
        if item.get("type") != "function_call_output":
            continue
        result = json.loads(item["output"])
        if (result.get("_receipt") or {}).get("tool") == tool_name:
            return [{"ref": row["ref"], "version": row["version"]} for row in result["cases"]]
    raise AssertionError(f"Missing observation {tool_name}")


@pytest.mark.asyncio
async def test_uploaded_preview_select_rewrite_apply_adopt_clears_canonical(monkeypatch, tmp_path):
    from casepilot_agent import tasks

    monkeypatch.setattr(tasks.settings, "provider", "mock")
    monkeypatch.setattr(tasks.settings, "embedding_provider", "mock")
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
            (
                "preview_uploaded_cases",
                lambda m: {"sources": observed_sources(m, "query_uploaded_cases")},
            ),
            ("prepare_rewrite", {}),  # Must not bypass missing canonical selection.
            (
                "select_assets",
                lambda m: {
                    "base_version": 0,
                    "sources": observed_sources(m, "preview_uploaded_cases"),
                },
            ),
            ("prepare_rewrite", {}),
        ]
        initial_provider = activate(monkeypatch, calls)
        turn = await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={
                "content": "把选中用例优先级改为P1",
                "document_ids": [doc],
                "client_request_id": str(uuid4()),
            },
        )
        assert turn.status_code == 202, turn.text
        body = turn.json()
        outputs = [
            json.loads(item["output"])
            for item in initial_provider.observations[-1]
            if item.get("type") == "function_call_output"
        ]
        assert any(
            item.get("error_code") == "uploaded_preview_requires_selection" for item in outputs
        )
        assert body["action"].get("job_id"), body
        workspace = (await client.get(f"/api/v1/conversations/{cid}")).json()
        assert len(workspace["candidates"]) == 1
        original = workspace["candidates"][0]
        assert not original["included"]
        assert original["snapshot"]["source_provenance"]["document_id"] == doc
        assert (await client.get(f"/api/v1/collections/{collection['id']}/test-cases")).json() == []
        op = body["operation_plan"]["operations"][0]["id"]
        await asyncio.to_thread(
            tasks.rewrite_test_cases_batch.run, body["action"]["job_id"]
        )
        workspace = (await client.get(f"/api/v1/conversations/{cid}")).json()
        operation = next(item for item in workspace["operation_history"] if item["id"] == op)
        change_id = operation["related_change_set_id"]
        applied = await client.post(f"/api/v1/case-change-sets/{change_id}/apply", json={})
        assert applied.status_code == 200, applied.text
        workspace = (await client.get(f"/api/v1/conversations/{cid}")).json()
        rewritten = next(item for item in workspace["candidates"] if item["ref"] == original["ref"])
        assert rewritten["snapshot"]["priority"] == "P1"
        assert rewritten["snapshot"]["steps"] == original["snapshot"]["steps"]
        assert (
            rewritten["snapshot"]["source_provenance"] == original["snapshot"]["source_provenance"]
        )
        assert rewritten["version"] > original["version"]
        included = await client.patch(
            f"/api/v1/workspace-candidates/{rewritten['id']}",
            json={
                "included": True,
                "base_version": rewritten["version"],
            },
        )
        assert included.status_code == 200, included.text
        old_selection_version = workspace["context"]["workbench_selection"]["version"]
        stale = await client.post(
            f"/api/v1/workspaces/{cid}/candidates/commit",
            json={
                "candidate_ids": [rewritten["id"]],
                "candidate_versions": {rewritten["id"]: original["version"]},
            },
        )
        assert stale.status_code == 409
        assert (await client.get(f"/api/v1/collections/{collection['id']}/test-cases")).json() == []
        adopted = await client.post(
            f"/api/v1/workspaces/{cid}/candidates/commit",
            json={
                "candidate_ids": [rewritten["id"]],
                "candidate_versions": {rewritten["id"]: rewritten["version"]},
            },
        )
        assert adopted.status_code == 200, adopted.text
        assert len(adopted.json()) == 1
        workspace = (await client.get(f"/api/v1/conversations/{cid}")).json()
        assert workspace["context"]["workbench_selection"]["items"] == []
        assert workspace["context"]["workbench_selection"]["version"] > old_selection_version
        provider = activate(monkeypatch, [("query_uploaded_cases", {})])
        inherited = await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={
                "content": "查看之前上传的历史表格",
                "client_request_id": str(uuid4()),
            },
        )
        assert inherited.status_code == 202, inherited.text
        assert len(observed_sources(provider.observations[-1], "query_uploaded_cases")) == 1


@pytest.mark.asyncio
async def test_uploaded_preview_revalidates_observation_versions_and_ownership(
    monkeypatch, tmp_path
):
    from fastapi import HTTPException
    from sqlalchemy import func, select

    from casepilot_api.models import Account, Conversation, KnowledgeDocument, WorkspaceCandidate
    from casepilot_api.schemas import ConversationMessageCreate
    from casepilot_api.workbench_tools import (
        UploadedPreviewArguments,
        UploadedQueryArguments,
        WorkbenchTools,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, _, conversation = await setup(client)
        doc = seed_sheet(tmp_path, account, conversation)
        with get_session_factory()() as db:
            conv = db.get(Conversation, UUID(conversation["id"]))
            owner = db.get(Account, UUID(account["id"]))
            bridge = WorkbenchTools(
                db,
                owner,
                conv,
                ConversationMessageCreate(
                    content="Read history",
                    document_ids=[UUID(doc)],
                ),
            )
            unknown = UploadedPreviewArguments(
                sources=[
                    {
                        "ref": f"upload:{doc}:unknown:2",
                        "version": "unknown",
                    }
                ]
            )
            assert bridge.preview_uploaded_cases(unknown)["error_code"] == (
                "agent_selection_requires_observed_sources"
            )
            rows = bridge.uploaded_cases(UploadedQueryArguments())["cases"]
            exact = {"ref": rows[0]["ref"], "version": rows[0]["version"]}
            duplicate = UploadedPreviewArguments(sources=[exact, exact])
            assert (
                bridge.preview_uploaded_cases(duplicate)["error_code"]
                == "duplicate_uploaded_source"
            )
            document = db.get(KnowledgeDocument, UUID(doc))
            document.version += 1
            db.flush()
            with pytest.raises(HTTPException) as error:
                bridge.preview_uploaded_cases(UploadedPreviewArguments(sources=[exact]))
            assert error.value.status_code == 409
            assert error.value.detail == "workbench_source_changed"
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(WorkspaceCandidate)
                    .where(
                        WorkspaceCandidate.conversation_id == conv.id,
                    )
                )
                == 0
            )
            # Even a previously observed row is no authority after private ownership changes.
            document.version -= 1
            from casepilot_api.models import KnowledgeSource

            source = db.get(KnowledgeSource, document.source_id)
            other = Account(
                email=f"other-{uuid4().hex}@test", display_name="Other", password_hash="x"
            )
            db.add(other)
            db.flush()
            source.account_id = other.id
            db.flush()
            with pytest.raises(HTTPException) as error:
                bridge.preview_uploaded_cases(UploadedPreviewArguments(sources=[exact]))
            assert error.value.status_code == 409
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(WorkspaceCandidate)
                    .where(
                        WorkspaceCandidate.conversation_id == conv.id,
                    )
                )
                == 0
            )
            db.rollback()


@pytest.mark.asyncio
async def test_explicit_observed_mixed_selection_rewrites_only_asset_and_uploaded_draft(
    monkeypatch,
    tmp_path,
):
    from casepilot_agent import tasks

    monkeypatch.setattr(tasks.settings, "provider", "mock")
    monkeypatch.setattr(tasks.settings, "embedding_provider", "mock")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, collection, conversation = await setup(client)
        cid = conversation["id"]
        seed_sheet(tmp_path, account, conversation)
        assets = []
        for title in ("Selected asset", "Unselected protected asset"):
            response = await client.post(
                f"/api/v1/collections/{collection['id']}/test-cases",
                json={
                    "title": title,
                    "priority": "P2",
                    "steps": [
                        {"action": "Login", "expected": "Success"},
                    ],
                },
            )
            assert response.status_code == 201, response.text
            assets.append(response.json())
        selected, protected = assets

        def mixed_sources(messages):
            asset = next(
                row
                for row in observed_sources(messages, "query_assets")
                if row["ref"] == f"asset:{selected['id']}"
            )
            return {
                "base_version": 0,
                "sources": [
                    asset,
                    *observed_sources(messages, "preview_uploaded_cases"),
                ],
            }

        activate(
            monkeypatch,
            [
                ("query_assets", {}),
                ("query_uploaded_cases", {}),
                (
                    "preview_uploaded_cases",
                    lambda m: {
                        "sources": observed_sources(m, "query_uploaded_cases"),
                    },
                ),
                ("select_assets", mixed_sources),
                ("prepare_rewrite", {}),
            ],
        )
        turn = await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={
                "content": "把选中用例优先级改为P1",
                "client_request_id": str(uuid4()),
            },
        )
        assert turn.status_code == 202, turn.text
        body = turn.json()
        assert body["action"].get("job_id"), body
        operation = body["operation_plan"]["operations"][0]
        confirmation = operation["payload"]["prepared_modification"]
        refs = {item["ref"] for item in confirmation["cases"]}
        state = (await client.get(f"/api/v1/conversations/{cid}")).json()
        candidate = state["candidates"][0]
        assert refs == {selected["id"], candidate["ref"]}
        await asyncio.to_thread(
            tasks.rewrite_test_cases_batch.run,
            body["action"]["job_id"],
        )
        state = (await client.get(f"/api/v1/conversations/{cid}")).json()
        saved = next(row for row in state["operation_history"] if row["id"] == operation["id"])
        change_id = saved["related_change_set_id"]
        change = (await client.get(f"/api/v1/case-change-sets/{change_id}")).json()
        assert {item["ref"] for item in change["items"]} == refs
        applied = await client.post(f"/api/v1/case-change-sets/{change_id}/apply", json={})
        assert applied.status_code == 200, applied.text
        current = (await client.get(f"/api/v1/test-cases/{protected['id']}")).json()
        assert current["current_revision_id"] == protected["current_revision_id"]
        assert current["priority"] == "P2"
        current = (await client.get(f"/api/v1/test-cases/{selected['id']}")).json()
        assert current["priority"] == "P1"
        state = (await client.get(f"/api/v1/conversations/{cid}")).json()
        assert state["candidates"][0]["snapshot"]["priority"] == "P1"
