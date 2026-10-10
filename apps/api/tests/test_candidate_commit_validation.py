"""Regression coverage for persisted candidates with oversized evidence excerpts."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from casepilot_api import conversations
from casepilot_api.schemas import SourceRefInput, WorkspaceCandidateCommitRequest


@pytest.mark.parametrize("length", [0, 3999, 4000, 4001, 12000])
def test_candidate_excerpt_preview_preserves_reference_and_original(length):
    ref = {
        "source_id": str(uuid4()), "document_id": str(uuid4()), "chunk_id": str(uuid4()),
        "label": "需求", "locator": "第 8 节", "excerpt": ("中🙂" * length)[:length],
    }
    snapshot = {"source_refs": [ref]}
    original = deepcopy(snapshot)
    normalized = conversations._candidate_source_refs(snapshot)
    assert normalized == [{**ref, "excerpt": ref["excerpt"][:4000]}]
    SourceRefInput.model_validate(normalized[0])
    assert snapshot == original
    if length > 4000:
        # Manual case inputs retain their existing strict validation contract.
        with pytest.raises(ValidationError):
            SourceRefInput.model_validate(ref)


@pytest.mark.parametrize("invalid_last", [False, True])
def test_commit_160_candidates_validates_whole_batch_before_writing(monkeypatch, invalid_last):
    conversation = SimpleNamespace(id=uuid4(), collection_id=uuid4(), context={})
    candidates = [
        SimpleNamespace(
            id=uuid4(), generation_job_id=uuid4(), ref=f"TC-{i}", status="candidate",
            snapshot={
                "title": f"候选 {i}",
                "steps": [{"action": "执行操作", "expected": "符合需求"}],
                "source_refs": [{"label": "需求", "excerpt": "摘" * (5000 if i == 159 else 50)}],
            },
        )
        for i in range(160)
    ]
    if invalid_last:
        candidates[-1].snapshot["steps"] = []
    originals = deepcopy([item.snapshot for item in candidates])
    db = Mock()
    db.scalars.side_effect = [candidates, [], []]
    db.scalar.side_effect = [None, None]
    monkeypatch.setattr(conversations, "_ensure_conversation", lambda *args: conversation)
    monkeypatch.setattr(conversations, "_require_idle_conversation", lambda *args: None)
    monkeypatch.setattr(conversations, "ensure_collection", lambda *args: SimpleNamespace())
    create = Mock(side_effect=lambda *args, **kwargs: SimpleNamespace(id=uuid4()))
    monkeypatch.setattr(conversations, "create_test_case_record", create)
    monkeypatch.setattr(conversations, "case_to_view", lambda db, case: case)
    monkeypatch.setattr(
        conversations, "TestCaseView", SimpleNamespace(model_validate=lambda case: case)
    )
    args = (conversation.id, WorkspaceCandidateCommitRequest(), SimpleNamespace(id=uuid4()), db)
    if invalid_last:
        with pytest.raises(HTTPException) as caught:
            conversations.commit_workspace_candidates(*args)
        assert caught.value.status_code == 422
        assert caught.value.detail == "invalid_workspace_candidate"
        create.assert_not_called()
        db.commit.assert_not_called()
        assert all(item.status == "candidate" for item in candidates)
    else:
        result = conversations.commit_workspace_candidates(*args)
        assert len(result) == create.call_count == 160
        assert len(create.call_args_list[-1].kwargs["payload"].source_refs[0].excerpt) == 4000
        assert len(create.call_args_list[0].kwargs["payload"].source_refs[0].excerpt) == 50
        assert all(item.status == "incorporated" for item in candidates)
        db.commit.assert_called_once()
    assert [item.snapshot for item in candidates] == originals


def test_edit_legacy_candidate_with_long_excerpt(monkeypatch):
    from casepilot_api.schemas import WorkspaceCandidateUpdate

    snapshot = {
        "title": "修改标题", "steps": [{"action": "执行", "expected": "成功"}],
        "source_refs": [{"label": "需求", "locator": "第 8 节", "excerpt": "摘" * 5000}],
    }
    candidate = SimpleNamespace(
        id=uuid4(), conversation_id=uuid4(), status="candidate", version=1,
    )
    db = Mock()
    db.scalar.return_value = candidate
    monkeypatch.setattr(conversations, "_ensure_conversation", lambda *args: None)
    monkeypatch.setattr(conversations, "_candidate_view", lambda item: item)
    conversations.update_workspace_candidate(
        candidate.id, WorkspaceCandidateUpdate(base_version=1, snapshot=snapshot),
        SimpleNamespace(id=uuid4()), db,
    )
    assert candidate.version == 2
    assert candidate.snapshot["title"] == "修改标题"
    assert candidate.snapshot["source_refs"] == [
        {"source_id": None, "document_id": None, "chunk_id": None,
         "label": "需求", "locator": "第 8 节", "excerpt": "摘" * 4000},
    ]
    assert len(snapshot["source_refs"][0]["excerpt"]) == 5000
    db.commit.assert_called_once()
