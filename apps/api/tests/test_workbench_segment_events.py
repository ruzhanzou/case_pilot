"""Actual Redis fencing/replay and real SDK event-budget proof; no live providers."""
import json
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError

from casepilot_api.workbench_agent import FinalAnswer, ModelTurn, ToolCall, ToolSpec, WorkbenchAgent
from casepilot_api.workbench_events import (
    WorkbenchEventStore,
    reserved_segment_base,
    segment_event_bound,
)
from casepilot_api.workbench_tools import NoArguments


@pytest.fixture
def channel():
    store = WorkbenchEventStore(uuid4(), uuid4(), uuid4())
    yield store
    store.client.delete(*(store.key + suffix for suffix in (
        ":events", ":segment", ":sequences", ":terminal", ":cancel")))
    store.client.close()


def test_two_segments_reconnect_dedup_late_terminal_and_expiry(channel):
    first = reserved_segment_base({"model_turns": 8, "tool_calls": 16, "segments": 1}, 8, 16)
    second = reserved_segment_base({"model_turns": 16, "tool_calls": 32, "segments": 2}, 8, 16)
    assert first == 0 and second == segment_event_bound(8, 16)
    assert channel.publish({"sequence": 1, "type": "run_started"}, segment_base=first)
    assert channel.publish({"sequence": 3, "type": "run_completed"}, segment_base=first)
    assert channel.is_terminal()
    start = {"sequence": second + 1, "type": "run_started"}
    assert channel.publish(start, segment_base=second)
    assert not channel.is_terminal()
    assert not channel.publish({"sequence": 4, "type": "run_failed"}, segment_base=first)
    assert not channel.publish({"sequence": 1, "type": "run_started"}, segment_base=first)
    completed = {"sequence": second + 2, "type": "tool_completed", "tool": "query_assets"}
    assert channel.publish(completed, segment_base=second)
    assert channel.publish(completed, segment_base=second)
    assert not channel.publish({**completed, "tool": "query_candidates"}, segment_base=second)
    terminal = {"sequence": second + 3, "type": "run_completed"}
    assert channel.publish(terminal, segment_base=second)
    assert channel.publish(start, segment_base=second)  # Replay cannot reopen terminal segment.
    assert channel.is_terminal()
    assert channel.read(3) == [start, completed, terminal]
    assert channel.read(second + 1) == [completed, terminal]
    # Human review may outlive Redis TTL; the durable reservation base cannot reset.
    channel.client.delete(*(channel.key + suffix for suffix in (
        ":events", ":segment", ":sequences", ":terminal")))
    third = reserved_segment_base({"model_turns": 24, "tool_calls": 48, "segments": 3}, 8, 16)
    assert channel.publish({"sequence": third + 1, "type": "run_started"}, segment_base=third)
    assert channel.read(second + 3) == [{"sequence": third + 1, "type": "run_started"}]


def test_maximum_configured_segment_budget_is_bounded_even_with_correction():
    class Provider:
        count = 0

        def complete(self, messages, tools, instructions):
            self.count += 1
            if self.count <= 18:
                return ModelTurn(calls=[ToolCall(f"{self.count}-{i}", "query", "{}")
                                        for i in range(2)])
            receipts = [json.loads(item["output"])["_receipt"]["id"] for item in messages
                        if item.get("type") == "function_call_output"]
            return ModelTurn(final=FinalAnswer(kind="action", message="Actual read", effect="read",
                receipt_ids=["invalid" if self.count == 19 else receipts[-1]]))

    result = WorkbenchAgent(Provider(), [ToolSpec("query", "Read", NoArguments,
        lambda _: {"status": "completed"})], max_turns=20, max_tool_calls=40).run(
            [{"role": "user", "content": "read"}], "Read")
    assert result.status == "completed"
    assert any(event["type"] == "final_correction" for event in result.events)
    assert len(result.events) + 1 <= segment_event_bound(20, 40)

    class ToolsOnly:
        count = 0

        def complete(self, messages, tools, instructions):
            self.count += 1
            return ModelTurn(calls=[ToolCall(f"limit-{self.count}-{i}", "query", "{}")
                                    for i in range(2)])

    limited = WorkbenchAgent(ToolsOnly(), [ToolSpec("query", "Read", NoArguments,
        lambda _: {"status": "completed"})], max_turns=20, max_tool_calls=40).run(
            [{"role": "user", "content": "read"}], "Read")
    assert limited.error_code == "agent_turn_budget_exhausted"
    assert sum(event["type"] == "tool_completed" for event in limited.events) == 40
    assert len(limited.events) + 1 <= segment_event_bound(20, 40)
    last = reserved_segment_base({"model_turns": 160, "tool_calls": 320, "segments": 8}, 20, 40)
    assert last + segment_event_bound(20, 40) == 832 < 1000
    rejected = WorkbenchAgent(Provider(), [], max_turns=20, max_tool_calls=40).run(
        [{"role": "user", "content": "read"}], "Read", reserve_budget=lambda amounts: False)
    assert rejected.error_code == "agent_cumulative_budget_exhausted"
    assert len(rejected.events) + 1 <= segment_event_bound(20, 40)
    with pytest.raises(ValueError, match="event_budget"):
        reserved_segment_base({"model_turns": 1000, "tool_calls": 1000, "segments": 8}, 20, 40)


def test_redis_segment_failure_is_non_authoritative():
    class Broken:
        def eval(self, *args):
            raise ConnectionError("unavailable")

    store = WorkbenchEventStore(uuid4(), uuid4(), uuid4(), client=Broken())
    assert not store.publish({"sequence": 1, "type": "run_started"}, segment_base=0)
