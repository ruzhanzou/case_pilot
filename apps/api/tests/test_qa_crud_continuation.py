"""Original continuous oracle, real DB/API/workers, scripted model responses only."""

import json
import re
from types import SimpleNamespace
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from test_workbench_bridge_integration import Provider, setup
from test_workbench_collection_durable_harness import isolated_outbox_db  # noqa: F401
from workbench_agent_live_crud import BAD_MARKER, GOOD_MARKER
from workbench_agent_live_journey import JourneyFailure
from workbench_crud_continuation import CrudDispatch, DurableCrudJourney, UploadBatch

from casepilot_api import conversations, knowledge, workbench_tools
from casepilot_api.config import get_settings
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import KnowledgeDocument, KnowledgeSource, TaskOutbox

pytestmark = pytest.mark.usefixtures("isolated_outbox_db")


def outputs(messages):
    return [json.loads(x["output"]) for x in messages if x.get("type") == "function_call_output"]


def observation(messages):
    return json.loads(
        next(
            x["content"].split("\n", 1)[1]
            for x in messages
            if x.get("role") == "developer"
            and "authorized_workspace_observation" in x.get("content", "")
        )
    )


def choose(predicate):
    def args(messages):
        rows = next(x["cases"] for x in reversed(outputs(messages)) if "cases" in x)
        version = next(
            (x["selection"]["version"] for x in reversed(outputs(messages)) if "selection" in x),
            observation(messages)["selection_version"],
        )
        return {
            "base_version": version,
            "action": "replace",
            "sources": [
                {"ref": x["ref"], "version": x["version"]} for x in rows if predicate(x["snapshot"])
            ],
        }

    return args


class ScriptProvider(Provider):
    def complete(self, *args):
        value = super().complete(*args)
        if value.final and value.final.effect == "read":
            value.final.kind = "answer"
        return value


def scripted(content):
    def query(action, name, args):
        return [("plan_work", {"steps": ["Read"], "plan_actions": [action]}), (name, args)]

    if content.startswith("查询当前空间"):
        calls = query("COLLECTION_QUERY", "query_collections", {})
    elif content.startswith("创建一个新用例集合"):
        name = re.search(r"名称严格为 (.*?)。", content).group(1)
        calls = [("create_collection", {"name": name})]
    elif content.startswith("将当前工作集合切换"):
        name = re.search(r"切换到 (.*?)，", content).group(1)

        def select_collection(messages):
            row = next(
                x["collections"][0] for x in reversed(outputs(messages)) if x.get("collections")
            )
            return {
                "collection_id": row["id"],
                "base_version": observation(messages)["selection_version"],
                "selection_policy": "clear",
            }

        calls = [("query_collections", {"search": name}), ("select_collection", select_collection)]
    elif content.startswith("请先读取附件"):
        calls = [("read_attachment_evidence", {})]
    elif content.startswith("现在按刚才附件"):
        calls = [("prepare_generation", {})]
    elif content.startswith("只把当前集合"):
        name = re.search(r"重命名为 (.*?)。", content).group(1)
        calls = [
            (
                "rename_collection",
                lambda m: {"collection_id": observation(m)["collection_id"], "name": name},
            )
        ]
    elif content.startswith("仅查询当前集合标题"):
        calls = query("CASE_QUERY", "query_assets", {"search": "SYNTHETIC-CRUD-NO-MATCH-NEVER"})
    elif content.startswith("只把当前选中的"):
        calls = [("prepare_rewrite", {})]
    elif content.startswith("请软删除刚才选中"):
        calls = [("prepare_delete", {})]
    else:
        if content.startswith("选择当前集合里的全部非P0"):

            def predicate(s):
                return s["priority"] != "P0"
        elif content.startswith("暂不应用删除预览"):

            def predicate(s):
                return GOOD_MARKER in s["title"]
        else:
            assert content.startswith(("只选择刚才新生成", "重新只选择刚才改写过"))

            def predicate(s):
                return BAD_MARKER in s["title"]

        calls = [("query_assets", {"search": ""}), ("select_assets", choose(predicate))]
    return ScriptProvider(calls)


