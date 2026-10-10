from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from casepilot_api import conversations
from casepilot_api.agent_router import CaseScopeDecision
from casepilot_api.schemas import ConversationMessageCreate


@pytest.fixture
def scope(monkeypatch):
    cases = [
        dict(
            id=str(uuid4()),
            case_key=f"QA-{i}",
            title="验证",
            module="登录",
            steps=[{"action": "发送验证码", "expected": "成功"}],
        )
        for i in range(2)
    ]
    conversation = SimpleNamespace(id=uuid4(), collection_id=uuid4(), context={})
    db = Mock()
    db.scalars.return_value = []
    db.scalar.return_value = None
    monkeypatch.setattr(conversations.settings, "agent_provider", "openai_compatible")
    monkeypatch.setattr(conversations, "_load_scope_snapshots", lambda *args: cases)
    monkeypatch.setattr(conversations, "_expand_conversation_targets", lambda db, c, p: p)
    monkeypatch.setattr(
        conversations, "resolve_scope", Mock(side_effect=AssertionError("rule selection called"))
    )
    selector = Mock(
        return_value=CaseScopeDecision(
            ids=[cases[1]["id"]],
            ambiguous=False,
            clarification="",
            reference="none",
            referenced_case_keys=[],
            requested_count=None,
        )
    )
    monkeypatch.setattr(conversations, "select_case_scope", selector)
    return db, conversation, cases, selector


@pytest.mark.parametrize("intent", ["CASE_QUERY", "CASE_MODIFY", "CASE_DELETE", "CASE_GENERATE"])
def test_model_receives_full_request_catalog_and_selection_context(scope, intent):
    db, conversation, cases, selector = scope
    payload = ConversationMessageCreate(
        content="选择正文包含验证码的用例，排除P0", target_case_ids=[cases[0]["id"]]
    )
    result, error = conversations._resolve_action_scope(db, conversation, payload, intent, "登录")
    assert error is None
    assert list(map(str, result.target_case_ids)) == [cases[1]["id"]]
    assert selector.call_args.args[0] == payload.content
    assert selector.call_args.args[1][0]["steps"] == cases[0]["steps"]
    assert selector.call_args.args[2]["selected_ids"] == [cases[0]["id"]]


@pytest.mark.parametrize(
    "update",
    [
        {"ids": [str(uuid4())]},
        {"referenced_case_keys": ["QA-UNKNOWN"]},
        {"requested_count": 22},
        {"reference": "selection"},
        {"reference": "previous_query"},
        {"reference": "previous_proposal"},
        {"ambiguous": True, "clarification": "请指定目标"},
    ],
)
def test_invalid_model_scope_is_never_applied(scope, update):
    db, conversation, cases, selector = scope
    selector.return_value = selector.return_value.model_copy(update=update)
    _, error = conversations._resolve_action_scope(
        db, conversation, ConversationMessageCreate(content="修改用例"), "CASE_MODIFY"
    )
    assert error


def test_model_failure_never_falls_back_to_all_cases(scope):
    db, conversation, _, selector = scope
    selector.side_effect = TimeoutError()
    _, error = conversations._resolve_action_scope(
        db, conversation, ConversationMessageCreate(content="删除全部"), "CASE_DELETE"
    )
    assert "没有修改或删除" in error


@pytest.mark.parametrize(
    "intent,has_error", [("CASE_QUERY", False), ("CASE_DELETE", True), ("CASE_MODIFY", True)]
)
def test_empty_latest_query_is_preserved(scope, intent, has_error):
    db, conversation, _, selector = scope
    db.scalar.return_value = SimpleNamespace(
        conversation_id=conversation.id, id=uuid4(), target={"case_ids": []}
    )
    selector.return_value = selector.return_value.model_copy(
        update={"ids": [], "reference": "previous_query"}
    )
    result, error = conversations._resolve_action_scope(
        db, conversation, ConversationMessageCreate(content="刚才查询到的用例"), intent
    )
    assert bool(error) == has_error
    assert result.target_case_ids == []
    assert selector.call_args.args[2]["latest_query"]["ids"] == []


