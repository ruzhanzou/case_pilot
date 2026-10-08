from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from casepilot_api import conversations
from casepilot_api.models import ConversationMessage, TestCaseRevision as Revision
from casepilot_api.schemas import ChangeSetApplyRequest


def test_conflicting_proposal_stops_waiting_for_confirmation():
    db = Mock()
    operation = SimpleNamespace(status="awaiting_confirmation", result={"kept": True})
    db.scalar.return_value = operation
    proposal = SimpleNamespace(id=uuid4(), status="ready")
    conversations._mark_change_set_conflict(db, proposal)
    assert proposal.status == "conflict"
    assert operation.status == "failed"
    assert operation.result == {"kept": True, "change_set_status": "conflict"}
    assert operation.completed_at <= datetime.now(UTC)
    db.commit.assert_called_once()


@pytest.mark.parametrize("operation,fields", [("modify", []), ("modify", ["unknown"]), ("delete", [])])
def test_unselected_case_does_not_write_revision_or_delete(monkeypatch, operation, fields):
    case_id, revision_id = uuid4(), uuid4()
    case = SimpleNamespace(id=case_id, current_revision_id=revision_id, deleted_at=None)
    item = {"ref": str(case_id), "test_case_id": str(case_id), "target_type": "formal",
            "base_revision_id": str(revision_id), "operation": operation,
            "field_diff": [{"field": "delete" if operation == "delete" else "title", "before": "Old", "after": "New"}]}
    change = SimpleNamespace(id=uuid4(), conversation_id=uuid4(), generation_job_id=None,
        instruction="Selected changes", scope="current", status="ready", items=[item],
        created_at=datetime.now(UTC), applied_at=None)
    db = Mock()
    db.scalar.return_value = None
    monkeypatch.setattr(conversations, "_ensure_change_set", lambda *args: change)
    result = conversations.apply_change_set(change.id,
        ChangeSetApplyRequest(accepted_fields={str(case_id): fields}), SimpleNamespace(id=uuid4()), db)
    assert db.scalar.call_count == 1  # Only the operation lookup; no case lock.
    assert case.current_revision_id == revision_id
    assert case.deleted_at is None
    assert result.change_set.items[0]["status"] == "rejected"
    assert not any(isinstance(call.args[0], Revision) for call in db.add.call_args_list)
    messages = [call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], ConversationMessage)]
    assert "0 条" in messages[0].content


def test_previous_generation_uses_committed_formal_cases():
    from casepilot_api.schemas import ConversationMessageCreate, ConversationTarget
    conversation_id, formal_id, candidate_id, operation_id = (uuid4() for _ in range(4))
    db = Mock()
    db.get.return_value = SimpleNamespace(conversation_id=conversation_id,
        result={"candidate_ids": [str(candidate_id)], "test_case_ids": [str(formal_id)]})
    db.scalars.return_value = [formal_id]
    result = conversations._expand_conversation_targets(db,
        SimpleNamespace(id=conversation_id, collection_id=uuid4(), context={"phase": "maintenance"}),
        ConversationMessageCreate(content="评审刚才生成的用例", targets=[
            ConversationTarget(kind="previous_result", source_operation_id=operation_id)]))
    assert result.target_case_ids == [formal_id]
    assert result.target_candidate_snapshots == []
    db.scalars.assert_called_once()  # collection membership is still checked


def test_single_discard_keeps_other_items_pending_and_retry_is_idempotent(monkeypatch):
    refs = [str(uuid4()), str(uuid4())]
    items = [{'ref': ref, 'target_type': 'formal', 'status': 'ready', 'operation': 'modify',
              'field_diff': [{'field': 'title'}]} for ref in refs]
    change = SimpleNamespace(id=uuid4(), conversation_id=uuid4(), generation_job_id=None,
        instruction='Review', scope='current', status='ready', items=items,
        created_at=datetime.now(UTC), applied_at=None)
    operation = SimpleNamespace(id=uuid4(), intent='CASE_MODIFY', status='awaiting_confirmation', result={})
    db = Mock(); db.scalar.return_value = operation
    monkeypatch.setattr(conversations, '_ensure_change_set', lambda *args: change)
    account = SimpleNamespace(id=uuid4())
    request = ChangeSetApplyRequest(accepted_fields={refs[0]: []}, review_refs=[refs[0]])
    conversations.apply_change_set(change.id, request, account, db)
    assert change.status == 'ready'
    assert [item['status'] for item in change.items] == ['rejected', 'ready']
    assert operation.status == 'awaiting_confirmation'
    assert operation.completed_at is None
    calls = db.add.call_count
    conversations.apply_change_set(change.id, request, account, db)
    assert db.add.call_count == calls
    conversations.apply_change_set(change.id, ChangeSetApplyRequest(accepted_fields={refs[1]: []}, review_refs=[refs[1]]), account, db)
    assert operation.status == 'completed'
    assert all(item['status'] == 'rejected' for item in change.items)


