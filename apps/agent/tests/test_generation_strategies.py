from copy import deepcopy
from unittest.mock import Mock
from uuid import uuid4

import pytest
from test_draft_planning_progress import Store
from test_parallel_planning import features, points
from test_reuse import source

from casepilot_agent import tasks
from casepilot_agent.contracts import UsageMetadata
from casepilot_agent.reuse import AssetObjectMatches, ReuseAnalysis, match_asset_objects


@pytest.mark.parametrize(
    "mode,resume",
    [
        ("select", False),
        ("select_and_generate", False),
        ("generate", False),
        (None, False),
        ("select_and_generate", True),
        ("select_and_generate", "scoped"),
    ],
)
def test_strategy_pauses_before_planning_or_generates_without_asset_search(
    monkeypatch, mode, resume
):
    store = Store()
    store.job["space_id"] = uuid4()
    store.job["input_payload"]["generation_strategy"] = mode
    if resume:
        store.job["input_payload"].update(
            asset_selection_confirmed=True, confirmed_asset_sources=[], case_context=[]
        )
    if resume == "scoped":
        from casepilot_agent.contracts import GenerationRequest
        from casepilot_agent.providers.mock import MockProvider
        original = MockProvider().generate(GenerationRequest(prompt="account login"))
        preserved = {"feature_points": [f.model_dump(mode="json") for f in original.feature_points],
                     "test_points": [original.test_points[0].model_dump(mode="json")]}
        store.job["input_payload"]["current_test_brief"] = {"planning": deepcopy(preserved)}
    store.search_reuse_cases = Mock(
        return_value=[
            {
                "ref": str(uuid4()),
                "target_type": "formal",
                "snapshot": source()["snapshot"],
            }
        ]
    )
    if mode in {"select", "select_and_generate"} and not resume:
        store.job["input_payload"]["case_context"] = deepcopy(store.search_reuse_cases.return_value)
    store.attach_reuse_collections = lambda connection, items, **kwargs: items

    def persist(connection, job, content):
        store.briefs.append(deepcopy(content))
        return 1

    store.persist_test_brief = persist
    stages = []

    class Provider:
        def complete(self, *, stage, payload, result_type, **kwargs):
            stages.append(stage)
            if stage in {"requirement.analyzed", "requirement.extracted"}:
                if mode in {"select", "select_and_generate"} and not resume:
                    assert payload["existing_cases"] == []
                    assert payload["pending_asset_count"] == 1
                    assert "feature_points" not in result_type.model_fields
                    assert "尚未经对象匹配和用户确认" in kwargs["instruction"]
                else:
                    assert "pending_asset_count" not in payload
                result = ReuseAnalysis(
                    summary="login",
                    test_object="account system",
                    test_object_specified=True,
                    generation_strategy="regression",
                    case_search_terms=["login"],
                )
            elif stage == "reuse.objects_matched":
                result = result_type(
                    matches=[
                        {
                            "source_key": item["key"],
                            "test_object_match": "same",
                            "reason": "same account system",
                        }
                        for item in payload["sources"]
                    ]
                )
            elif stage == "feature.generated":
                assert mode in {None, "generate"} or resume, "planning started before confirmation"
                result = features(6)
            else:
                assert mode in {None, "generate"} or resume, "planning started before confirmation"
                result = points(payload, fill_budget=True)
            return result, UsageMetadata(model="mock")

    monkeypatch.setattr(tasks, "JobStore", lambda *args: store)
    monkeypatch.setattr(tasks, "create_provider", lambda *args: Provider())
    monkeypatch.setattr(tasks, "create_embedding_provider", lambda: None)
    monkeypatch.setattr(tasks, "_context_payload", lambda *args, **kwargs: {"evidence": []})
    tasks.draft_test_brief(str(store.job["id"]))
    content = store.briefs[0]
    if mode in {None, "generate"} or resume:
        store.search_reuse_cases.assert_not_called()
        assert content["planning"]["reuse"]["strategy"] == ("regression" if resume else "fresh")
        assert "reuse.objects_matched" not in stages
        if resume == "scoped":
            assert "feature.generated" not in stages and "test_point.generated" not in stages
            assert content["planning"]["test_points"] == preserved["test_points"]
        else:
            assert "test_point.generated" in stages
    else:
        assert content["planning"] == {}
        assert content["asset_selection"]["status"] == "awaiting_confirmation"
        assert len(content["asset_selection"]["sources"]) == 1
        assert "test_point.generated" not in stages


