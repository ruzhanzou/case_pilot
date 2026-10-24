"""Persist real API/worker rounds with controlled model responses and isolated accounts."""

from uuid import UUID, uuid4

import pytest
from casepilot_agent import tasks
from casepilot_agent.contracts import UsageMetadata
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from casepilot_api import conversations
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import Account, Space


@pytest.fixture
async def workspace(monkeypatch):
    monkeypatch.setattr(conversations, "enqueue_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(conversations.settings, "agent_provider", "mock")
    monkeypatch.setattr(tasks, "_prepare_rewrite_requests", lambda store, job, pipeline, r: r)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"multiround-{uuid4().hex}@casepilot.test",
                "display_name": "Multi round acceptance",
                "password": "CasePilot123!",
            },
        )
        account = response.json()
        space = account["spaces"][0]["id"]
        collection = (await client.get(f"/api/v1/spaces/{space}/collections")).json()[0]["id"]
        wid = (await client.put(f"/api/v1/collections/{collection}/workspace")).json()["id"]
        try:
            yield client, collection, wid
        finally:
            with get_session_factory()() as db:
                db.execute(delete(Space).where(Space.id == UUID(space)))
                db.execute(delete(Account).where(Account.id == UUID(account["id"])))
                db.commit()


class RewriteProvider:
    name = "openai_compatible"
    changes = {}

    def complete(self, *, payload, result_type, **kwargs):
        if kwargs.get("stage") == "rewrite.constraints_validated":
            from casepilot_agent.contracts import QualityIssue, QualityReport, RewriteCaseDraft, RewriteRequest
            from casepilot_agent.rewrite_guards import preservation_error, reference_rewrite_error
            request = RewriteRequest(test_case=payload["original"], instruction=payload["instruction"], context=payload.get("context", {}))
            proposed = RewriteCaseDraft.model_validate(payload["proposed"])
            error = preservation_error(request, proposed) or reference_rewrite_error(request, proposed)
            return QualityReport(passed=not error, score=0 if error else 100,
                issues=[QualityIssue(code="fixture_constraint", message=error)] if error else []), UsageMetadata(model="acceptance")
        return result_type.model_validate(
            {
                "items": [
                    {"ref": item["ref"], "changes": self.changes, "reason": "验收修改"}
                    for item in payload["items"]
                ]
            }
        ), UsageMetadata(model="acceptance")