def test_single_review_rejects_unknown_refs(monkeypatch):
    from fastapi import HTTPException
    change = SimpleNamespace(status='ready', items=[{'ref':'known'}])
    monkeypatch.setattr(conversations, '_ensure_change_set', lambda *args: change)
    with pytest.raises(HTTPException) as error:
        conversations.apply_change_set(uuid4(), ChangeSetApplyRequest(review_refs=['other']), SimpleNamespace(id=uuid4()), Mock())
    assert error.value.status_code == 422


def test_discard_remaining_preserves_already_accepted_items(monkeypatch):
    accepted, pending = str(uuid4()), str(uuid4())
    change = SimpleNamespace(id=uuid4(), conversation_id=uuid4(), generation_job_id=None,
        instruction='Review', scope='current', status='ready', created_at=datetime.now(UTC), applied_at=None,
        items=[{'ref':accepted,'status':'applied','target_type':'formal','field_diff':[]},
               {'ref':pending,'status':'ready','target_type':'formal','field_diff':[{'field':'title'}]}])
    operation = SimpleNamespace(id=uuid4(), intent='CASE_MODIFY', status='awaiting_confirmation', result={})
    db = Mock(); db.scalar.return_value = operation
    monkeypatch.setattr(conversations, '_ensure_change_set', lambda *args: change)
    result = conversations.reject_change_set(change.id, SimpleNamespace(id=uuid4()), db)
    assert result.status == 'applied'
    assert [item['status'] for item in result.items] == ['applied','rejected']
    assert operation.status == 'completed'
    message = next(call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], ConversationMessage))
    assert '已采纳 1 条' in message.content and '已丢弃 1 条' in message.content


@pytest.mark.parametrize('followers', [0, 1])
def test_reject_middle_change_stops_only_queued_followers(monkeypatch, followers):
    change = SimpleNamespace(id=uuid4(), conversation_id=uuid4(), generation_job_id=None,
        instruction='Review', scope='current', status='ready', items=[],
        created_at=datetime.now(UTC), applied_at=None)
    operation = SimpleNamespace(id=uuid4(), message_id=uuid4(), sequence=1,
        intent='CASE_MODIFY', status='awaiting_confirmation')
    db = Mock(); db.scalar.return_value = operation
    db.execute.return_value.rowcount = followers
    monkeypatch.setattr(conversations, '_ensure_change_set', lambda *args: change)
    conversations.reject_change_set(change.id, SimpleNamespace(id=uuid4()), db)
    assert operation.status == 'cancelled'
    statement = db.execute.call_args.args[0]
    parameters = statement.compile().params
    assert operation.message_id in parameters.values()
    assert operation.sequence in parameters.values()
    assert 'queued' in parameters.values()
    assert 'cancelled' in parameters.values()
    messages = [call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], ConversationMessage)]
    assert ('后续任务已停止' in messages[0].content) == bool(followers)


