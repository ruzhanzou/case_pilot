"""Real parallel planning preserves scoped observers without sharing Context objects."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from threading import Barrier, Event, Lock

import pytest
from test_parallel_planning import features, points

from casepilot_agent.contracts import RequirementAnalysis
from casepilot_agent.planning import analyze_batches, build_planning
from casepilot_agent.providers.safe_diagnostics import (
    notify_structured_failure,
    observe_structured_failures,
)

_SCOPE = ContextVar("test_planning_scope", default="outside")
_BUDGET = ContextVar("test_planning_budget")
_CANCEL = ContextVar("test_planning_cancel")


def notify(stage):
    notify_structured_failure(ValueError("PRIVATE_BODY"), stage=stage,
                              result_type=RequirementAnalysis)


def test_two_parallel_runs_keep_observers_budget_and_cancel_contexts_separate():
    barrier = Barrier(4, timeout=5)

    def run(label):
        observed, saved = [], []
        budget = {"remaining": 2, "lock": Lock()}
        cancelled = Event()
        tokens = (_SCOPE.set(label), _BUDGET.set(budget), _CANCEL.set(cancelled))

        def check():
            assert _SCOPE.get() == label
            assert _BUDGET.get() is budget
            assert _CANCEL.get() is cancelled
            if cancelled.is_set():
                raise RuntimeError("cancelled")

        def complete(index, batch):
            check()
            barrier.wait()
            with _BUDGET.get()["lock"]:
                assert _BUDGET.get()["remaining"] > 0
                _BUDGET.get()["remaining"] -= 1
            notify(label)
            _SCOPE.set("worker-local")  # must not leak to sibling/copied Context
            return index

        try:
            with observe_structured_failures(observed.append):
                result = analyze_batches([{}, {}], complete, load=lambda *a: None,
                    save=lambda *a: saved.append(_SCOPE.get()), on_progress=lambda *a: None,
                    check_cancelled=check, concurrency=2)
            assert result == [0, 1]
            assert saved == [label, label]
            assert budget["remaining"] == 0
            assert [item["stage"] for item in observed] == [label, label]
            return observed
        finally:
            _SCOPE.reset(tokens[0])
            _BUDGET.reset(tokens[1])
            _CANCEL.reset(tokens[2])

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(run, "first_run"), pool.submit(run, "second_run")
        assert len(first.result()) == len(second.result()) == 2
    assert _SCOPE.get() == "outside"


def test_actual_point_planning_threads_observe_context_and_isolate_worker_changes():
    barrier = Barrier(3, timeout=5)
    observed = []
    token = _SCOPE.set("planning_run")

    def complete(stage, instruction, payload, result_type):
        assert _SCOPE.get() == "planning_run"
        notify(stage)
        if stage == "feature.generated":
            return features(9)
        barrier.wait()
        _SCOPE.set("private_worker_change")
        return points(payload)

    try:
        with observe_structured_failures(observed.append):
            result = build_planning(
                RequirementAnalysis(summary="Login"),
                {"user_input": "Synthetic login rules for nine feature groups."}, complete,
            )
        assert len(result["test_points"]) == 9
        assert [item["stage"] for item in observed].count("feature.generated") == 1
        assert [item["stage"] for item in observed].count("test_point.generated") == 3
        assert _SCOPE.get() == "planning_run"
    finally:
        _SCOPE.reset(token)


def test_nested_context_failure_propagates_and_cancellation_is_not_swallowed():
    error = RuntimeError("cancelled")
    cancelled = Event()
    token = _CANCEL.set(cancelled)
    observed = []

    def check():
        if _CANCEL.get().is_set():
            raise error

    def complete(*args):
        notify("before_cancel")
        _CANCEL.get().set()
        check()

    try:
        with observe_structured_failures(observed.append), pytest.raises(RuntimeError) as caught:
            analyze_batches([{}, {}], complete, load=lambda *a: None, save=lambda *a: None,
                on_progress=lambda *a: None, check_cancelled=check, concurrency=1)
        assert caught.value is error
        assert len(observed) == 1
    finally:
        _CANCEL.reset(token)
