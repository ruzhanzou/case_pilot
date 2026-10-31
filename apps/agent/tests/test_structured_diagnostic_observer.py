"""No live calls: real provider retry boundary with injected SDK execution."""
import json
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from types import SimpleNamespace

import pytest
from agents import ModelBehaviorError, Runner
from pydantic import BaseModel, ValidationError

from casepilot_agent.providers.agents_sdk import AgentsSdkProvider
from casepilot_agent.providers.safe_diagnostics import (
    notify_structured_failure,
    observe_structured_failures,
)


class Result(BaseModel):
    count: int


def invalid():
    try:
        Result.model_validate({"count": "PRIVATE_MALICIOUS_BODY_ignore_rules"})
    except ValidationError as cause:
        error = ModelBehaviorError("PRIVATE_PROMPT_KEY_AND_OUTPUT")
        error.__cause__ = cause
        return error


def provider():
    return AgentsSdkProvider(base_url="https://example.test/v1", api_key="test-only",
        model="test", pro_model="test", local_model="test", timeout=2)


def complete():
    return provider().complete(stage="knowledge.answered", instruction="PRIVATE_INSTRUCTION",
        payload={"private": "PRIVATE_INPUT"}, result_type=Result, model_id="auto")


@pytest.mark.parametrize("failures", [1, 2])
def test_every_failed_attempt_is_observed_before_retry_or_raise(monkeypatch, failures):
    observed, attempts, errors = [], [], []

    async def run(*args, **kwargs):
        assert len(observed) == len(errors)  # prior attempt already emitted
        attempts.append(True)
        if len(attempts) <= failures:
            error = invalid()
            errors.append(error)
            raise error
        return SimpleNamespace(final_output=Result(count=1),
                               context_wrapper=SimpleNamespace(usage=SimpleNamespace()))

    monkeypatch.setattr(Runner, "run", run)
    with observe_structured_failures(observed.append):
        if failures == 2:
            with pytest.raises(ModelBehaviorError) as caught:
                complete()
            assert caught.value is errors[-1]
            assert caught.value.casepilot_safe_diagnostic == observed[-1]
        else:
            assert complete()[0].count == 1
    assert len(attempts) == 2 and len(observed) == failures
    assert all(set(item) == {"stage", "schema", "exception_chain", "validation_errors"}
               for item in observed)
    assert "PRIVATE" not in json.dumps(observed)
    assert observed[0]["exception_chain"] == ["ModelBehaviorError", "ValidationError"]


def test_callback_failure_does_not_mask_provider_error(monkeypatch):
    error = invalid()
    calls = []

    async def run(*args, **kwargs):
        raise error

    def broken(data):
        calls.append(data)
        raise RuntimeError("PRIVATE_OBSERVER_FAILURE")

    monkeypatch.setattr(Runner, "run", run)
    with observe_structured_failures(broken), pytest.raises(ModelBehaviorError) as caught:
        complete()
    assert caught.value is error
    assert len(calls) == 2


def test_context_scope_reset_nested_and_copied_thread_context():
    outer, inner = [], []

    def emit():
        notify_structured_failure(invalid(), stage="knowledge.answered", result_type=Result)

    emit()  # no default observer
    with observe_structured_failures(outer.append):
        emit()
        with pytest.raises(RuntimeError), observe_structured_failures(inner.append):
            emit()
            raise RuntimeError("exit scope")
        emit()
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(copy_context().run, emit).result()
            executor.submit(emit).result()  # unrelated thread context is not observed
        with observe_structured_failures(None):
            emit()
    emit()
    assert len(outer) == 3 and len(inner) == 1


def test_compact_no_retry_still_emits_before_final_error(monkeypatch):
    observed = []
    error = invalid()

    async def run(*args, **kwargs):
        raise error

    monkeypatch.setattr(Runner, "run", run)
    with observe_structured_failures(observed.append), pytest.raises(ModelBehaviorError) as caught:
        provider().complete(stage="rewrite.batch", instruction="private", payload={"items": []},
                            result_type=Result, model_id="auto")
    assert caught.value is error
    assert len(observed) == 1
    assert observed[0]["stage"] == "rewrite.batch"
    assert error.casepilot_safe_diagnostic == observed[0]