@pytest.mark.parametrize('instruction,refs', [
    ('修改前置条件', ['one']), ('新建一个任务修改标题', ['one']),
    ('修改其他模块', ['other']), ('不要新建任务，继续修改标题', ['one']),
])
def test_open_mutation_task_always_keeps_followups(instruction, refs):
    source = SimpleNamespace(id=uuid4(), intent='CASE_MODIFY', payload={'task_id': 'root', 'task_revision': 2}, target={'case_ids':['one']})
    operation = SimpleNamespace(id=uuid4(), intent='CASE_MODIFY', payload={})
    class Payload(SimpleNamespace):
        def model_copy(self, update): return Payload(**{**vars(self), **update})
    payload = Payload(source_operation_id=None, content=instruction, targets=[], target_case_ids=refs, target_candidate_snapshots=[])
    db = Mock(); db.scalars.return_value = [source]
    conversation = SimpleNamespace(id=uuid4(), context={})
    result = conversations._link_rewrite_round(db, conversation, operation, payload)
    assert result.source_operation_id == source.id
    assert operation.payload['task_id'] == 'root'
    assert operation.payload['task_revision'] == 3
    assert conversation.context['active_mutation_operation_id'] == str(operation.id)


def test_closed_task_is_not_reopened_by_explicit_old_source():
    operation = SimpleNamespace(id=uuid4(), intent='CASE_MODIFY', payload={})
    payload = SimpleNamespace(source_operation_id=uuid4())
    conversation = SimpleNamespace(id=uuid4(), context={'active_mutation_task_id': None})
    conversations._link_rewrite_round(Mock(), conversation, operation, payload)
    assert operation.payload['task_id'] == str(operation.id)
    assert operation.payload['source_operation_id'] is None
    assert operation.payload['task_revision'] == 1


def test_query_does_not_replace_open_mutation_and_review_closes_it():
    operation = SimpleNamespace(id=uuid4(), intent='CASE_QUERY', payload={})
    conversation = SimpleNamespace(id=uuid4(), context={'active_mutation_task_id':'root','active_mutation_operation_id':'round'})
    payload = SimpleNamespace()
    conversations._link_rewrite_round(Mock(), conversation, operation, payload)
    assert conversation.context['active_mutation_task_id'] == 'root'
    operation = SimpleNamespace(id=uuid4(), conversation_id=conversation.id, payload={'task_id':'root'}, result={})
    db=Mock(); db.get.return_value=conversation
    conversations._finish_mutation_task(db, operation)
    assert conversation.context['active_mutation_task_id'] is None
    assert operation.result['task_closed'] is True


def test_candidate_rewrite_belongs_to_open_generation():
    source=SimpleNamespace(id=uuid4(), intent='CASE_GENERATE', payload={'task_id':'root','task_revision':1})
    operation=SimpleNamespace(id=uuid4(),intent='CASE_MODIFY',payload={})
    conversation=SimpleNamespace(id=uuid4(), context={'active_mutation_task_id':'root','active_mutation_operation_id':str(source.id)})
    class Payload(SimpleNamespace):
        def model_copy(self, update): return Payload(**{**vars(self),**update})
    payload=Payload(source_operation_id=None,targets=[],target_case_ids=[],target_candidate_snapshots=[])
    db=Mock();db.get.return_value=source
    result=conversations._link_rewrite_round(db,conversation,operation,payload)
    assert operation.payload['task_intent']=='CASE_GENERATE'
    assert operation.payload['task_id']=='root'
    assert result.targets[0].kind=='previous_result'


def test_formal_query_during_candidate_review_excludes_unaccepted_candidates(monkeypatch):
    from casepilot_api.schemas import ConversationMessageCreate
    formal_id = uuid4()
    conversation = SimpleNamespace(id=uuid4(), collection_id=uuid4(), context={'phase': 'candidate_review'})
    monkeypatch.setattr(conversations, '_load_scope_snapshots', lambda *args: [{'id':str(formal_id),'case_key':'FORMAL-1','title':'正式用例','module':'登录'}])
    db = Mock()
    payload = ConversationMessageCreate(content='查询当前集合全部正式用例，只查询不修改。')
    resolved, error = conversations._resolve_action_scope(db, conversation, payload, 'CASE_QUERY')
    assert error is None
    assert resolved.target_case_ids == [formal_id]
    assert resolved.target_candidate_snapshots == []
    db.scalars.assert_not_called()


