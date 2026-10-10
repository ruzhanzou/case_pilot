from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from casepilot_agent import tasks


def test_temporary_attachment_is_readable_without_remote_embeddings(monkeypatch, tmp_path):
    source_id = uuid4()
    path = tmp_path / "login.txt"
    path.write_text("Valid credentials open the account home page.")
    chunks = []
    updates = []

    class Store:
        def __init__(self, *_):
            pass

        @contextmanager
        def connection(self):
            yield SimpleNamespace(scalar=lambda _: source_id)

        def get_source(self, *_):
            return {"persistence": "temporary"}

        def get_source_documents(self, *_):
            return [{"id": uuid4(), "storage_key": path.name,
                     "original_name": path.name, "mime_type": "text/plain"}]

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
