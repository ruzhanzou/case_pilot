from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image
from casepilot_agent import tasks


@pytest.mark.parametrize("image", [False, True])
def test_temporary_attachment_is_readable_without_remote_embeddings(monkeypatch, tmp_path, image):
    source_id = uuid4()
    path = tmp_path / "login.txt"
    path.write_text("Valid credentials open the account home page.")
    if image:
        path = tmp_path / "screenshot.png"
        Image.new("RGB", (20, 20), "white").save(path)
        monkeypatch.setattr(tasks, "parse_document", lambda *_: pytest.fail("Images must not require OCR"))
    chunks = []
    updates = []

    class Store:
        def __init__(self, *_):
            pass

        @contextmanager
        def execution_guard(self, source_id):
            yield True

        @contextmanager
        def connection(self):
            yield SimpleNamespace(scalar=lambda _: source_id)

        def get_source(self, *_):
            return {"persistence": "temporary"}

        def get_source_documents(self, *_):
            return [{"id": uuid4(), "storage_key": path.name,
                     "original_name": path.name, "mime_type": "image/png" if image else "text/plain"}]

        def update_document(self, *_, **values):
            updates.append(values)

        def replace_document_chunks(self, _, __, values):
            chunks.extend(values)

        def update_source(self, *_, **values):
            updates.append(values)

    def no_remote_call():
        raise AssertionError("Explicit attachments must not wait for embeddings")

    monkeypatch.setattr(tasks, "JobStore", Store)
    monkeypatch.setattr(tasks, "create_embedding_provider", no_remote_call)
    monkeypatch.setattr(tasks, "settings", SimpleNamespace(
        database_url="unused", redis_url="unused", knowledge_storage_path=str(tmp_path),
        embedding_fallback_enabled=False,
    ))
    result = tasks.index_knowledge_source(str(source_id))
    assert result["status"] == "ready"
    assert result["retrieval_mode"] == "lexical"
    assert any(item["chunk_type"] == "parent" for item in chunks)
    assert updates[-1] == {"status": "ready", "error_code": None}


def test_bad_file_does_not_prevent_later_valid_sibling_from_being_indexed(monkeypatch, tmp_path):
    source_id = uuid4()
    documents = []
    for name, content in [('empty.txt', ''), ('rules.txt', 'Current rule: expired code returns E731.')]:
        (tmp_path/name).write_text(content)
        documents.append({'id': uuid4(), 'storage_key': name, 'original_name': name,
                          'mime_type': 'text/plain', 'status': 'uploaded', 'error_code': None})
    source = {'persistence': 'temporary', 'status': 'uploaded'}
    indexed = []

    class Store:
        def __init__(self, *_): pass
        @contextmanager
        def execution_guard(self, _): yield True
        @contextmanager
        def connection(self): yield SimpleNamespace(scalar=lambda _: source_id)
        def get_source(self, *_): return source
        def get_source_documents(self, *_): return documents
        def update_source(self, *_, **values): source.update(values)
        def update_document(self, _, document_id, **values):
            next(d for d in documents if d['id'] == document_id).update(values)
        def replace_document_chunks(self, _, document, chunks):
            assert any('E731' in chunk['content'] for chunk in chunks)
            indexed.append(document['original_name'])

    monkeypatch.setattr(tasks, 'JobStore', Store)
    monkeypatch.setattr(tasks, 'settings', SimpleNamespace(database_url='unused', redis_url='unused',
        knowledge_storage_path=str(tmp_path), embedding_fallback_enabled=False))
    result = tasks.index_knowledge_source(str(source_id))
    assert result['status'] == 'failed'
    assert result['failed_document_count'] == 1
    assert indexed == ['rules.txt']
    assert documents[0]['status'] == 'failed'
    assert documents[0]['error_code'] == 'DocumentTextUnavailable'
    assert documents[1]['status'] == 'ready'
    assert documents[1]['error_code'] is None
    assert source['error_code'] == 'attachment_batch_partial_failure'