@pytest.mark.parametrize('edit_content', [False, True])
def test_candidate_selection_does_not_invalidate_content_revision(monkeypatch, edit_content):
    from casepilot_api.schemas import WorkspaceCandidateUpdate
    candidate = SimpleNamespace(id=uuid4(), conversation_id=uuid4(), status='candidate', version=3,
        included=True, snapshot={'title':'登录失败','module':'登录','priority':'P1','case_type':'功能',
            'preconditions':['独立环境'],'steps':[{'action':'输入错误密码','expected':'HTTP 401'}]})
    db=Mock();db.scalar.return_value=candidate
    monkeypatch.setattr(conversations, '_ensure_conversation', lambda *args: SimpleNamespace())
    monkeypatch.setattr(conversations, '_candidate_view', lambda item: item)
    payload=WorkspaceCandidateUpdate(base_version=3,included=False,
        snapshot={**candidate.snapshot,'preconditions':['可查询审计日志']} if edit_content else None)
    result=conversations.update_workspace_candidate(candidate.id,payload,SimpleNamespace(id=uuid4()),db)
    assert result.version == (4 if edit_content else 3)
    assert result.included is False
    db.commit.assert_called_once()


def test_candidate_commit_cannot_bypass_pending_ai_review(monkeypatch):
    from fastapi import HTTPException
    from casepilot_api.schemas import WorkspaceCandidateCommitRequest
    conversation=SimpleNamespace(id=uuid4(),collection_id=uuid4())
    candidate=SimpleNamespace(id=uuid4(),ref='TC-002')
    change=SimpleNamespace(items=[{'ref':'TC-002','target_type':'candidate','status':'ready'}])
    db=Mock();db.scalars.side_effect=[[candidate],[change]]
    monkeypatch.setattr(conversations,'_ensure_conversation',lambda *args:conversation)
    monkeypatch.setattr(conversations,'_require_idle_conversation',lambda *args:None)
    with pytest.raises(HTTPException) as error:
        conversations.commit_workspace_candidates(conversation.id,WorkspaceCandidateCommitRequest(),SimpleNamespace(id=uuid4()),db)
    assert error.value.status_code == 409
    assert error.value.detail == 'candidate_changes_need_review'
    db.commit.assert_not_called()
    db.add.assert_not_called()


@pytest.mark.parametrize('count,valid', [('2',True),('3',False),('',True)])
def test_remaining_candidate_scope_uses_current_membership(monkeypatch,count,valid):
    from casepilot_api.schemas import ConversationMessageCreate
    candidates=[SimpleNamespace(id=uuid4(),ref=f'TC-{i}',version=1,snapshot={'title':f'候选{i}'}) for i in [1,2]]
    conversation=SimpleNamespace(id=uuid4(),collection_id=uuid4(),context={'phase':'candidate_review'})
    db=Mock();db.scalars.return_value=candidates
    quantity=f'{count}条' if count else ''
    payload=ConversationMessageCreate(content=f'重写剩余未纳入的{quantity}候选用例，已纳入用例不得改动。')
    resolved,error=conversations._resolve_action_scope(db,conversation,payload,'CASE_MODIFY')
    if valid:
        assert error is None
        assert [item.ref for item in resolved.target_candidate_snapshots] == ['TC-1','TC-2']
        assert resolved.target_case_ids == []
    else:
        assert '不一致' in error


def test_query_then_modify_carries_candidate_references(monkeypatch):
    from casepilot_api.schemas import ConversationMessageCreate, ConversationTarget
    conversation=SimpleNamespace(id=uuid4(),collection_id=uuid4(),context={'phase':'candidate_review'})
    source=SimpleNamespace(id=uuid4(),conversation_id=conversation.id,intent='CASE_QUERY',payload={},result={},target={'candidate_refs':['TC-2'],'case_ids':[]})
    candidate=SimpleNamespace(ref='TC-2',version=2,snapshot={'title':'剩余候选'})
    db=Mock();db.get.return_value=source;db.scalar.return_value=candidate;db.scalars.return_value=[]
    payload=ConversationMessageCreate(content='修改查询到的候选',targets=[ConversationTarget(kind='previous_result',source_operation_id=source.id)])
    resolved=conversations._expand_conversation_targets(db,conversation,payload)
    assert [item.ref for item in resolved.target_candidate_snapshots] == ['TC-2']
    assert resolved.target_case_ids == []


