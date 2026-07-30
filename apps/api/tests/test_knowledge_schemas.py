from uuid import uuid4

import pytest
from pydantic import ValidationError

from casepilot_api.knowledge import _signature_matches
from casepilot_api.schemas import GenerationAnswersRequest, GenerationStartRequest


def test_upload_signature_validation_rejects_extension_spoofing() -> None:
    assert _signature_matches(".pdf", b"%PDF-1.7\n")
    assert _signature_matches(".docx", b"PK\x03\x04archive")
    assert _signature_matches(".png", b"\x89PNG\r\n\x1a\n")
    assert not _signature_matches(".pdf", b"not-a-pdf")
    assert not _signature_matches(".png", b"%PDF-1.7")


def test_generation_request_supports_scoped_knowledge_and_temporary_documents() -> None:
    source_id = uuid4()
    document_id = uuid4()
    request = GenerationStartRequest.model_validate(
        {
            "prompt": "支付需求",
            "collection_id": uuid4(),
            "knowledge_source_ids": [source_id],
            "document_ids": [document_id],
            "use_space_knowledge": False,
        }
    )
    assert request.knowledge_source_ids == [source_id]
    assert request.document_ids == [document_id]
    assert not request.use_space_knowledge


def test_generation_answers_require_non_empty_answer() -> None:
    with pytest.raises(ValidationError):
        GenerationAnswersRequest.model_validate(
            {"answers": [{"question_id": "Q-1", "answer": ""}]}
        )