def test_object_matching_excludes_unknown_and_different_sources():
    sources = [{"key": str(i)} for i in range(3)]

    def complete(*args):
        return AssetObjectMatches(
            matches=[
                {"source_key": str(i), "test_object_match": match, "reason": match}
                for i, match in enumerate(["same", "different", "unknown"])
            ]
        )

    assert [item["key"] for item in match_asset_objects(sources, "account", complete)] == ["0"]


def test_object_matching_rejects_invented_source():
    with pytest.raises(ValueError, match="scope_invalid"):
        match_asset_objects(
            [{"key": "one"}], "account", lambda *args: AssetObjectMatches(matches=[])
        )


@pytest.mark.parametrize('count', [0, 1, 12, 13, 100])
def test_parallel_object_matching_preserves_order_and_snapshots(count):
    from threading import Lock
    from time import sleep

    sources = [{'key': str(i), 'revision': f'revision-{i}'} for i in range(count)]
    original = deepcopy(sources)
    lock, active, peak = Lock(), 0, 0

    def complete(stage, instruction, payload, result_type):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        batch = payload['sources']
        sleep(.03 if batch[0]['key'] == '0' else .001)
        with lock:
            active -= 1
        return result_type(matches=[{'source_key': item['key'],
            'test_object_match': 'same' if int(item['key']) % 3 == 0 else 'unknown',
            'reason': '明确对象证据' if int(item['key']) % 3 == 0 else '无对象证据'}
            for item in reversed(batch)])

    found = match_asset_objects(sources, '系统', complete, concurrency=2)
    assert [item['key'] for item in found] == [str(i) for i in range(count) if i % 3 == 0]
    assert sources == original
    assert peak <= 2
    if count > 12:
        assert peak == 2
    assert all(item['revision'] == f"revision-{item['key']}" for item in found)


def test_parallel_object_matching_failure_never_returns_partial_selection():
    def complete(stage, instruction, payload, result_type):
        return result_type(matches=[{'source_key': item['key'],
            'test_object_match': 'same', 'reason': 'same'}
            for item in payload['sources'] if item['key'] != '12'])

    with pytest.raises(ValueError, match='scope_invalid'):
        match_asset_objects([{'key': str(i)} for i in range(25)], '系统', complete, concurrency=2)


def test_cancelled_object_matching_does_not_start_requests():
    complete = Mock()
    def cancelled():
        raise RuntimeError('cancelled')
    with pytest.raises(RuntimeError, match='cancelled'):
        match_asset_objects([{'key': '0'}], '系统', complete, concurrency=2,
                            check_cancelled=cancelled)
    complete.assert_not_called()


def test_object_matching_retries_only_rate_limited_batch():
    import httpx
    from openai import RateLimitError
    from collections import Counter
    calls = Counter()
    def complete(stage, instruction, payload, result_type):
        key = payload['sources'][0]['key']
        calls[key] += 1
        if key == '12' and calls[key] == 1:
            raise RateLimitError('limited', response=httpx.Response(429,
                request=httpx.Request('POST', 'https://example.test')), body=None)
        return result_type(matches=[{'source_key': item['key'],
            'test_object_match': 'same', 'reason': 'same'} for item in payload['sources']])
    found = match_asset_objects([{'key': str(i)} for i in range(25)], '系统', complete, concurrency=2)
    assert len(found) == 25
    assert calls == {'0': 1, '12': 2, '24': 1}


def test_invalid_object_match_is_rejected_before_completion_checkpoint():
    saved = []
    def complete(stage, instruction, payload, result_type):
        # The real callback validates with this schema before saving the stage.
        result = result_type.model_validate({'matches': []})
        saved.append(result)
        return result
    with pytest.raises(ValueError, match='scope_invalid'):
        match_asset_objects([{'key': 'one'}], '系统', complete)
    assert saved == []


def test_duplicate_asset_identity_is_rejected_before_model_call():
    complete = Mock()
    with pytest.raises(ValueError, match='duplicate_source'):
        match_asset_objects([{'key': 'one'}, {'key': 'one'}], '系统', complete)
    complete.assert_not_called()