def test_candidates_are_selected_by_model_and_mapped_to_snapshots(scope):
    db, conversation, cases, selector = scope
    candidate = SimpleNamespace(
        id=uuid4(), ref="candidate-1", version=1, snapshot={"title": "候选验证"}
    )
    db.scalars.return_value = [candidate]
    selector.return_value = selector.return_value.model_copy(
        update={"ids": [str(candidate.id), cases[0]["id"]]}
    )
    result, error = conversations._resolve_action_scope(
        db, conversation, ConversationMessageCreate(content="查询正式和候选"), "CASE_QUERY"
    )
    assert error is None
    assert result.target_candidate_snapshots[0].ref == candidate.ref
    assert list(map(str, result.target_case_ids)) == [cases[0]["id"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("changes_scope", [True, False])
async def test_resume_text_reselects_instead_of_freezing_stale_ui_targets(monkeypatch, changes_scope):
    from httpx import ASGITransport, AsyncClient

    from casepilot_api.main import app

    monkeypatch.setattr(conversations.settings, "agent_provider", "mock")
    dispatched = []
    monkeypatch.setattr(conversations, "enqueue_task", lambda *a, **k: dispatched.append(a))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        registered = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"model-scope-{uuid4().hex}@casepilot.test",
                "display_name": "Model scope",
                "password": "CasePilot123!",
            },
        )
        assert registered.status_code == 201
        space = registered.json()["spaces"][0]["id"]
        collection = (await client.get(f"/api/v1/spaces/{space}/collections")).json()[0]["id"]
        cases = []
        for title in ["短信登录", "密码登录"]:
            response = await client.post(
                f"/api/v1/collections/{collection}/test-cases",
                json={
                    "title": title,
                    "module": "登录",
                    "steps": [{"action": "登录", "expected": "成功"}],
                },
            )
            assert response.status_code == 201
            cases.append(response.json())
        workspace = (await client.put(f"/api/v1/collections/{collection}/workspace")).json()["id"]
        response = await client.post(
            f"/api/v1/conversations/{workspace}/messages",
            json={
                "content": "把登录模块用例优先级改为P2",
                "intent_override": "CASE_MODIFY",
                "target_case_ids": [case["id"] for case in cases],
            },
        )
        assert response.status_code == 202, response.text
        operation = response.json()["operation_plan"]["operations"][0]["id"]
        expected_ids = [cases[1]["id"]] if changes_scope else [case["id"] for case in cases]
        selector = Mock(
            return_value=CaseScopeDecision(
                ids=expected_ids,
                ambiguous=False,
                clarification="",
                reference="none",
                referenced_case_keys=[],
                requested_count=len(expected_ids),
            )
        )
        monkeypatch.setattr(conversations.settings, "agent_provider", "openai_compatible")
        monkeypatch.setattr(conversations, "select_case_scope", selector)
        resume = f"/api/v1/conversation-operations/{operation}/resume"
        corrected = await client.post(
            resume,
            json={
                "content": f"范围缩小为仅用例 {cases[1]['case_key']}，优先级改为P2" if changes_scope else "步骤更清晰",
                "targets": [{"kind": "case", "case_ids": [case["id"] for case in cases]}],
            },
        )
        assert corrected.status_code == 202, corrected.text
        assert set(corrected.json()["assistant_message"]["target_case_ids"]) == set(expected_ids)
        assert selector.call_args.args[0].startswith("把登录模块用例优先级改为P2\n补充说明：")
        assert selector.call_count == 1
        assert not dispatched
        confirmed = await client.post(resume, json={"confirm_modification": True})
        assert confirmed.status_code == 202, confirmed.text
        assert confirmed.json()["action"]["job_id"]
        assert selector.call_count == 1
        assert len(dispatched) == 1


def test_scope_transient_failure_retries_without_changing_catalog(scope):
    db, conversation, cases, selector = scope
    valid = selector.return_value
    selector.side_effect = [TimeoutError(), valid]
    payload = ConversationMessageCreate(content="改写登录模块用例，步骤更清晰")
    result, error = conversations._resolve_action_scope(db, conversation, payload, "CASE_MODIFY")
    assert error is None
    assert list(map(str, result.target_case_ids)) == [cases[1]["id"]]
    assert selector.call_count == 2
    assert selector.call_args_list[0] == selector.call_args_list[1]