@pytest.mark.asyncio
async def test_original_nine_check_continuous_mock_protocol(monkeypatch, tmp_path):
    from casepilot_agent import tasks
    from casepilot_agent.contracts import TestCaseBatch
    from casepilot_agent.pipeline import _explicit_rewrite_candidate
    from casepilot_agent.providers.mock import MockProvider

    monkeypatch.setattr(get_settings(), "workbench_agent_enabled", True)
    monkeypatch.setattr(get_settings(), "agent_provider", "openai_compatible")
    monkeypatch.setattr(get_settings(), "agent_api_key", "")
    monkeypatch.setattr(get_settings(), "knowledge_storage_path", str(tmp_path))
    monkeypatch.setattr(knowledge.settings, "knowledge_storage_path", str(tmp_path))
    monkeypatch.setattr(tasks.settings, "knowledge_storage_path", str(tmp_path))
    monkeypatch.setattr(tasks.settings, "provider", "mock")
    monkeypatch.setattr(tasks.settings, "embedding_provider", "mock")

    def scope(content, catalog, context, **kwargs):
        return SimpleNamespace(
            ids=context["selected_ids"],
            reference="selection",
            requested_count=1,
            referenced_case_keys=[],
            ambiguous=False,
            clarification=None,
        )

    monkeypatch.setattr(conversations, "select_case_scope", scope)
    original_message = DurableCrudJourney.message

    async def message(self, cid, content, **kwargs):
        provider = scripted(content)
        monkeypatch.setattr(workbench_tools, "make_provider", lambda *a: provider)
        return await original_message(self, cid, content, **kwargs)

    monkeypatch.setattr(DurableCrudJourney, "message", message)
    original_generate = MockProvider.generate

    def generate(self, request):
        result = original_generate(self, request)
        for index, point in enumerate(result.test_points[:2]):
            point.title = [GOOD_MARKER, BAD_MARKER][index]
            point.priority = ["P2", "P1"][index]
        return result

    monkeypatch.setattr(MockProvider, "generate", generate)
    original_complete = MockProvider.complete

    def complete(self, **kwargs):
        result, usage = original_complete(self, **kwargs)
        if kwargs["result_type"] is TestCaseBatch:
            for case in result.test_cases:
                case.priority = "P1" if BAD_MARKER in case.title else "P2"
        return result, usage

    monkeypatch.setattr(MockProvider, "complete", complete)
    monkeypatch.setattr(
        MockProvider,
        "rewrite",
        lambda self, req: _explicit_rewrite_candidate(
            req.model_copy(update={"instruction": "把选中用例优先级改为P2"})
        ),
    )
    report = {"checks": [], "workspace_ids": []}
    dispatch = CrudDispatch()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        journey = DurableCrudJourney(client, dispatch, tasks, report, "auto")
        dispatch.journey = journey
        try:
            await journey.run({"crud_continuous"})
        except Exception:
            from sqlalchemy import select

            from casepilot_api.models import WorkbenchContinuation, WorkbenchRun

            allowed = {
                "workbench_legacy_scope_requires_reselection",
                "workbench_authority_changed",
                "workbench_approval_completion_invalid",
                "workbench_selection_changed",
                "workbench_binding_changed",
                "workbench_source_changed",
                "workbench_scope_changed",
            }
            with get_session_factory()() as db:
                run = db.get(WorkbenchRun, journey.current_request.run_id)
                request = run.checkpoint.get("original_request", {})
                report["offline_scope_shape"] = {
                    "target_count": len(request.get("targets", [])),
                    "asset_count": len(request.get("target_case_ids", [])),
                    "candidate_count": len(request.get("target_candidate_snapshots", [])),
                    "binding_sources_count": len(run.binding.get("sources", [])),
                    "target_kinds": [v.get("kind") for v in request.get("targets", [])],
                }
                report["offline_continuation_errors"] = [
                    {
                        "kind": event.event_kind,
                        "status": event.status,
                        "error_code": event.receipt.get("error_code")
                        if event.receipt.get("error_code") in allowed
                        else "unrecognized",
                    }
                    for event in db.scalars(
                        select(WorkbenchContinuation).where(
                            WorkbenchContinuation.run_id == journey.current_request.run_id
                        )
                    )
                ]
            print(json.dumps(report, ensure_ascii=False, default=str))
            raise
    assert len(report["checks"]) == 9 and all(x["passed"] for x in report["checks"])
    assert report["source_owned_index_tasks"] == 1
    assert report["crud_human_boundaries"][-1]["status"] == "completed"
    assert all(x["pending_events"] == 0 for x in report["crud_human_boundaries"])


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["foreign", "old_batch", "version", "task", "foreign_pending"])
async def test_upload_batch_refuses_wrong_ownership_version_or_delivery(monkeypatch, tmp_path, bad):
    monkeypatch.setattr(knowledge.settings, "knowledge_storage_path", str(tmp_path))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, workspace = await setup(client)
        cid = workspace["id"]
        result = await client.post(
            f"/api/v1/conversations/{cid}/attachments",
            files={"files": ("synthetic.txt", b"Synthetic requirements", "text/plain")},
        )
        assert result.status_code == 202
        uploaded = result.json()
        if bad == "old_batch":
            with pytest.raises(JourneyFailure):
                UploadBatch(cid, uploaded, {UUID(uploaded["source"]["id"])})
            return
        batch = UploadBatch(cid, uploaded, set())
        with get_session_factory()() as db:
            source = db.get(KnowledgeSource, batch.source_id)
            if bad == "foreign":
                source.account_id = None
            elif bad == "version":
                doc = db.get(KnowledgeDocument, next(iter(batch.versions)))
                doc.version += 1
            elif bad == "task":
                db.get(TaskOutbox, batch.outbox_id).task_args = []
            else:
                from uuid import uuid4

                db.add(
                    TaskOutbox(
                        task_name="casepilot.workbench.continue",
                        task_id=str(uuid4()),
                        task_args=[],
                        status="pending",
                    )
                )
            db.commit()
        with pytest.raises(JourneyFailure):
            batch.before_dispatch()
        with get_session_factory()() as db:
            assert db.get(TaskOutbox, batch.outbox_id).status == "pending"
