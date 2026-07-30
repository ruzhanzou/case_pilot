from contextlib import contextmanager
from uuid import uuid4

from casepilot_agent.contracts import GenerationRequest
from casepilot_agent.pipeline import GenerationPipeline
from casepilot_agent.providers.mock import MockProvider
from casepilot_agent.tasks import (
    _apply_persisted_asset_quality,
    _context_payload,
)


class FailingEmbeddingProvider:
    @property
    def name(self) -> str:
        return "failing:embedding"

    def embed(self, texts: list[str]) -> list[list[float]]:
        del texts
        raise RuntimeError("embedding_unavailable")


class FakeStore:
    def __init__(self, existing: list[dict] | None = None) -> None:
        self.existing = existing or []
        self.query_embedding: list[float] | None = []
        self.recorded_stage: dict = {}
        self.events: list[dict] = []

    @contextmanager
    def connection(self):
        yield object()

    def load_completed_stage(self, *args, **kwargs):
        return None

    def retrieve_context(self, *args, **kwargs):
        self.query_embedding = kwargs["query_embedding"]
        return []

    def persist_evidence(self, *args, **kwargs) -> None:
        return None

    def record_stage(self, *args, **kwargs) -> None:
        self.recorded_stage = kwargs

    def update_job(self, *args, **kwargs) -> None:
        return None

    def publish(self, job_id, event) -> None:
        del job_id
        self.events.append(event)

    def load_existing_case_titles(self, *args, **kwargs):
        return self.existing


def job(*, use_space_knowledge: bool = True) -> dict:
    return {
        "id": uuid4(),
        "space_id": uuid4(),
        "collection_id": uuid4(),
        "input_payload": {
            "prompt": "支付失败返回 E1001",
            "markdown_content": "",
            "knowledge_source_ids": [],
            "document_ids": [],
            "use_space_knowledge": use_space_knowledge,
        },
    }


def test_context_falls_back_to_lexical_retrieval_when_embedding_fails(
    monkeypatch,
) -> None:
    from casepilot_agent import tasks

    monkeypatch.setattr(tasks.settings, "embedding_fallback_enabled", True)
    store = FakeStore()

    output = _context_payload(store, job(), FailingEmbeddingProvider())

    assert output["retrieval_mode"] == "lexical"
    assert output["warnings"][0]["code"] == "embedding_retrieval_degraded"
    assert store.query_embedding is None
    assert store.recorded_stage["status"] == "completed"
    assert store.events[0]["retrieval_mode"] == "lexical"


def test_context_skips_embedding_when_knowledge_retrieval_is_disabled(
    monkeypatch,
) -> None:
    from casepilot_agent import tasks

    monkeypatch.setattr(tasks.settings, "embedding_fallback_enabled", True)
    store = FakeStore()

    output = _context_payload(
        store,
        job(use_space_knowledge=False),
        FailingEmbeddingProvider(),
    )

    assert output["retrieval_mode"] == "none"
    assert output["warnings"] == []


def test_quality_keeps_exact_dedup_and_warns_when_semantic_dedup_degrades(
    monkeypatch,
) -> None:
    from casepilot_agent import tasks

    monkeypatch.setattr(tasks.settings, "embedding_fallback_enabled", True)
    result = MockProvider().generate(GenerationRequest(prompt="支付需求"))
    existing_title = result.test_cases[0].title
    store = FakeStore(
        existing=[{"case_key": "CASE-001", "title": existing_title}]
    )

    _apply_persisted_asset_quality(
        store,
        job(),
        FailingEmbeddingProvider(),
        {"evidence": [], "warnings": []},
        result,
    )

    issue_codes = {issue.code for issue in result.quality.issues}
    assert "possible_existing_case_duplicate" in issue_codes
    assert "semantic_duplicate_check_degraded" in issue_codes
    assert result.quality.passed


def test_generation_completes_end_to_end_with_embedding_degraded(
    monkeypatch,
) -> None:
    from casepilot_agent import tasks

    monkeypatch.setattr(tasks.settings, "embedding_fallback_enabled", True)
    store = FakeStore()
    current_job = job()
    context = _context_payload(
        store,
        current_job,
        FailingEmbeddingProvider(),
    )
    llm = MockProvider()

    def execute(stage, instruction, payload, result_type, model_id):
        return llm.complete(
            stage=stage,
            instruction=instruction,
            payload=payload,
            result_type=result_type,
            model_id=model_id,
        )[0]

    result = GenerationPipeline(llm).run(
        GenerationRequest(prompt="支付状态查询和幂等回调"),
        context=context,
        answers={},
        execute_stage=execute,
    )
    _apply_persisted_asset_quality(
        store,
        current_job,
        FailingEmbeddingProvider(),
        context,
        result,
    )

    assert result.feature_points
    assert result.test_points
    assert result.test_cases
    assert result.quality.passed
    assert {
        issue.code for issue in result.quality.issues
    } >= {"embedding_retrieval_degraded"}