def test_router_scope_question_cannot_bypass_catalog_selector(monkeypatch):
    monkeypatch.setattr(conversations.settings, "agent_provider", "openai_compatible")
    monkeypatch.setattr(conversations, "_collection_gate", lambda *args: None)
    monkeypatch.setattr(conversations, "_link_rewrite_round", lambda db, c, op, p: p)
    payload = ConversationMessageCreate(content="查询前置条件包含只读审计账号的正式用例")
    operation = SimpleNamespace(
        payload={
            "plan": {
                "clarification_questions": ["请指定要处理的模块名称或用例编号。"],
                "reason_codes": ["TARGET_EVIDENCE_NOT_IN_REQUEST"],
                "routing_source": "semantic",
            }
        }
    )
    db = Mock()
    db.get.return_value = operation
    selector = Mock(return_value=(payload, "来自模型选择器的澄清"))
    monkeypatch.setattr(conversations, "_resolve_model_scope", selector)
    result, action, _ = conversations._start_action(
        db,
        None,
        SimpleNamespace(id=uuid4(), collection_id=uuid4(), context={}),
        SimpleNamespace(content=payload.content),
        payload,
        "CASE_QUERY",
        1.0,
        uuid4(),
    )
    assert selector.call_count == 1
    assert result.content == "来自模型选择器的澄清"
    assert action["type"] == "clarification"


def test_invalid_field_value_reference_is_reselected_with_grounded_feedback(scope):
    db, conversation, cases, selector = scope
    valid = selector.return_value
    selector.side_effect = [valid.model_copy(update={"referenced_case_keys": ["改P2"]}), valid]
    payload = ConversationMessageCreate(content="刚才说错了，改P2，标题不要动。")
    result, error = conversations._resolve_action_scope(db, conversation, payload, "CASE_MODIFY")
    assert error is None
    assert list(map(str, result.target_case_ids)) == [cases[1]["id"]]
    assert selector.call_count == 2
    assert selector.call_args.args[0] == payload.content
    assert selector.call_args.args[2]["validation_feedback"]["unknown_references"] == ["改P2"]


def test_reselection_cannot_hide_a_missing_explicit_target(scope):
    db, conversation, _, selector = scope
    selector.return_value = selector.return_value.model_copy(
        update={"referenced_case_keys": ["QA-MISSING"]}
    )
    _, error = conversations._resolve_action_scope(
        db,
        conversation,
        ConversationMessageCreate(content="修改QA-MISSING优先级为P2"),
        "CASE_MODIFY",
    )
    assert "不在当前集合" in error
    assert selector.call_count == 2


def test_scope_transport_compacts_ids_and_restores_exact_membership(monkeypatch):
    import json

    import agents

    from casepilot_api.agent_router import select_case_scope

    ids = [str(uuid4()) for _ in range(1000)]
    observed = {}

    def run(agent, payload, **kwargs):
        observed.update(json.loads(payload))
        return SimpleNamespace(
            final_output=CaseScopeDecision(
                ids=["c0", "c999"],
                ambiguous=False,
                clarification="",
                reference="selection",
                referenced_case_keys=[],
                requested_count=2,
            )
        )

    monkeypatch.setattr(agents.Runner, "run_sync", run)
    decision = select_case_scope(
        "修改勾选的两条用例",
        [{"id": value, "case_key": f"QA-{i}"} for i, value in enumerate(ids)],
        {"selected_ids": [ids[0], ids[-1]], "latest_query": {"ids": [ids[-1]]}},
        intent="CASE_MODIFY",
        model_name="test",
        base_url="http://localhost:9999",
        api_key="test-fixture",
        timeout_seconds=1,
        tracing_enabled=False,
    )
    assert observed["context"]["selected_ids"] == ["c0", "c999"]
    assert observed["context"]["latest_query"]["ids"] == ["c999"]
    assert observed["cases"][-1]["source_id"] == ids[-1]
    assert decision.ids == [ids[0], ids[-1]]