def test_abandoning_revised_task_cancels_queued_followups_from_original_request():
    conversation=SimpleNamespace(id=uuid4(),context={'active_mutation_task_id':'root'})
    operation=SimpleNamespace(id=uuid4(),conversation_id=conversation.id,payload={'task_id':'root','task_intent':'CASE_MODIFY'},result={})
    db=Mock();db.get.return_value=conversation
    conversations._finish_mutation_task(db,operation,discard=True)
    statements=[call.args[0].compile() for call in db.execute.call_args_list]
    queued=next(statement for statement in statements if 'queued' in statement.params.values())
    assert 'root' in queued.params.values()
    assert conversation.id in queued.params.values()
    assert 'cancelled' in queued.params.values()
    assert 'message_id IN (SELECT' in str(queued)
    assert conversation.context['active_mutation_task_id'] is None


def test_numeric_candidate_count_does_not_narrow_the_remaining_set():
    from casepilot_api.schemas import ConversationMessageCreate
    candidates=[SimpleNamespace(id=uuid4(),ref=str(i),version=1,snapshot={'title':f'候选{i}'}) for i in [2,3]]
    conversation=SimpleNamespace(id=uuid4(),collection_id=uuid4(),context={'phase':'candidate_review'})
    db=Mock();db.scalars.return_value=candidates
    payload=ConversationMessageCreate(content='重写剩余未纳入的2条候选用例，最多3步')
    resolved,error=conversations._resolve_action_scope(db,conversation,payload,'CASE_MODIFY','剩余未纳入的2条候选用例')
    assert error is None
    assert [item.ref for item in resolved.target_candidate_snapshots] == ['2','3']
    payload=ConversationMessageCreate(content='修改候选 2 的步骤')
    resolved,error=conversations._resolve_action_scope(db,conversation,payload,'CASE_MODIFY','2')
    assert error is None
    assert [item.ref for item in resolved.target_candidate_snapshots] == ['2']


def test_inventory_query_includes_both_formal_and_pending_candidates(monkeypatch):
    from casepilot_api.schemas import ConversationMessageCreate
    formal_id, candidate_id = uuid4(), uuid4()
    conversation = SimpleNamespace(id=uuid4(), collection_id=uuid4(), context={'phase':'candidate_review'})
    monkeypatch.setattr(conversations, '_load_scope_snapshots', lambda *args: [{'id':formal_id,'case_key':'F-1','title':'正式','module':'创建'}])
    candidate = SimpleNamespace(id=candidate_id,ref='C-1',version=1,snapshot={'title':'候选','module':'变更'})
    db=Mock();db.scalars.return_value=[candidate]
    payload=ConversationMessageCreate(content='现在正式用例和待审阅候选各有多少？分别按模块列出来，只查询，不修改。')
    result,error=conversations._resolve_action_scope(db,conversation,payload,'CASE_QUERY','非原文范围')
    assert error is None
    assert result.target_case_ids == [formal_id]
    assert [c.ref for c in result.target_candidate_snapshots] == ['C-1']
    summary=conversations._inventory_summary([
        {'target_type':'formal','snapshot':{'module':'创建'}},
        {'target_type':'candidate','snapshot':{'module':'变更'}},
        {'target_type':'candidate','snapshot':{'module':'变更'}},
    ])
    assert summary == '正式用例 1 条：创建 1 条\n待审阅候选 2 条：变更 2 条'
    assert not conversations._is_inventory_query('CASE_MODIFY',payload.content)


def test_only_unaccepted_suggestions_are_in_rewrite_scope(monkeypatch):
    from casepilot_api.schemas import ConversationMessageCreate
    source_id,change_id=uuid4(),uuid4()
    candidates=[SimpleNamespace(id=uuid4(),ref=f'TC-{i}',version=1,snapshot={'title':f'场景{i}','module':'预约变更'}) for i in range(10)]
    source=SimpleNamespace(id=source_id, related_change_set_id=change_id)
    change=SimpleNamespace(status='ready',items=[{'ref':c.ref,'status':'applied' if i<3 else 'ready'} for i,c in enumerate(candidates)])
    db=Mock();db.get.side_effect=lambda model,key: source if key==source_id else change;db.scalars.return_value=candidates
    conversation=SimpleNamespace(id=uuid4(),collection_id=uuid4(),context={'phase':'candidate_review'})
    payload=ConversationMessageCreate(content='“预约变更”模块剩余7条未采纳建议的候选，请细化预期，刚刚采纳的3条不要再改。',source_operation_id=source_id)
    result,error=conversations._resolve_action_scope(db,conversation,payload,'CASE_MODIFY')
    assert error is None
    assert [c.ref for c in result.target_candidate_snapshots]==[c.ref for c in candidates[3:]]


