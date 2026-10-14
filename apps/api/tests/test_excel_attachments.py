from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from casepilot_api import conversations
from casepilot_api.knowledge import _store_uploads


@pytest.mark.parametrize(
    ("name", "mime"),
    [
        ("需求.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("需求.xls", "application/vnd.ms-excel"),
        ("需求.XLSX", "application/octet-stream"),
        ("需求.xls", ""),
        ("需求.pdf", "application/pdf"),
        ("需求.txt", "text/plain"),
    ],
)
def test_conversation_accepts_excel_and_binds_uploaded_documents(monkeypatch, name, mime):
    conversation = SimpleNamespace(id=uuid4(), space_id=uuid4(), title="需求", context={})
    result = SimpleNamespace(source=SimpleNamespace(id=uuid4()), document_ids=[uuid4()])
    store = Mock(return_value=result)
    monkeypatch.setattr(conversations, "_ensure_conversation", Mock(return_value=conversation))
    monkeypatch.setattr(conversations, "_store_uploads", store)
    account, db = SimpleNamespace(id=uuid4()), Mock()
    files = [
        UploadFile(BytesIO(b"content"), filename=name, headers=Headers({"content-type": mime}))
    ]
    assert (
        conversations.upload_conversation_attachments(conversation.id, account, db, files) is result
    )
    assert conversation.context["document_ids"] == [str(result.document_ids[0])]
    assert conversation.context["knowledge_source_ids"] == [str(result.source.id)]
    assert store.call_args.args[-1] == "temporary"


@pytest.mark.parametrize(
    ("name", "mime"),
    [("macro.xlsm", "application/octet-stream"), ("bad.xlsx", "text/html")],
)
def test_conversation_rejects_unsupported_excel_uploads(monkeypatch, name, mime):
    monkeypatch.setattr(conversations, "_ensure_conversation", Mock())
    upload = UploadFile(BytesIO(b"content"), filename=name, headers=Headers({"content-type": mime}))
    with pytest.raises(HTTPException) as error:
        conversations.upload_conversation_attachments(
            uuid4(), SimpleNamespace(id=uuid4()), Mock(), [upload]
        )
    assert error.value.status_code == 415


@pytest.mark.parametrize("extension", ["xls", "xlsx"])
def test_excel_signature_is_checked_before_storage(extension):
    db = Mock()
    upload = UploadFile(BytesIO(b"not an Excel workbook"), filename=f"bad.{extension}")
    with pytest.raises(HTTPException) as error:
        _store_uploads(db, uuid4(), uuid4(), "资料", [upload], "temporary")
    assert error.value.detail == "document_signature_mismatch"
    db.add.assert_not_called()
