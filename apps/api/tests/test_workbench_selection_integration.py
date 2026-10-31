from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import (
    Account,
    Conversation,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    WorkspaceCandidate,
)
from casepilot_api.models import TestCase as CaseRecord
from casepilot_api.workbench_selection import SelectionUpdate, _resolve_sources, update_selection
from casepilot_api.workbench_sources import WorkbenchSources


@pytest.mark.asyncio
async def test_database_scoped_discovery_exact_selection_and_foreign_rejection(tmp_path):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:

        async def post(path, payload):
            response = await client.post("/api/v1" + path, json=payload)
            assert response.status_code in {200, 201, 202}, response.text
            return response.json()

        user = await post(
            "/auth/register",
            {
                "email": f"selection-{uuid4().hex}@casepilot.test",
                "password": "CasePilot123!",
                "display_name": "Selection",
            },
        )
        space = user["spaces"][0]["id"]
        collections, cases = [], []
        for name in ["A", "B"]:
            collection = await post(f"/spaces/{space}/collections", {"name": name})
            collections.append(collection)
            cases.append(
                await post(
                    f"/collections/{collection['id']}/test-cases",
                    {
                        "title": f"Test {name}",
                        "module": "module",
                        "priority": "P1",
                        "case_type": "functional",
                        "preconditions": [],
                        "steps": [{"action": "Act", "expected": "Pass"}],
                    },
                )
            )
        workspace = await post(
            "/conversations", {"collection_id": collections[0]["id"], "title": "Selection"}
        )
        foreign_user = await post(
            "/auth/register",
            {
                "email": f"foreign-{uuid4().hex}@casepilot.test",
                "password": "CasePilot123!",
                "display_name": "Foreign",
            },
        )
        foreign_collection = await post(
            f"/spaces/{foreign_user['spaces'][0]['id']}/collections", {"name": "Foreign"}
        )
        foreign = await post(
            f"/collections/{foreign_collection['id']}/test-cases",
            {
                "title": "Foreign",
                "module": "module",
                "priority": "P1",
                "case_type": "functional",
                "preconditions": [],
                "steps": [{"action": "Act", "expected": "Pass"}],
            },
        )
        with get_session_factory()() as db:
            conversation = db.get(Conversation, UUID(workspace["id"]))
            account = db.get(Account, conversation.account_id)
            source = WorkbenchSources(db, account, conversation)
            rows = source.query_assets()["cases"]
            assert {r["ref"] for r in rows} == {f"asset:{case['id']}" for case in cases}
            assert len(source.query_assets(scope="current_collection")["cases"]) == 1
            state = update_selection(
                db,
                account,
                conversation,
                SelectionUpdate(
                    base_version=0, sources=[{"ref": rows[0]["ref"], "version": rows[0]["version"]}]
                ),
            )
            db.flush()
            assert state["version"] == 1
            from casepilot_api.workbench_plan import TaskContext

            TaskContext(conversation).remember_sources(rows)
            TaskContext(conversation).plan(["Inspect", "Select"])
            update_selection(
                db,
                account,
                conversation,
                SelectionUpdate(
                    base_version=1, sources=[{"ref": rows[1]["ref"], "version": rows[1]["version"]}]
                ),
                changed_by="agent",
            )
            assert conversation.context["workbench_plan"]["goals"] == ["Inspect", "Select"]
            assert set(conversation.context["workbench_plan"]["source_catalog"]) == {
                row["ref"] for row in rows
            }

            with pytest.raises(HTTPException) as error:
                _resolve_sources(db, account, conversation, [{"ref": f"asset:{foreign['id']}"}])
            assert error.value.status_code == 404
            with pytest.raises(HTTPException) as error:
                _resolve_sources(
                    db, account, conversation, [{"ref": rows[0]["ref"], "version": str(uuid4())}]
                )
            assert error.value.status_code == 409
            for case in cases:
                assert (
                    str(db.get(CaseRecord, UUID(case["id"])).current_revision_id)
                    == case["current_revision_id"]
                )
            # Actual XLSX parser output, existing ingestion metadata, explicit draft-only reuse.
            from casepilot_agent.knowledge import parse_document
            from openpyxl import Workbook
            from sqlalchemy import func, select

            from casepilot_api.schemas import ConversationMessageCreate

            book = Workbook()
            sheet = book.active
            sheet.title = "Historic"
            sheet.append(["用例编号", "用例标题", "前置条件", "操作步骤", "预期结果"])
            sheet.append(["OLD-1", "Historic login", "Account enabled", "Login", "Session created"])
            path = tmp_path / "history.xlsx"
            book.save(path)
            blocks = parse_document(path, "")
            assert any(block.metadata.get("reference_cases") for block in blocks)
            knowledge = KnowledgeSource(
                space_id=conversation.space_id,
                account_id=account.id,
                name="History",
                kind="upload",
                persistence="temporary",
                status="ready",
            )
            db.add(knowledge)
            db.flush()
            document = KnowledgeDocument(
                source_id=knowledge.id,
                space_id=conversation.space_id,
                original_name="history.xlsx",
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
                        source_id=knowledge.id,
                        space_id=conversation.space_id,
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
            db.flush()
            source = WorkbenchSources(
                db,
                account,
                conversation,
                ConversationMessageCreate(
                    content="Rewrite historic login", document_ids=[document.id]
                ),
            )
            before = db.scalar(select(func.count()).select_from(CaseRecord))
            candidates_before = db.scalar(select(func.count()).select_from(WorkspaceCandidate))
            preview = source.uploaded_cases()["cases"]
            assert len(preview) == 1
            assert preview[0]["source_ref"]["sheet"] == "Historic"
            assert preview[0]["source_ref"]["row"] == 2
            assert (
                db.scalar(select(func.count()).select_from(WorkspaceCandidate)) == candidates_before
            )
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(WorkspaceCandidate)
                    .where(WorkspaceCandidate.conversation_id == conversation.id)
                )
                == 0
            )
            target = {"ref": preview[0]["ref"], "version": preview[0]["version"]}
            materialized = source.preview_uploaded_rows([target])
            assert materialized[0]["snapshot"]["source_provenance"]["document_id"] == str(
                document.id
            )
            assert db.scalar(select(func.count()).select_from(CaseRecord)) == before
            candidate_ref = materialized[0]["ref"][10:]
            db.add(
                WorkspaceCandidate(
                    conversation_id=conversation.id,
                    ref=candidate_ref,
                    version=2,
                    snapshot=materialized[0]["snapshot"],
                    status="discarded",
                    included=False,
                    position=0,
                    created_by=account.id,
                )
            )
            db.flush()
            assert source.query_candidates()["cases"] == []
            with pytest.raises(HTTPException) as error:
                _resolve_sources(
                    db, account, conversation, [{"ref": materialized[0]["ref"], "version": "1"}]
                )
            assert error.value.status_code == 409
            document.version += 1
            db.flush()
            with pytest.raises(HTTPException) as error:
                source.resolve_uploaded_rows([target])
            assert error.value.status_code == 409
            db.rollback()
