import json
import threading

import pytest
from fastapi import HTTPException
from test_workbench_agent import Args, Provider, answer, call, run

from casepilot_api.workbench_agent import ToolSpec
from casepilot_api.workbench_events import safe_event
from casepilot_api.workbench_tool_diagnostics import safe_tool_diagnostic


@pytest.mark.parametrize(
    "handler,phase,category",
    [
        (
            lambda _: (_ for _ in ()).throw(HTTPException(409, "collection_impact_busy")),
            "handler",
            "HTTPException",
        ),
        (lambda _: [], "result_type", "TypeError"),
        (lambda _: {"bad": float("nan")}, "result_json", "ValueError"),
        (
            lambda _: (_ for _ in ()).throw(RuntimeError("SECRET/raw SQL")),
            "handler",
            "RuntimeError",
        ),
    ],
)
def test_failure_phase_preserves_stop_and_redacts(handler, phase, category):
    result = run(Provider(call()), [ToolSpec("query", "query", Args, handler)])
    assert result.error_code == "agent_tool_failed"
    event = next(e for e in result.events if e["type"] == "tool_failed")
    assert event["diagnostic"]["phase"] == phase
    assert event["diagnostic"]["exception_class"] == category
    assert "SECRET" not in json.dumps(result.events)
    if category == "HTTPException":
        assert event["diagnostic"]["http_status"] == 409
        assert event["diagnostic"]["http_detail_code"] == "collection_impact_busy"


def test_rejection_context_runs_after_handler_same_thread_and_cannot_change_result():
    seen = []

    def handler(_):
        seen.append(threading.get_ident())
        return {"error_code": "plan_required"}

    def context():
        assert seen == [threading.get_ident()]
        return {
            "plan_cursor": 2,
            "plan_action": "CASE_MODIFY",
            "canonical_version": 3,
            "canonical_count": 1,
            "canonical_present": True,
            "raw": "SECRET",
        }

    result = run(
        Provider(call(), answer(), answer()),
        [ToolSpec("query", "query", Args, handler, diagnostic_context=context)],
    )
    event = next(e for e in result.events if e["type"] == "tool_rejected")
    assert event["diagnostic"]["rejection_code"] == "plan_required"
    assert event["diagnostic"]["plan_cursor"] == 2
    assert "SECRET" not in json.dumps(result.events)

    def broken():
        raise ValueError("SECRET")

    result = run(
        Provider(call(), answer(), answer()),
        [ToolSpec("query", "query", Args, handler, diagnostic_context=broken)],
    )
    event = next(e for e in result.events if e["type"] == "tool_rejected")
    assert event["diagnostic"] == {
        "rejection_code": "plan_required",
        "diagnostic_unavailable": True,
    }
    assert result.error_code is None


def test_event_diagnostics_strict_types_bounds_and_unknown_codes():
    dirty = {
        "rejection_code": "SECRET",
        "http_detail_code": {"secret": "value"},
        "exception_class": "CustomSecret",
        "phase": "SECRET",
        "plan_action": "SECRET",
        "canonical_count": True,
        "canonical_version": -1,
        "plan_cursor": 1001,
        "canonical_present": "true",
        "http_status": 200,
        "args": "SECRET",
    }
    expected = {
        "rejection_code": "unknown",
        "http_detail_code": "unknown",
        "exception_class": "unrecognized",
    }
    assert safe_tool_diagnostic(dirty) == expected
    event = safe_event(
        {
            "type": "tool_failed",
            "sequence": 1,
            "tool": "delete_collection",
            "diagnostic": dirty,
            "traceback": "SECRET",
        }
    )
    assert event["diagnostic"] == expected
    assert "SECRET" not in json.dumps(event)

@pytest.mark.parametrize('broken',[False,True])
def test_failed_tool_callback_safe_and_cannot_mask_exception(broken):
    def context():
        if broken:
            raise ValueError('SECRET')
        return {'argument_base_version': 2, 'canonical_version': 3,
                'request_selection_version': 3, 'rawargs': 'SECRET'}
    def handler(_):
        raise HTTPException(409, 'workbench_selection_version_conflict')
    result = run(Provider(call()), [ToolSpec('query', 'query', Args, handler,
                                           diagnostic_context=context)])
    assert result.error_code == 'agent_tool_failed'
    event = next(e for e in result.events if e['type'] == 'tool_failed')
    value = event['diagnostic']
    assert value['http_detail_code'] == 'workbench_selection_version_conflict'
    if broken:
        assert value['diagnostic_unavailable'] is True
    else:
        assert value['argument_base_version'] == 2 and value['canonical_version'] == 3
        assert value['request_selection_version'] == 3
    assert 'SECRET' not in json.dumps(event)

@pytest.mark.parametrize('value',[True,-1,2147483648,'2',{},2.0,None])
def test_selection_diagnostic_integer_bounds(value):
    assert safe_tool_diagnostic({'argument_base_version':value,
                                 'request_selection_version':value}) == {}

def test_selection_argument_snapshot_does_not_leak_into_other_tools():
    from types import SimpleNamespace

    from casepilot_api.workbench_tools import WorkbenchTools
    bridge = WorkbenchTools(None, None, SimpleNamespace(context={}), None)
    bridge.selection_diagnostic = {'argument_base_version': 2}
    specs = {item.name: item for item in bridge.specs()}
    assert specs['select_collection'].diagnostic_context()['argument_base_version'] == 2
    assert 'argument_base_version' not in specs['select_collection'].diagnostic_context()
    assert 'argument_base_version' not in specs['query_assets'].diagnostic_context()
    assert 'argument_base_version' not in bridge.completion_state()
