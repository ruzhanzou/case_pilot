from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from casepilot_agent.providers.agents_sdk import AgentsSdkProvider
from casepilot_agent import config, tasks


def test_image_prompt_keeps_text_and_original_image_together(monkeypatch):
    provider = AgentsSdkProvider(base_url='http://unused', api_key='test', model='vision', pro_model='text', local_model='text', timeout=1)
    monkeypatch.setattr(config, 'get_settings', lambda: SimpleNamespace(image_models='vision'))
    assert provider._image_prompt('hello', 'text') == 'hello'
    image = {'type': 'input_image', 'detail': 'auto', 'image_url': 'data:image/png;base64,aGVsbG8='}
    provider.image_inputs = [image]
    result = provider._image_prompt('explain screenshot', 'vision')
    assert result == [{'role': 'user', 'content': [{'type': 'input_text', 'text': 'explain screenshot'}, image]}]
    with pytest.raises(ValueError, match='model_does_not_support_images'):
        provider._image_prompt('hello', 'text')


def test_bind_job_images_preserves_request_order_and_clears_previous_state(
    monkeypatch, tmp_path
):
    first_id, second_id = uuid4(), uuid4()
    (tmp_path / "first.png").write_bytes(b"first")
    (tmp_path / "second.jpg").write_bytes(b"second")
    documents = [
        {
            "id": second_id,
            "mime_type": "image/jpeg",
            "size_bytes": 6,
            "storage_key": "second.jpg",
        },
        {
            "id": first_id,
            "mime_type": "image/png",
            "size_bytes": 5,
            "storage_key": "first.png",
        },
    ]

    class Result:
        def mappings(self):
            return self

        def all(self):
            return documents

    class Store:
        @contextmanager
        def connection(self):
            yield SimpleNamespace(execute=lambda _: Result())

    provider = SimpleNamespace(image_inputs=[{"stale": True}])
    monkeypatch.setattr(
        tasks,
        "settings",
        SimpleNamespace(
            knowledge_storage_path=str(tmp_path), image_max_total_bytes=20
        ),
    )
    job = {
        "space_id": uuid4(),
        "input_payload": {"document_ids": [str(first_id), str(second_id)]},
    }
    tasks.bind_job_images(provider, Store(), job)
    assert [item["image_url"].split(";", 1)[0] for item in provider.image_inputs] == [
        "data:image/png",
        "data:image/jpeg",
    ]

    tasks.bind_job_images(
        provider, Store(), {"space_id": uuid4(), "input_payload": {}}
    )
    assert provider.image_inputs == []
