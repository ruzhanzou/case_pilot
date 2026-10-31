"""QA integration boundary contracts without services or live providers."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
import workbench_agent_live_journey as journey
from workbench_agent_live_acceptance import RequestBudget
from workbench_request_continuation import NaturalDurableJourney, RequestWorkerDispatch


@pytest.mark.asyncio
async def test_natural_execute_keeps_real_outbox_and_single_shared_http_budget(
    monkeypatch, tmp_path
):
    from casepilot_api import conversations, knowledge

    original = conversations.enqueue_task, knowledge.enqueue_task
    budget = RequestBudget(60)
    entered = []

    @asynccontextmanager
    async def bounded(key, actual):
        assert actual is budget and actual.limit == 60
        entered.append(actual)
        yield

    async def run(self, scenarios):
        assert scenarios == {"natural_selection"}
        assert isinstance(self.dispatch, RequestWorkerDispatch)
        assert self.dispatch.journey is self
        assert (conversations.enqueue_task, knowledge.enqueue_task) == original

    monkeypatch.setattr(journey, "bounded_clients", bounded)
    monkeypatch.setattr(NaturalDurableJourney, "run", run)
    await journey.execute(
        "offline-placeholder",
        "offline-model",
        budget,
        {"natural_selection"},
        {},
        str(tmp_path),
    )
    assert entered == [budget] and budget.count == 0


def test_original_natural_prompts_and_preview_oracles_are_inherited():
    assert NaturalDurableJourney.natural_selection is journey.Journey.natural_selection
    assert NaturalDurableJourney.scoped_preview is journey.Journey.scoped_preview
    assert NaturalDurableJourney.selected_preview is journey.Journey.selected_preview


@pytest.mark.asyncio
async def test_applied_boundary_does_not_accept_current_invalidated_run(monkeypatch):
    from types import SimpleNamespace

    runner = object.__new__(NaturalDurableJourney)
    runner.tasks = object()
    runner.report = {}
    runner.current_request = SimpleNamespace(
        advance=AsyncMock(), state=lambda: {"status": "invalidated"}
    )
    monkeypatch.setattr(
        journey.Journey, "apply_selected", AsyncMock(return_value=("case", "state"))
    )
    with pytest.raises(journey.JourneyFailure, match="durable_apply_not_terminal"):
        await runner.apply_selected()
    runner.current_request.advance.assert_awaited_once_with(runner.tasks, "applied")