@pytest.mark.asyncio
async def test_module_then_single_then_failed_round_and_rewrite_after_apply(
    workspace, monkeypatch
):
    client, collection, wid = workspace
    provider = RewriteProvider()
    monkeypatch.setattr(tasks, "create_provider", lambda *args: provider)
    cases = []
    for name, module in [("登录A", "登录"), ("登录B", "登录"), ("其他", "其他")]:
        response = await client.post(
            f"/api/v1/collections/{collection}/test-cases",
            json={
                "title": name,
                "module": module,
                "preconditions": ["账号存在"],
                "steps": [{"action": f"原步骤{i}", "expected": f"原校验{i}"} for i in range(3)],
            },
        )
        assert response.status_code == 201, response.text
        cases.append(response.json())

    async def rewrite(instruction, targets, changes):
        provider.changes = changes
        turn = await client.post(
            f"/api/v1/conversations/{wid}/messages",
            json={
                "content": instruction,
                "intent_override": "CASE_MODIFY",
                "targets": targets,
                "target_scope": "selected" if targets[0]["kind"] == "case" else "inferred",
            },
        )
        assert turn.status_code == 202, turn.text
        body = turn.json()
        if body["action"].get("job_id"):
            result = tasks.rewrite_test_cases_batch.run(body["action"]["job_id"])
            return (await client.get(f"/api/v1/case-change-sets/{result['change_set_id']}")).json()
        operation = body["operation_plan"]["current_operation_id"]
        confirmed = await client.post(
            f"/api/v1/conversation-operations/{operation}/resume",
            json={"confirm_modification": True},
        )
        assert confirmed.status_code == 202, (
            confirmed.text + str(body["assistant_message"]) + str(body["operation_plan"])
        )
        job = confirmed.json()["action"].get("job_id")
        assert job, confirmed.text
        result = tasks.rewrite_test_cases_batch.run(job)
        assert "error" not in result, result
        saved = await client.get(f"/api/v1/case-change-sets/{result['change_set_id']}")
        assert saved.status_code == 200, saved.text
        return saved.json()

    failed_initial = await rewrite(
        "把其他模块当前用例改为单步注销验证，其他内容不变",
        [{"kind": "case", "case_ids": [cases[2]["id"]]}],
        {"steps": [{"action": "注销", "expected": "会话失效"}]},
    )
    assert failed_initial["status"] == "no_changes"
    assert failed_initial["items"][0]["quality"]["passed"] is False
    assert failed_initial["items"][0]["field_diff"] == []
    blocked = await client.post(
        f"/api/v1/case-change-sets/{failed_initial['id']}/apply", json={}
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"] == "change_item_needs_completion"
    rejected = await client.post(
        f"/api/v1/case-change-sets/{failed_initial['id']}/reject"
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    unchanged = (await client.get(f"/api/v1/test-cases/{cases[2]['id']}")).json()
    assert len(unchanged["steps"]) == 3

    first = await rewrite(
        "给登录模块用例补充断网重试验证，其他内容不变",
        [{"kind": "module", "module": "登录"}],
        {"append_steps": [{"action": "断网重试", "expected": "恢复会话"}]},
    )
    assert {item["ref"] for item in first["items"]} == {c["id"] for c in cases[:2]}
    assert all(len(i["proposed_snapshot"]["steps"]) == 4 for i in first["items"])
    second = await rewrite(
        "修改当前用例操作步骤，第2步改为输入验证码，预期结果保持不变",
        [{"kind": "case", "case_ids": [cases[0]["id"]]}],
        {"step_updates": [{"step_index": 1, "action": "输入验证码"}]},
    )
    assert len(second["items"]) == 2
    second_items = {i["ref"]: i for i in second["items"]}
    assert second_items[cases[0]["id"]]["proposed_snapshot"]["steps"][1]["action"] == "输入验证码"
    assert second_items[cases[1]["id"]]["proposed_snapshot"] == next(
        i["proposed_snapshot"] for i in first["items"] if i["ref"] == cases[1]["id"]
    )
    third = await rewrite(
        "给当前用例增加注销验证，其他内容不变",
        [{"kind": "case", "case_ids": [cases[0]["id"]]}],
        {"steps": [{"action": "注销", "expected": "会话失效"}]},
    )
    assert third["status"] == "ready"
    third_items = {i["ref"]: i for i in third["items"]}
    assert third_items[cases[0]["id"]]["quality"]["passed"] is False
    assert third_items[cases[0]["id"]]["field_diff"] == second_items[cases[0]["id"]]["field_diff"]
    assert (
        third_items[cases[0]["id"]]["proposed_snapshot"]
        == second_items[cases[0]["id"]]["proposed_snapshot"]
    )
    applied = await client.post(f"/api/v1/case-change-sets/{third['id']}/apply", json={})
    assert applied.status_code == 409, applied.text
    assert applied.json()["detail"] == "change_item_needs_completion"
    for case in cases:
        current = (await client.get(f"/api/v1/test-cases/{case['id']}")).json()
        assert len(current["steps"]) == 3
        assert [s["expected"] for s in current["steps"][:3]] == [f"原校验{i}" for i in range(3)]
    fourth = await rewrite(
        "给当前用例增加注销验证，其他内容不变",
        [{"kind": "case", "case_ids": [cases[0]["id"]]}],
        {"append_steps": [{"action": "注销", "expected": "会话失效"}]},
    )
    assert len(fourth["items"]) == 2
    fourth_items = {item["ref"]: item for item in fourth["items"]}
    assert len(fourth_items[cases[0]["id"]]["proposed_snapshot"]["steps"]) == 5
    assert fourth_items[cases[0]["id"]]["proposed_snapshot"]["steps"][1]["action"] == "输入验证码"
    assert fourth_items[cases[1]["id"]]["proposed_snapshot"] == second_items[cases[1]["id"]]["proposed_snapshot"]
    applied = await client.post(f"/api/v1/case-change-sets/{fourth['id']}/apply", json={})
    assert applied.status_code == 200, applied.text
    current = (await client.get(f"/api/v1/test-cases/{cases[0]['id']}")).json()
    assert len(current["steps"]) == 5


@pytest.mark.asyncio
async def test_planning_add_edit_delete_rounds_persist_history_and_select_latest(
    workspace, monkeypatch
):
    from casepilot_agent.contracts import FeaturePoint
    from casepilot_agent.planning import PlanningAnalysis

    client, _, wid = workspace
    base_points = [
        {
            "id": f"original-{i}",
            "title": f"原测试点{i}",
            "objective": f"原目标{i}",
            "feature_point_ids": ["original-feature"],
        }
        for i in range(18)
    ]
    response = await client.post(
        f"/api/v1/workspaces/{wid}/test-briefs",
        json={
            "content": {
                "test_object": "登录",
                "planning": {
                    "feature_points": [
                        {
                            "id": "original-feature",
                            "name": "登录",
                            "module": "登录",
                            "description": "登录",
                            "requirement_refs": [],
                        }
                    ],
                    "test_points": base_points,
                },
            },
        },
    )
    assert response.status_code == 201, response.text

    class PlanningProvider:
        name = "openai_compatible"
        label = "稳定性"
        removed = []
        deletion_only = False

        def complete(self, *, stage, payload, result_type, **kwargs):
            if stage == "output_quantity.interpreted":
                from casepilot_agent.quantity import OutputQuantity
                return OutputQuantity(test_point_count={"稳定性": 3, "安全": 2, "修订稳定性": 1}.get(self.label)), UsageMetadata(model="acceptance")
            if stage == "requirement.analyzed":
                result = PlanningAnalysis(
                    summary="登录",
                    test_object="登录",
                    test_object_specified=True,
                    superseded_test_point_ids=self.removed,
                    feature_points=[]
                    if self.deletion_only
                    else [
                        FeaturePoint(
                            id="new",
                            name=self.label,
                            module="登录",
                            description=self.label,
                            requirement_refs=[],
                        )
                    ],
                )
            else:
                assert stage == "test_point.generated", stage
                features = payload["feature_points"]["feature_points"]
                result = result_type.model_validate(
                    {
                        "test_points": [
                            {
                                "id": str(i),
                                "title": f"{self.label}{i}",
                                "objective": f"验证{self.label}{i}",
                                "category": "功能",
                                "priority": "P1",
                                "priority_reason": "核心流程",
                                "feature_point_ids": [features[0]["id"]],
                            }
                            for i in range(payload["batch_count"])
                        ],
                        "coverage_matrix": [],
                    }
                )
            return result, UsageMetadata(model="acceptance")

    provider = PlanningProvider()
    monkeypatch.setattr(tasks, "create_provider", lambda *args: provider)
    monkeypatch.setattr(tasks, "create_embedding_provider", lambda: None)
    monkeypatch.setattr(tasks, "_context_payload", lambda *args, **kwargs: {"evidence": []})
    selected = None
    for label, instruction, count in [
        ("稳定性", "登录测试规划增加3个稳定性测试点", 21),
        ("安全", "登录测试规划增加2个安全测试点", 23),
        ("修订稳定性", "登录测试规划修改指定稳定性测试点，仅替换为1个测试点", 23),
        ("删除安全", "登录测试规划删除指定安全测试点，其余不变", 22),
    ]:
        provider.label = label
        provider.removed = []
        if label == "修订稳定性":
            provider.removed = [next(p["id"] for p in selected if p["title"] == "稳定性0")]
        if label == "删除安全":
            provider.removed = [next(p["id"] for p in selected if p["title"] == "安全0")]
            provider.deletion_only = True
        turn = await client.post(
            f"/api/v1/conversations/{wid}/messages",
            json={
                "content": instruction,
                "intent_override": "CASE_GENERATE",
            },
        )
        assert turn.status_code == 202, turn.text
        job = turn.json()["action"].get("job_id")
        assert job, turn.text
        result = tasks.draft_test_brief.run(job)
        assert "error" not in result, result
        refreshed = (await client.get(f"/api/v1/conversations/{wid}")).json()
        latest = refreshed["test_briefs"][-1]
        selected = latest["content"]["planning"]["test_points"]
        assert len(selected) == count
        assert selected[:18] == base_points
        assert refreshed["context"]["selected_brief_version"] == latest["version"]
        assert len(refreshed["test_briefs"]) == latest["version"]


@pytest.mark.asyncio
async def test_candidate_rewrite_rounds_keep_point_links_and_other_candidates(
    workspace, monkeypatch
):
    from casepilot_api.models import Conversation, WorkspaceCandidate

    client, _, wid = workspace
    provider = RewriteProvider()
    monkeypatch.setattr(tasks, "create_provider", lambda *args: provider)
    base = {
        "id": "C-A",
        "title": "候选A",
        "module": "登录",
        "priority": "P1",
        "case_type": "功能",
        "preconditions": ["账号可用"],
        "tags": [],
        "source_refs": [],
        "test_point_ids": ["TP-keep"],
        "steps": [
            {"action": "打开登录页", "expected": "显示登录表单"},
            {"action": "提交有效凭据", "expected": "显示首页"},
        ],
    }
    with get_session_factory()() as db:
        db.add(WorkspaceCandidate(conversation_id=UUID(wid), ref="C-A", snapshot=base))
        db.add(
            WorkspaceCandidate(
                conversation_id=UUID(wid),
                ref="C-B",
                snapshot={**base, "id": "C-B", "title": "候选B"},
                position=1,
            )
        )
        conversation = db.get(Conversation, UUID(wid))
        conversation.context = {**dict(conversation.context), "phase": "candidate_review"}
        db.commit()
    change = None
    for instruction, changes in [
        (
            "补充当前候选用例的重试操作步骤，其他内容不变",
            {"append_steps": [{"action": "重试", "expected": "保持登录"}]},
        ),
        (
            "修改当前候选用例操作步骤，第2步改为输入验证码，预期结果保持不变",
            {"step_updates": [{"step_index": 1, "action": "输入验证码并提交"}]},
        ),
    ]:
        provider.changes = changes
        turn = await client.post(
            f"/api/v1/conversations/{wid}/messages",
            json={
                "content": instruction,
                "intent_override": "CASE_MODIFY",
                "target_scope": "selected",
                "targets": [{"kind": "case", "candidate_refs": ["C-A"]}],
            },
        )
        assert turn.status_code == 202, turn.text
        body = turn.json()
        oid = body["operation_plan"]["current_operation_id"]
        if not body["action"].get("job_id"):
            confirmed = await client.post(
                f"/api/v1/conversation-operations/{oid}/resume", json={"confirm_modification": True}
            )
            assert confirmed.status_code == 202, confirmed.text
            body = confirmed.json()
        result = tasks.rewrite_test_cases_batch.run(body["action"]["job_id"])
        change = (await client.get(f"/api/v1/case-change-sets/{result['change_set_id']}")).json()
        assert len(change["items"]) == 1
        snapshot = change["items"][0]["proposed_snapshot"]
        assert len(snapshot["steps"]) == 3
        assert snapshot["test_point_ids"] == ["TP-keep"]
    applied = await client.post(f"/api/v1/case-change-sets/{change['id']}/apply", json={})
    assert applied.status_code == 200, applied.text
    refreshed = (await client.get(f"/api/v1/conversations/{wid}")).json()
    candidates = {c["ref"]: c for c in refreshed["candidates"]}
    assert candidates["C-A"]["version"] == 2
    assert candidates["C-A"]["snapshot"]["steps"][1]["action"] == "输入验证码并提交"
    assert candidates["C-A"]["snapshot"]["steps"][1]["expected"] == "显示首页"
    assert len(candidates["C-A"]["snapshot"]["steps"]) == 3
    assert candidates["C-B"]["version"] == 1
    assert candidates["C-B"]["snapshot"]["steps"] == base["steps"]


@pytest.mark.asyncio
async def test_text_retry_of_partial_generation_only_reconfirms_missing_points(workspace):
    from casepilot_api.models import (Conversation, ConversationOperation, GenerationJob,
                                     WorkspaceCandidate, WorkspaceTestBrief)
    from casepilot_api.schemas import TestBriefContent
    from sqlalchemy import select

    client, _, wid = workspace
    response = await client.post(f'/api/v1/conversations/{wid}/messages', json={
        'content': '生成2条登录用例', 'intent_override': 'CASE_GENERATE',
    })
    assert response.status_code == 202, response.text
    job_id = UUID(response.json()['action']['job_id'])
    points = [{'id': f'P-{i}', 'title': f'登录场景{i}', 'objective': f'验证登录场景{i}',
               'feature_point_ids': ['F-1']} for i in [1, 2]]
    content = TestBriefContent.model_validate({'test_object': '登录系统', 'planning': {
        'feature_points': [{'id': 'F-1', 'name': '登录', 'module': '账号', 'description': '登录'}],
        'test_points': points,
    }}).model_dump(mode='json')
    snapshot = {'id': 'TC-P-1', 'title': '成功的候选', 'module': '账号', 'priority': 'P1',
                'case_type': '功能', 'preconditions': ['账号存在'], 'steps': [{'action': '登录', 'expected': '进入首页'}],
                'test_point_ids': ['P-1'], 'source_refs': [], 'tags': []}
    with get_session_factory()() as db:
        job = db.get(GenerationJob, job_id)
        op = db.scalar(select(ConversationOperation).where(ConversationOperation.related_job_id == job_id))
        job.operation = 'generate'
        job.status = 'completed'
        job.stage = 'completed'
        job.input_payload = {**job.input_payload, 'confirmed_plan': content['planning'],
                             'confirmed_test_brief_version': 1, 'output_contract': 'case_batch_v2'}
        job.output_payload = {'quality': {'passed': True, 'issues': [
            {'code': 'uncovered_test_point', 'object_id': 'P-2', 'message': '待完善', 'severity': 'warning'}]}}
        op.status = 'completed'
        db.add(WorkspaceTestBrief(conversation_id=UUID(wid), source_operation_id=op.id,
                                  version=1, content=content, status='confirmed'))
        kept = WorkspaceCandidate(conversation_id=UUID(wid), generation_job_id=job.id,
                                  ref='TC-P-1', snapshot=snapshot, version=1, status='candidate')
        db.add(kept)
        conv = db.get(Conversation, UUID(wid))
        conv.context = {**conv.context, 'phase': 'candidate_review', 'active_job_id': None,
                        'confirmed_brief_version': 1}
        db.commit()
        kept_id = kept.id
    retried = await client.post(f'/api/v1/conversations/{wid}/messages', json={'content': '重试未完成的生成'})
    assert retried.status_code == 202, retried.text
    new_job_id = UUID(retried.json()['action']['job_id'])
    assert new_job_id != job_id
    with get_session_factory()() as db:
        new_job = db.get(GenerationJob, new_job_id)
        assert [p['id'] for p in new_job.input_payload['confirmed_plan']['test_points']] == ['P-2']
        kept = db.get(WorkspaceCandidate, kept_id)
        assert kept.snapshot == snapshot and kept.version == 1 and kept.status == 'candidate'
    duplicate = await client.post(f'/api/v1/conversations/{wid}/messages', json={'content': '重试'})
    assert duplicate.status_code == 409


@pytest.mark.parametrize('changed', [False, True])
@pytest.mark.asyncio
async def test_failed_rewrite_reuses_confirmation_only_for_unchanged_assets(workspace, changed):
    from casepilot_api.models import GenerationJob, ConversationOperation, CaseChangeSet
    client, collection, wid = workspace
    item = (await client.post(f'/api/v1/collections/{collection}/test-cases', json={
        'title': '原始登录', 'module': '账号', 'steps': [{'action': '登录', 'expected': '进入首页'}],
    })).json()
    first = await client.post(f'/api/v1/conversations/{wid}/messages', json={
        'content': '将标题改为新登录，其他字段保持不变', 'intent_override': 'CASE_MODIFY',
        'targets': [{'kind': 'case', 'case_ids': [item['id']]}], 'target_scope': 'selected',
    })
    assert first.status_code == 202, first.text
    operation_id = first.json()['operation_plan']['current_operation_id']
    confirmed = await client.post(f'/api/v1/conversation-operations/{operation_id}/resume', json={
        'confirm_modification': True,
    })
    assert confirmed.status_code == 202, confirmed.text + first.text
    job_id = confirmed.json()['action']['job_id']
    with get_session_factory()() as db:
        job = db.get(GenerationJob, UUID(job_id)); job.status = 'failed'
        op = db.get(ConversationOperation, UUID(operation_id)); op.status = 'failed'
        assert op.payload['last_confirmed_modification']['cases']
        change = db.get(CaseChangeSet, op.related_change_set_id)
        if change: change.status = 'failed'
        db.commit()
    if changed:
        updated = await client.patch(f"/api/v1/test-cases/{item['id']}", json={'title': '外部已更新', 'base_revision_id': item['current_revision_id'], 'steps': item['steps']})
        assert updated.status_code == 200, updated.text
    retry = await client.post(f'/api/v1/conversations/{wid}/messages', json={'content': '重试修改任务'})
    assert retry.status_code == 202, retry.text
    if changed:
        assert not retry.json()['action'].get('job_id')
        assert retry.json()['assistant_message']['metadata']['modification_confirmation']
    else:
        assert retry.json()['action']['job_id'] != job_id
        assert retry.json()['operation_plan']['current_operation_id'] == operation_id
    actual = (await client.get(f"/api/v1/test-cases/{item['id']}")).json()
    assert actual['title'] == ('外部已更新' if changed else '原始登录')