def test_explicit_discarded_case_is_not_replaced_by_preserved_pending_suggestions():
    from casepilot_api.schemas import ConversationMessageCreate
    candidate=SimpleNamespace(id=uuid4(),ref='TC-9',version=1,snapshot={'title':'目标场景','module':'预约变更'})
    db=Mock();db.scalars.return_value=[candidate]
    conversation=SimpleNamespace(id=uuid4(),collection_id=uuid4(),context={'phase':'candidate_review'})
    payload=ConversationMessageCreate(content='重新修改候选 TC-9，保留其他6条待审阅建议。')
    result,error=conversations._resolve_action_scope(db,conversation,payload,'CASE_MODIFY')
    assert error is None
    assert [c.ref for c in result.target_candidate_snapshots] == ['TC-9']
    db.get.assert_not_called()


@pytest.mark.parametrize('matches,expects_error', [([0,2],False),([],False),(['outside'],True)])
def test_topic_query_filters_within_authorized_module(monkeypatch,matches,expects_error):
    from casepilot_api.schemas import ConversationMessageCreate
    ids=[uuid4() for _ in range(3)]
    snapshots=[{'id':key,'case_key':f'CASE-{i}','title':f'场景{i}','module':'预约查询'} for i,key in enumerate(ids)]
    monkeypatch.setattr(conversations,'_load_scope_snapshots',lambda *args:snapshots)
    monkeypatch.setattr(conversations,'select_query_case_ids',lambda *args,**kw:[str(ids[i]) if isinstance(i,int) else i for i in matches])
    conversation=SimpleNamespace(id=uuid4(),collection_id=uuid4(),context={'phase':'maintenance'})
    result,error=conversations._resolve_action_scope(Mock(),conversation,ConversationMessageCreate(content='查询“预约查询”模块中关于无结果展示和取消后状态展示的用例，只列出来。'),'CASE_QUERY')
    assert bool(error) == expects_error
    if not expects_error:
        assert result.target_case_ids == [ids[i] for i in matches]


@pytest.mark.parametrize('count,expected_error', [(2, False), (1, True), (0, True)])
def test_followup_delete_uses_exact_previous_query(monkeypatch, count, expected_error):
    from casepilot_api.schemas import ConversationMessageCreate
    conversation = SimpleNamespace(id=uuid4(), collection_id=uuid4(), context={})
    source = SimpleNamespace(id=uuid4(), conversation_id=conversation.id)
    db = Mock(); db.scalar.return_value = source
    ids = [uuid4() for _ in range(count)]
    def expand(db, conv, payload):
        assert payload.targets[0].source_operation_id == source.id
        return payload.model_copy(update={'target_case_ids': ids})
    monkeypatch.setattr(conversations, '_expand_conversation_targets', expand)
    result, error = conversations._resolve_action_scope(db, conversation,
        ConversationMessageCreate(content='删除刚才查询到的两条用例，其他用例不动。'), 'CASE_DELETE')
    assert bool(error) == expected_error
    if not error:
        assert result.target_case_ids == ids
    statement = str(db.scalar.call_args.args[0])
    assert 'conversation_id =' in statement and 'status =' in statement


def test_followup_delete_rejects_foreign_query():
    from casepilot_api.schemas import ConversationMessageCreate
    db = Mock(); db.scalar.return_value = SimpleNamespace(conversation_id=uuid4())
    _, error = conversations._resolve_action_scope(db,
        SimpleNamespace(id=uuid4(), collection_id=uuid4()),
        ConversationMessageCreate(content='删除刚才查询到的两条用例'), 'CASE_DELETE')
    assert error


