from casepilot_agent.store import JobStore


class RecordingConnection:
    def __init__(self) -> None:
        self.parameters: list[dict] = []

    def execute(self, statement):
        self.parameters.append(statement.compile().params)


def test_integration_callback_uses_operation_specific_destination_and_correlation() -> None:
    connection = RecordingConnection()
    store = JobStore("postgresql+psycopg://unused", "redis://unused")
    store._queue_integration_callback(
        connection,
        {
            "input_payload": {
                "integration_callback_url": "https://caller.example.test/hooks/generation",
                "integration_callback_events": ["generation-status"],
                "integration_callback_correlation_id": "caller-job-42",
            }
        },
        "generation-status",
        "CASE-SESSION-00042",
        {"generation_status": "generating"},
    )

    assert len(connection.parameters) == 1
    callback = connection.parameters[0]
    assert callback["callback_url"] == "https://caller.example.test/hooks/generation"
    assert callback["event_type"] == "generation-status"
    assert callback["aggregate_id"] == "CASE-SESSION-00042"
    assert callback["payload"]["callback_correlation_id"] == "caller-job-42"
    assert callback["payload"]["event_id"] == str(callback["event_id"])


def test_integration_callback_skips_events_not_requested_by_caller() -> None:
    connection = RecordingConnection()
    store = JobStore("postgresql+psycopg://unused", "redis://unused")
    store._queue_integration_callback(
        connection,
        {
            "input_payload": {
                "integration_callback_url": "https://caller.example.test/hooks/generation",
                "integration_callback_events": ["generation-status"],
            }
        },
        "case-summary",
        "CASE-SESSION-00042",
        {"generation_status": "approved"},
    )

    assert connection.parameters == []
