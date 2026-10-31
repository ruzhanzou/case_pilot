from workbench_agent_live_journey import runtime_diagnostics


def test_qa_tool_diagnostics_drop_sensitive_unknown_fields():
    result = runtime_diagnostics(
        {
            "events": [
                {
                    "type": "tool_failed",
                    "tool": "delete_collection",
                    "diagnostic": {
                        "phase": "handler",
                        "exception_class": "ValueError",
                        "raw": "SECRET",
                        "http_detail_code": "SECRET",
                        "canonical_count": True,
                    },
                }
            ]
        }
    )
    assert result["tool_events"][0]["diagnostic"] == {
        "phase": "handler",
        "exception_class": "ValueError",
        "http_detail_code": "unknown",
    }
    assert "SECRET" not in str(result)


def test_completion_and_answer_display_are_bounded_and_redacted():
    from workbench_agent_live_journey import safe_turn_evidence

    secret = "synthetic-private-test-secret"
    response = {
        "assistant_message": {
            "content": "Visible answer " + secret + " sk-private " + "x" * 700,
            "metadata": {
                "workbench_agent": {
                    "status": "completed",
                    "events": [
                        {
                            "type": "run_completed",
                            "final_kind": "answer",
                            "final_effect": "read",
                            "completion": {
                                "completion_code": "goal_unverified",
                                "plan_present": False,
                                "plan_cursor": 0,
                                "raw": "DO_NOT_SAVE",
                                "plan_action": "BAD",
                            },
                        }
                    ],
                    "raw_response": "DO_NOT_SAVE",
                    "reasoning": "DO_NOT_SAVE",
                }
            },
        }
    }
    result = safe_turn_evidence(response, {}, {}, "selection_update", secret)
    assert "Visible answer" in result["display_answer"]
    assert len(result["display_answer"]) <= 600
    assert secret not in str(result) and "sk-private" not in str(result)
    assert "DO_NOT_SAVE" not in str(result)
    diagnostic = runtime_diagnostics(
        response["assistant_message"]["metadata"]["workbench_agent"]
    )
    assert diagnostic["completion"] == {
        "completion_code": "goal_unverified",
        "plan_present": False,
        "plan_cursor": 0,
    }


def test_server_final_cancellation_overrides_earlier_model_completion_diagnostic():
    result = runtime_diagnostics(
        {
            "completion": {"completion_code": "cancelled"},
            "events": [
                {
                    "type": "run_completed",
                    "final_kind": "answer",
                    "final_effect": "read",
                    "completion": {"completion_code": "goal_satisfied"},
                }
            ],
        }
    )
    assert result["completion"] == {"completion_code": "cancelled"}
