from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from casepilot_api import knowledge
from casepilot_api.schemas import WorkspaceStateUpdate


def document():
    return SimpleNamespace(
        id=uuid4(),
        source_id=uuid4(),
        expires_at=None,
        storage_key="original.txt",
        original_name="需求.txt",
    )


def test_files_view_can_be_saved():
    assert WorkspaceStateUpdate(active_view="files").active_view == "files"


@pytest.mark.parametrize(
    "action", [knowledge.download_knowledge_document, knowledge.preview_knowledge_document]
)
def test_document_requires_source_membership(monkeypatch, action):
    doc = document()
    db = Mock()
    db.get.return_value = doc
    check = Mock(side_effect=HTTPException(status_code=403))
    monkeypatch.setattr(knowledge, "_get_source", check)
    account = SimpleNamespace(id=uuid4())
    with pytest.raises(HTTPException) as error:
        action(doc.id, account, db)
    assert error.value.status_code == 403
    check.assert_called_once_with(db, account.id, doc.source_id)
    db.scalars.assert_not_called()


def test_expired_document_is_not_accessible(monkeypatch):
    doc = document()
    doc.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db = Mock()
    db.get.return_value = doc
    monkeypatch.setattr(knowledge, "_get_source", Mock())
    with pytest.raises(HTTPException) as error:
        knowledge._get_document(db, uuid4(), doc.id)
    assert error.value.status_code == 410


def test_download_returns_original_and_rejects_missing_file(monkeypatch, tmp_path):
    doc = document()
    monkeypatch.setattr(knowledge, "_get_document", Mock(return_value=doc))
    monkeypatch.setattr(
        knowledge, "settings", SimpleNamespace(knowledge_storage_path=str(tmp_path))
    )
    (tmp_path / doc.storage_key).write_text("original content")
    response = knowledge.download_knowledge_document(doc.id, SimpleNamespace(id=uuid4()), Mock())
    assert response.filename == "需求.txt"
    assert response.path.read_text() == "original content"
    assert response.headers["cache-control"] == "private, no-store"
    (tmp_path / doc.storage_key).unlink()
    with pytest.raises(HTTPException) as error:
        knowledge.download_knowledge_document(doc.id, SimpleNamespace(id=uuid4()), Mock())
    assert error.value.status_code == 404


def test_preview_is_bounded(monkeypatch):
    doc = document()
    monkeypatch.setattr(knowledge, "_get_document", Mock(return_value=doc))
    db = Mock()
    db.scalars.return_value.all.return_value = ["x" * 2000] * 101
    result = knowledge.preview_knowledge_document(doc.id, SimpleNamespace(id=uuid4()), db)
    assert len(result["content"]) == 100_000
    assert result["truncated"] is True