@pytest.mark.parametrize('content,expected', [
    ('汇总当前各模块用例数量，以及本次新增、改写和删除的结果，只查询汇总，不修改。', True),
    ('查询预约变更模块关于权限的用例', False),
    ('正式和候选分别有多少条', True),
])
def test_inventory_query_detects_module_totals(content, expected):
    assert conversations._is_inventory_query('CASE_QUERY', content) is expected
    assert not conversations._is_inventory_query('CASE_DELETE', content)


@pytest.mark.parametrize("status", ["awaiting_clarification", "failed"])
def test_followup_uses_last_valid_proposal_after_unsuccessful_round(status):
    conversation_id = uuid4()
    first = SimpleNamespace(
        id=uuid4(),
        conversation_id=conversation_id,
        related_change_set_id=uuid4(),
        payload={},
        intent="CASE_MODIFY",
    )
    failed = SimpleNamespace(
        id=uuid4(),
        conversation_id=conversation_id,
        related_change_set_id=uuid4() if status == "failed" else None,
        payload={"source_operation_id": str(first.id)},
        status=status,
    )
    db = Mock()
    rows = {first.id: first, first.related_change_set_id: SimpleNamespace(status="ready")}
    if failed.related_change_set_id:
        rows[failed.related_change_set_id] = SimpleNamespace(status="failed")
    db.get.side_effect = lambda _model, key: rows[key]
    assert conversations._rewrite_proposal_source(db, failed) is first


@pytest.mark.parametrize("status", ["applied", "rejected", "conflict", "no_changes"])
def test_followup_does_not_resurrect_older_reviewed_or_conflicting_proposals(status):
    source = SimpleNamespace(
        id=uuid4(), related_change_set_id=uuid4(), payload={"source_operation_id": str(uuid4())}
    )
    db = Mock()
    db.get.return_value = SimpleNamespace(status=status)
    assert conversations._rewrite_proposal_source(db, source) is source
    assert db.get.call_count == 1


@pytest.mark.parametrize("target_type", ["formal", "candidate"])
def test_unchecked_stale_case_requires_no_version_lookup(monkeypatch, target_type):
    ref = str(uuid4())
    change = SimpleNamespace(
        id=uuid4(),
        conversation_id=uuid4(),
        generation_job_id=None,
        instruction="Only selected",
        scope="current",
        status="ready",
        items=[
            {
                "ref": ref,
                "target_type": target_type,
                "status": "ready",
                "field_diff": [{"field": "title"}],
            }
        ],
        created_at=datetime.now(UTC),
        applied_at=None,
    )
    db = Mock()
    db.scalar.return_value = None
    monkeypatch.setattr(conversations, "_ensure_change_set", lambda *args: change)
    result = conversations.apply_change_set(
        change.id, ChangeSetApplyRequest(accepted_fields={ref: []}), SimpleNamespace(id=uuid4()), db
    )
    assert result.change_set.status == "rejected"
    assert db.scalar.call_count == 1
    assert "conversation_operations" in str(db.scalar.call_args.args[0])


@pytest.mark.parametrize('key', ['candidate_ids', 'test_case_ids', 'query_cases'])
def test_successful_result_is_not_replaced_by_its_earlier_source(key):
    source = SimpleNamespace(
        id=uuid4(), related_change_set_id=None,
        payload={'source_operation_id': str(uuid4())}, result={key: ['existing-result']},
    )
    db = Mock()
    assert conversations._rewrite_proposal_source(db, source) is source
    db.get.assert_not_called()


def test_stale_superseded_source_follows_the_current_proposal():
    conversation_id = uuid4()
    current_change_id = uuid4()
    old = SimpleNamespace(
        id=uuid4(),
        conversation_id=conversation_id,
        related_change_set_id=uuid4(),
        payload={},
        result={"superseded_by": str(current_change_id)},
    )
    current = SimpleNamespace(
        id=uuid4(),
        conversation_id=conversation_id,
        related_change_set_id=current_change_id,
        payload={},
        result={},
    )
    db = Mock()
    db.get.side_effect = lambda model, key: SimpleNamespace(
        status="ready" if key == current_change_id else "superseded"
    )
    db.scalar.return_value = current
    assert conversations._rewrite_proposal_source(db, old) is current