def test_scope_transport_rejects_unknown_short_reference(monkeypatch):
    import agents

    from casepilot_api.agent_router import select_case_scope

    monkeypatch.setattr(
        agents.Runner,
        "run_sync",
        lambda *a, **kw: SimpleNamespace(
            final_output=CaseScopeDecision(
                ids=["c1"],
                ambiguous=False,
                clarification="",
                reference="none",
                referenced_case_keys=[],
                requested_count=None,
            )
        ),
    )
    with pytest.raises(ValueError, match="unknown_reference"):
        select_case_scope(
            "改所有用例",
            [{"id": str(uuid4())}],
            {},
            intent="CASE_MODIFY",
            model_name="test",
            base_url="http://localhost:9999",
            api_key="test-fixture",
            timeout_seconds=1,
            tracing_enabled=False,
        )


def test_existing_proposal_asset_id_is_a_valid_reference(scope):
    db, conversation, cases, selector = scope
    selector.return_value = selector.return_value.model_copy(
        update={
            "referenced_case_keys": [cases[1]["id"]],
        }
    )
    result, error = conversations._resolve_action_scope(
        db,
        conversation,
        ConversationMessageCreate(content="这条优先级改P2，保留标题"),
        "CASE_MODIFY",
    )
    assert error is None
    assert list(map(str, result.target_case_ids)) == [cases[1]["id"]]


@pytest.mark.parametrize(
    "refs,expected",
    [
        (["c0..c1", "c3"], [0, 1, 3]),
        (["c0..c1", "c1"], [0, 1]),
        (["c0..c4"], None),
        (["c2..c0"], None),
    ],
)
def test_scope_ranges_are_bounded_and_preserve_excluded_gaps(monkeypatch, refs, expected):
    import agents

    from casepilot_api.agent_router import select_case_scope

    ids = [str(uuid4()) for _ in range(4)]
    monkeypatch.setattr(
        agents.Runner,
        "run_sync",
        lambda *a, **kw: SimpleNamespace(
            final_output=CaseScopeDecision(
                ids=refs,
                ambiguous=False,
                clarification="",
                reference="none",
                referenced_case_keys=[],
                requested_count=None,
            )
        ),
    )

    def select():
        return select_case_scope(
            "除第三条以外修改其余用例",
            [{"id": ref} for ref in ids],
            {},
            intent="CASE_MODIFY",
            model_name="test",
            base_url="http://localhost:9999",
            api_key="test-fixture",
            timeout_seconds=1,
            tracing_enabled=False,
        )

    if expected is None:
        with pytest.raises(ValueError, match="unknown_reference"):
            select()
    else:
        assert select().ids == [ids[index] for index in expected]


def test_polish_explicit_selection_skips_model(scope):
    db, conversation, cases, selector = scope
    payload = ConversationMessageCreate(
        content="润色标题", target_scope="selected",
        targets=[{"kind": "case", "case_ids": [cases[0]["id"]]}],
        target_case_ids=[cases[0]["id"]],
    )
    result, error = conversations._resolve_action_scope(db, conversation, payload, "CASE_MODIFY")
    assert error is None
    assert result.target_case_ids == payload.target_case_ids
    selector.assert_not_called()


@pytest.mark.parametrize("targets", [[], [{"kind": "module", "module": "登录"}]])
def test_polish_never_expands_missing_selection(scope, targets):
    db, conversation, _, selector = scope
    _, error = conversations._resolve_action_scope(
        db, conversation,
        ConversationMessageCreate(content="润色", target_scope="selected", targets=targets),
        "CASE_MODIFY",
    )
    assert error
    selector.assert_not_called()


def test_polish_does_not_silently_drop_missing_candidate(scope):
    db, conversation, cases, selector = scope
    _, error = conversations._resolve_action_scope(
        db, conversation,
        ConversationMessageCreate(
            content="润色", target_scope="selected",
            targets=[{"kind": "case", "case_ids": [cases[0]["id"]], "candidate_refs": ["missing"]}],
            target_case_ids=[cases[0]["id"]],
        ), "CASE_MODIFY",
    )
    assert error
    selector.assert_not_called()
