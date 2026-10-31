"""Fresh rebuild contracts using the actual SDK Runner, without live model calls."""
import asyncio
import json
import threading
from contextvars import ContextVar
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel, Field

from casepilot_api.workbench_agent import (
    AgentProviderError,
    FinalAnswer,
    InjectedModel,
    ModelTurn,
    ResponsesProvider,
    ToolCall,
    ToolSpec,
    WorkbenchAgent,
    responses_base_url,
)


class Args(BaseModel):
    query: str = Field(min_length=1)


class Provider:
    def __init__(self, *turns):
        self.turns = list(turns)
        self.requests = []

    def complete(self, messages, tools, instructions):
        self.requests.append(list(messages))
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        return turn(messages) if callable(turn) else turn


def call(name="query", identifier="one", arguments='{"query":"login"}'):
    return ModelTurn(calls=[ToolCall(identifier, name, arguments)])


def answer(message="Done"):
    return ModelTurn(final=FinalAnswer(kind="answer", message=message))


def action(messages):
    outputs = [json.loads(item["output"]) for item in messages
               if item.get("type") == "function_call_output"]
    receipt = outputs[-1]["_receipt"]
    return ModelTurn(final=FinalAnswer(kind="action", message="Model claims action",
                                     effect=receipt["effect"], receipt_ids=[receipt["id"]]))


def run(provider, tools=(), **kwargs):
    return WorkbenchAgent(provider, list(tools), **kwargs).run(
        [{"role": "user", "content": "Inspect cases, then prepare a review."}], "Scoped tools only",
    )


def test_multistep_observations_and_grounded_preparation_final():
    provider = Provider(call(), call("prepare", "two"), action)
    result = run(provider, [
        ToolSpec("query", "Query", Args, lambda _: {"case_ids": ["case-1"]}),
        ToolSpec("prepare", "Prepare", Args,
                 lambda _: {"assistant_message": "Review exact preview", "applied": False},
                 "prepare"),
    ])
    assert result.status == "awaiting_input"
    assert result.text == "Review exact preview"
    assert result.final.effect == "prepare"
    assert len(provider.requests) == 3
    assert "case-1" in json.dumps(provider.requests[1])
    assert result.final.receipt_ids == [result.tool_results[-1]["receipt"]["id"]]
    assert all("arguments" not in event and "text" not in event for event in result.events)


@pytest.mark.parametrize("final,code", [
    (FinalAnswer(kind="action", message="Applied", effect="prepare"),
     "agent_final_receipt_required"),
    (FinalAnswer(kind="action", message="Applied", effect="prepare", receipt_ids=["old:1"]),
     "agent_final_receipt_invalid"),
])
def test_action_claim_requires_this_run_receipts(final, code):
    assert run(Provider(ModelTurn(final=final), ModelTurn(final=final))).error_code == code


def test_read_receipt_cannot_substantiate_preparation():
    def wrong_effect(messages):
        response = action(messages)
        response.final.effect = "prepare"
        return response
    result = run(Provider(call(), wrong_effect, wrong_effect), [
        ToolSpec("query", "Query", Args, lambda _: {}),
    ])
    assert result.error_code == "agent_final_receipt_required"


def test_receipt_identity_is_unique_across_runs():
    ids = [run(Provider(call(), action), [ToolSpec("query", "Query", Args, lambda _: {})])
           .final.receipt_ids[0] for _ in range(2)]
    assert ids[0] != ids[1]


def test_plan_only_gets_one_bounded_continuation_then_honest_clarification():
    provider = Provider(call("plan"), answer("Plan ready"), answer("Done"))
    result = run(provider, [
        ToolSpec("plan", "Plan", Args, lambda _: {"steps": ["review"]}, "plan"),
    ])
    assert len(provider.requests) == 3
    assert result.status == "awaiting_input"
    assert result.final.kind == "clarify"
    assert sum(event["type"] == "plan_continuation" for event in result.events) == 1


def test_natural_answers_and_clarifications_need_no_tool_calls():
    assert run(Provider(answer("Here is an explanation"))).status == "completed"
    result = run(Provider(ModelTurn(final=FinalAnswer(
        kind="clarify", message="Which collection?",
    ))))
    assert result.status == "awaiting_input"
    assert result.text == "Which collection?"


@pytest.mark.parametrize("arguments", ["invalid", "[]", '{"query":""}',
                                       '{"query":"ok","account_id":"other"}'])
def test_invalid_arguments_never_execute_or_receive_receipt(arguments):
    visits = []
    result = run(Provider(call(arguments=arguments), answer()), [
        ToolSpec("query", "Query", Args, lambda _: visits.append(1) or {}),
    ])
    assert not visits
    assert result.tool_results[0]["receipt"] is None


def test_replayed_call_is_idempotent_and_conflicting_replay_fails_closed():
    visits = []
    tool = ToolSpec("query", "Query", Args, lambda _: visits.append(1) or {})
    result = run(Provider(call(), call(), action), [tool])
    assert result.status == "completed" and visits == [1]
    assert len(result.tool_results) == 1
    result = run(Provider(call(), call(arguments='{"query":"changed"}')), [tool])
    assert result.error_code == "agent_tool_call_id_conflict"
    assert visits == [1, 1]


@pytest.mark.parametrize("name", ["unknown", "apply"])
def test_unknown_or_approval_tool_is_never_executed(name):
    visits = []
    result = run(Provider(call(name)), [
        ToolSpec("apply", "Apply", Args, lambda _: visits.append(1), requires_approval=True),
    ])
    assert result.error_code == "tool_not_allowed" and not visits


def test_tool_failure_stops_remaining_parallel_calls_and_redacts_errors():
    visits = []
    def fail(args):
        visits.append(args.query)
        raise RuntimeError("private-secret")
    provider = Provider(ModelTurn(calls=[
        ToolCall("a", "query", '{"query":"first"}'),
        ToolCall("b", "query", '{"query":"second"}'),
    ]))
    result = run(provider, [ToolSpec("query", "Query", Args, fail)])
    assert result.error_code == "agent_tool_failed"
    assert visits == ["first"]
    assert "private-secret" not in str(result)


def test_cancellation_before_tool_side_effect():
    state, visits = {"cancel": False}, []
    def event(item):
        if item["type"] == "tool_started":
            state["cancel"] = True
    result = WorkbenchAgent(Provider(call()), [
        ToolSpec("query", "Query", Args, lambda _: visits.append(1)),
    ]).run([], "test", on_event=event, is_cancelled=lambda: state["cancel"])
    assert result.status == "cancelled" and not visits


def test_budgets_bound_model_and_tool_calls():
    tool = ToolSpec("query", "Query", Args, lambda _: {})
    assert run(Provider(call()), [tool], max_turns=1).error_code == "agent_turn_budget_exhausted"
    assert run(Provider(call(), call(identifier="two")), [tool], max_tool_calls=1).error_code == (
        "agent_tool_budget_exhausted"
    )


def test_nested_sync_sdk_handler_and_client_cleanup_use_worker_loop(caplog):
    from agents import Agent, RunConfig, Runner

    from casepilot_api.model_client import managed_model_client

    observed = {}
    class Client:
        async def close(self):
            observed["loop"] = asyncio.get_running_loop()
    def handler(_):
        observed["thread"] = threading.current_thread()
        with managed_model_client(Client()):
            result = Runner.run_sync(Agent(name="nested", model=InjectedModel(
                Provider(ModelTurn(text="Scoped")),
            )), "Scope", run_config=RunConfig(tracing_disabled=True))
        return {"scope": result.final_output}
    result = run(Provider(call(), action), [ToolSpec("query", "Query", Args, handler)])
    assert result.status == "completed"
    assert observed["thread"].ident != threading.get_ident()
    assert not observed["thread"].is_alive()
    assert observed["loop"].is_closed()
    assert "model_client_cleanup_failed" not in caplog.text


def test_parallel_tools_are_serial_and_request_context_is_propagated():
    import time
    value = ContextVar("request_value", default="missing")
    token = value.set("request-a")
    visits, active = [], []
    def handler(args):
        assert not active
        active.append(True)
        visits.append((args.query, value.get(), threading.get_ident()))
        time.sleep(0.005)
        active.pop()
        return {}
    provider = Provider(ModelTurn(calls=[
        ToolCall(str(i), "query", json.dumps({"query": str(i)})) for i in range(3)
    ]), action)
    try:
        result = run(provider, [ToolSpec("query", "Query", Args, handler)])
    finally:
        value.reset(token)
    assert result.status == "completed"
    assert [v[0] for v in visits] == ["0", "1", "2"]
    assert {v[1] for v in visits} == {"request-a"}
    assert len({v[2] for v in visits}) == 1


def test_endpoint_normalizes_explicit_responses_without_switching_api():
    assert responses_base_url("https://ark.cn-beijing.volces.com/api/v3/responses") == (
        "https://ark.cn-beijing.volces.com/api/v3/"
    )
    for url in ["bad", "https://u:secret@example.com/v1", "https://example.com/chat/completions"]:
        with pytest.raises(AgentProviderError):
            responses_base_url(url)


@pytest.mark.parametrize("http_status,code,expected", [
    (404, "ModelNotOpen", "agent_model_not_enabled"),
    (404, None, "agent_endpoint_or_model_not_found"),
    (401, None, "agent_provider_authentication_failed"),
    (200, None, "agent_provider_incomplete_response"),
])
def test_sdk_http_contract_redacts_provider_errors_and_rejects_incomplete(
    caplog, http_status, code, expected,
):
    from openai import AsyncOpenAI

    from casepilot_api.model_client import managed_model_client
    requests = []
    def transport(request):
        requests.append(json.loads(request.content))
        return httpx.Response(http_status, json=(
            {"id": "resp", "object": "response", "created_at": 1, "model": "test",
             "status": "incomplete", "output": []} if http_status == 200
            else {"error": {"code": code, "message": "private-secret-body"}}
        ))
    client = AsyncOpenAI(api_key="offline", max_retries=0,
                         http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)))
    provider = ResponsesProvider(base_url="https://offline.invalid/v1/responses",
                                 api_key="offline", model="test", client=client)
    with managed_model_client(client):
        result = run(provider)
    assert result.error_code == expected
    assert len(requests) == 1
    assert requests[0]["store"] is False
    assert requests[0]["parallel_tool_calls"] is False
    assert requests[0]["text"]["format"]["type"] == "json_schema"
    assert "private-secret" not in caplog.text + str(result)


def test_provider_uses_existing_sdk_model_and_does_not_close_injected_client():
    from agents import OpenAIResponsesModel
    provider = ResponsesProvider(base_url="https://offline.invalid/v1", api_key="offline",
                                 model="test", client=SimpleNamespace())
    assert isinstance(provider.sdk_model, OpenAIResponsesModel)
    provider.close()


@pytest.mark.parametrize("payload", [
    {"status": "failed"}, {"status": "clarification"}, {"error_code": "scope_missing"},
    {"success": False},
])
def test_unsuccessful_tool_outputs_never_provide_action_receipts(payload):
    result = run(Provider(call(), answer()), [ToolSpec("query", "Query", Args, lambda _: payload)])
    assert result.tool_results[0]["receipt"] is None


def test_independent_runs_have_isolated_workers_and_no_global_serialization():
    from concurrent.futures import ThreadPoolExecutor

    from casepilot_api.workbench_agent import _close_worker_loop

    barrier = threading.Barrier(2)
    workers = []
    def execute():
        def handler(_):
            workers.append(threading.current_thread())
            barrier.wait(timeout=3)
            return {}
        try:
            return run(Provider(call(), action), [ToolSpec("query", "Query", Args, handler)])
        finally:
            _close_worker_loop()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(execute), pool.submit(execute)
        assert first.result(timeout=5).status == second.result(timeout=5).status == "completed"
    assert len({worker.ident for worker in workers}) == 2
    assert not any(worker.is_alive() for worker in workers)


def test_responses_wire_contract_preserves_images_and_returns_json_tool_receipt():
    from openai import AsyncOpenAI

    from casepilot_api.model_client import managed_model_client

    requests = []
    def transport(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            output = [{"type": "function_call", "id": "fc1", "call_id": "one",
                       "name": "query", "arguments": '{"query":"login"}'}]
        else:
            observation = next(item for item in body["input"]
                               if item.get("type") == "function_call_output")
            receipt = json.loads(observation["output"])["_receipt"]
            final = FinalAnswer(kind="action", effect="read", message="Read complete",
                                receipt_ids=[receipt["id"]])
            output = [{"type": "message", "id": "m1", "role": "assistant", "status": "completed",
                       "content": [{"type": "output_text", "text": final.model_dump_json(),
                                    "annotations": []}]}]
        return httpx.Response(200, json={"id": "r1", "object": "response", "created_at": 1,
                              "status": "completed", "model": "test", "output": output})
    client = AsyncOpenAI(api_key="offline", max_retries=0,
                         http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)))
    provider = ResponsesProvider(base_url="https://offline.invalid/v1", api_key="offline",
                                 model="test", client=client)
    with managed_model_client(client):
        result = WorkbenchAgent(provider, [ToolSpec("query", "Query", Args, lambda _: {})]).run(
            [{"role": "user", "content": [
                {"type": "input_text", "text": "Inspect"},
                {"type": "input_image", "image_url": "data:image/png;base64,offline"},
            ]}], "Use scoped tools",
        )
    assert result.status == "completed"
    assert len(requests) == 2
    assert requests[0]["input"][0]["content"][1]["type"] == "input_image"
    assert requests[0]["tools"][0]["name"] == "query"
    assert requests[0]["max_output_tokens"] == 8192


@pytest.mark.parametrize("text", ["Sensitive plain model text", '{"kind":"action"}', "null"])
def test_malformed_typed_final_has_safe_contract_diagnostic(text, caplog):
    result = run(Provider(ModelTurn(text=text)))
    assert result.status == "failed"
    assert result.error_code == "agent_model_contract_invalid"
    assert result.final is None
    assert result.tool_results == []
    assert text not in json.dumps(result.events)
    assert text not in caplog.text


def test_safe_sdk_exception_classification():
    from agents.exceptions import ModelBehaviorError, UserError
    from pydantic import ValidationError

    from casepilot_api.workbench_agent import _error_code

    assert _error_code(ModelBehaviorError("private output")) == "agent_model_contract_invalid"
    assert _error_code(UserError("private configuration")) == "agent_sdk_configuration_invalid"
    try:
        FinalAnswer.model_validate({"private": "output"})
    except ValidationError as error:
        assert _error_code(error) == "agent_output_validation_failed"


def test_ungrounded_action_gets_real_tool_continuation_not_synthetic_receipt():
    premature = ModelTurn(final=FinalAnswer(kind="action", message="Prepared", effect="prepare"))
    provider = Provider(premature, call("prepare"), action)
    result = run(provider, [ToolSpec("prepare", "Prepare", Args,
                                   lambda _: {"assistant_message": "Review proposal"}, "prepare")])
    assert result.status == "awaiting_input"
    assert result.text == "Review proposal"
    assert len(provider.requests) == 3
    assert len(result.tool_results) == 1
    assert "Actual successful current-run receipts: []" in provider.requests[1][-1]["content"]
    assert sum(e["type"] == "final_correction" for e in result.events) == 1


def test_ungrounded_action_correction_obeys_original_turn_budget():
    premature = ModelTurn(final=FinalAnswer(kind="action", message="Prepared", effect="prepare"))
    provider = Provider(premature)
    result = run(provider, max_turns=1)
    assert result.error_code == "agent_final_receipt_required"
    assert len(provider.requests) == 1
    assert result.tool_results == []


@pytest.mark.parametrize("intent", ["CASE_GENERATE", "CASE_REUSE", "CASE_MODIFY"])
def test_typed_plan_query_selection_requires_real_domain_preparation(intent):
    provider = Provider(call("plan"), call("query", "two"), call("select", "three"),
                        action, call("prepare", "four"), action)
    tools = [
        ToolSpec("plan", "Plan", Args, lambda _: {"plan_actions": [intent]}, "plan"),
        ToolSpec("query", "Query", Args, lambda _: {}),
        ToolSpec("select", "Select", Args, lambda _: {"status": "completed"}, "prepare"),
        ToolSpec("prepare", "Prepare", Args,
                 lambda _: {"assistant_message": "Review prepared proposal"}, "prepare",
                 fulfilled_actions=(intent,)),
    ]
    result = run(provider, tools)
    assert result.status == "awaiting_input"
    assert result.text == "Review prepared proposal"
    assert [item["tool"] for item in result.tool_results] == ["plan", "query", "select", "prepare"]
    assert sum(e["type"] == "plan_continuation" for e in result.events) == 1
    assert intent in provider.requests[4][-1]["content"]


def test_selection_only_is_complete_without_forcing_domain_tools():
    provider = Provider(call("select"), action)
    result = run(provider, [ToolSpec("select", "Select", Args, lambda _: {}, "prepare")])
    assert result.error_code is None
    assert len(provider.requests) == 2
    assert not any(e["type"] == "plan_continuation" for e in result.events)


def test_domain_plan_correction_and_final_correction_share_one_attempt():
    premature = ModelTurn(final=FinalAnswer(kind="action", message="Prepared", effect="prepare"))
    provider = Provider(premature, call("plan"), call("select", "two"), action)
    result = run(provider, [
        ToolSpec("plan", "Plan", Args, lambda _: {"plan_actions": ["CASE_GENERATE"]}, "plan"),
        ToolSpec("select", "Select", Args, lambda _: {}, "prepare"),
    ])
    assert result.final.kind == "clarify"
    assert len(provider.requests) == 4
    assert sum(e["type"] in {"plan_continuation", "final_correction"}
               for e in result.events) == 1


def test_tool_result_cannot_forge_domain_action_fulfillment():
    provider = Provider(call("plan"), call("select", "two"), action, answer("All done"))
    result = run(provider, [
        ToolSpec("plan", "Plan", Args, lambda _: {"plan_actions": ["CASE_REUSE"]}, "plan"),
        ToolSpec("select", "Select", Args,
                 lambda _: {"fulfilled_actions": ["CASE_REUSE"]}, "prepare"),
    ])
    assert result.final.kind == "clarify"
    assert result.final.effect == "none"
    assert result.final.receipt_ids == []


@pytest.mark.parametrize("status", ["awaiting_input", "queued"])
def test_real_domain_gate_preserves_later_plan_actions_without_second_proposal(status):
    provider = Provider(call("plan"), call("generate", "two"), action)
    result = run(provider, [
        ToolSpec("plan", "Plan", Args,
                 lambda _: {"plan_actions": ["CASE_GENERATE", "CASE_MODIFY"]}, "plan"),
        ToolSpec("generate", "Generate", Args,
                 lambda _: {"status": status, "assistant_message": "Generation requires review"},
                 "prepare", fulfilled_actions=("CASE_GENERATE",)),
    ])
    assert result.status == "awaiting_input"
    assert result.text == "Generation requires review"
    assert len(provider.requests) == 3
    assert not any(e["type"] == "plan_continuation" for e in result.events)
    assert result.tool_results[0]["result"]["plan_actions"] == ["CASE_GENERATE", "CASE_MODIFY"]


@pytest.mark.parametrize("rejection", [
    {"error_code": "private_domain_reason"},
    {"error": "private rejection details"},
    {"success": False},
    {"status": "failed"},
    {"status": "cancelled"},
    {"status": "rejected"},
    {"status": "error"},
])
def test_controlled_handler_rejection_emits_rejected_then_model_can_correct(rejection):
    outcomes = iter([rejection, {"status": "completed"}])
    provider = Provider(call(), call(identifier="corrected"), action)
    result = run(provider, [ToolSpec("query", "Query", Args, lambda _: next(outcomes))])
    assert result.status == "completed"
    assert result.tool_results[0]["receipt"] is None
    assert result.tool_results[1]["receipt"] is not None
    assert result.final.receipt_ids == [result.tool_results[1]["receipt"]["id"]]
    events = [event["type"] for event in result.events if event.get("tool") == "query"]
    assert events == ["tool_started", "tool_rejected", "tool_started", "tool_completed"]
    assert "private" not in json.dumps(result.events)
    outputs = [json.loads(item["output"]) for item in provider.requests[1]
               if item.get("type") == "function_call_output"]
    assert outputs[-1]["_receipt"] is None


def test_legitimate_tool_clarification_completes_without_effect_receipt():
    provider = Provider(call(), ModelTurn(final=FinalAnswer(
        kind="clarify", message="Which selected collection should I use?",
    )))
    result = run(provider, [ToolSpec("query", "Query", Args,
                                   lambda _: {"status": "clarification", "question": "Which?"})])
    assert result.status == "awaiting_input"
    assert result.final.kind == "clarify"
    assert result.final.effect == "none"
    assert result.final.receipt_ids == []
    assert result.tool_results[0]["receipt"] is None
    assert [e["type"] for e in result.events if e.get("tool") == "query"] == [
        "tool_started", "tool_completed",
    ]


@pytest.mark.parametrize("kind,status", [("answer", "completed"), ("clarify", "awaiting_input")])
def test_read_receipt_can_ground_informational_answer_or_clarification(kind, status):
    def read_final(messages):
        response = action(messages)
        response.final.kind = kind
        response.final.message = "Read authorized collections; which should I use?"
        return response

    provider = Provider(call("query_collections"), read_final)
    result = run(provider, [ToolSpec("query_collections", "Read", Args,
                                   lambda _: {"collections": ["authorized"]})])
    assert result.status == status
    assert result.final.kind == kind
    assert result.final.effect == "read"
    assert result.final.receipt_ids == [result.tool_results[0]["receipt"]["id"]]
    assert len(provider.requests) == 2
    assert not any(e["type"] == "final_correction" for e in result.events)


@pytest.mark.parametrize("kind", ["answer", "clarify"])
@pytest.mark.parametrize("refs,code", [
    ([], "agent_final_receipt_required"),
    (["foreign:1"], "agent_final_receipt_invalid"),
])
def test_informational_read_claim_still_requires_real_current_read_receipt(kind, refs, code):
    final = ModelTurn(final=FinalAnswer(kind=kind, message="Read complete", effect="read",
                                      receipt_ids=refs))
    result = run(Provider(final, final))
    assert result.status == "failed"
    assert result.error_code == code
    assert result.final is None


@pytest.mark.parametrize("kind", ["answer", "clarify"])
def test_informational_final_cannot_claim_preparation(kind):
    def invalid_final(messages):
        response = action(messages)
        response.final.kind = kind
        return response

    result = run(Provider(call("prepare"), invalid_final, invalid_final), [
        ToolSpec("prepare", "Prepare", Args, lambda _: {}, "prepare"),
    ])
    assert result.error_code == "agent_final_effect_invalid"
    assert result.final is None


def test_preparation_receipt_cannot_substitute_for_informational_read_receipt():
    def wrong_receipt(messages):
        response = action(messages)
        response.final.kind = "answer"
        response.final.effect = "read"
        return response

    result = run(Provider(call("prepare"), wrong_receipt, wrong_receipt), [
        ToolSpec("prepare", "Prepare", Args, lambda _: {}, "prepare"),
    ])
    assert result.error_code == "agent_final_receipt_required"
    assert result.final is None


@pytest.mark.parametrize("intent", ["COLLECTION_CREATE", "COLLECTION_RENAME", "COLLECTION_DELETE"])
def test_collection_proposal_gate_stops_before_later_generation(intent):
    provider = Provider(call("plan"), call("collection", "two"), action)
    result = run(provider, [
        ToolSpec("plan", "Plan", Args,
                 lambda _: {"plan_actions": [intent, "CASE_GENERATE"]}, "plan"),
        ToolSpec("collection", "Prepare entity review", Args,
                 lambda _: {"status": "awaiting_input", "requires_human_review": True,
                            "applied": False, "assistant_message": "Review collection proposal"},
                 "prepare", fulfilled_actions=(intent,)),
    ])
    assert result.status == "awaiting_input"
    assert result.text == "Review collection proposal"
    assert len(provider.requests) == 3
    assert not any(e["type"] == "plan_continuation" for e in result.events)
    assert result.tool_results[0]["result"]["plan_actions"] == [intent, "CASE_GENERATE"]


def test_query_and_selection_do_not_fulfill_collection_creation():
    provider = Provider(call("plan"), call("query", "two"), call("select", "three"),
                        action, answer("Done"))
    result = run(provider, [
        ToolSpec("plan", "Plan", Args,
                 lambda _: {"plan_actions": ["COLLECTION_CREATE"]}, "plan"),
        ToolSpec("query", "Query", Args, lambda _: {}),
        ToolSpec("select", "Select", Args, lambda _: {}, "prepare"),
    ])
    assert result.status == "awaiting_input"
    assert result.final.kind == "clarify"
    assert result.final.effect == "none"
    assert sum(e["type"] == "plan_continuation" for e in result.events) == 1


@pytest.mark.parametrize("invalid_kind", ["answer", "clarify"])
def test_rename_proposal_final_correction_explains_action_review_shape(invalid_kind):
    def invalid_review(messages):
        response = action(messages)
        response.final.kind = invalid_kind
        response.final.receipt_ids = []
        return response

    def corrected_review(messages):
        correction = messages[-1]["content"]
        outputs = [json.loads(item["output"]) for item in messages
                   if item.get("type") == "function_call_output"]
        receipt = outputs[-1]["_receipt"]
        assert receipt["id"] in correction
        assert '"kind": "action", "effect": "prepare"' in correction
        assert "do not repeat successful preparation" in correction
        return action(messages)

    handler_calls = []

    def proposal(_args):
        handler_calls.append(True)
        return {"status": "awaiting_input", "requires_human_review": True, "applied": False,
                "proposal": {"action": "rename", "status": "pending"},
                "assistant_message": "请确认重命名提案；尚未更改集合。"}

    result = run(Provider(call("rename_collection"), invalid_review, corrected_review), [
        ToolSpec("rename_collection", "Prepare rename", Args, proposal, "prepare",
                 fulfilled_actions=("COLLECTION_RENAME",)),
    ])
    assert result.status == "awaiting_input"
    assert result.final.kind == "action"
    assert result.final.effect == "prepare"
    assert result.text == "请确认重命名提案；尚未更改集合。"
    assert handler_calls == [True]
    assert sum(e["type"] == "final_correction" for e in result.events) == 1


@pytest.mark.parametrize("kind", ["answer", "clarify"])
def test_real_pending_rename_proposal_can_be_described_as_answer_or_clarification(kind):
    def review_final(messages):
        response = action(messages)
        response.final.kind = kind
        response.final.message = "Model says already renamed"
        return response

    result = run(Provider(call("rename_collection"), review_final), [
        ToolSpec("rename_collection", "Prepare rename", Args,
                 lambda _: {"status": "awaiting_input", "requires_human_review": True,
                            "applied": False, "proposal": {"status": "pending", "action": "rename"},
                            "assistant_message": "Rename proposal pending; nothing applied"},
                 "prepare", fulfilled_actions=("COLLECTION_RENAME",)),
    ])
    assert result.status == "awaiting_input"
    assert result.final.kind == kind
    assert result.final.effect == "prepare"
    assert result.text == "Rename proposal pending; nothing applied"
    assert not any(event["type"] == "final_correction" for event in result.events)


@pytest.mark.parametrize("change", [
    {"applied": True}, {"requires_human_review": False}, {"status": "completed"},
    {"proposal": None}, {"proposal": {"status": "applied"}},
])
def test_informational_prepare_requires_genuine_pending_review_artifact(change):
    def review_final(messages):
        response = action(messages)
        response.final.kind = "clarify"
        return response

    result = run(Provider(call("rename_collection"), review_final, review_final), [
        ToolSpec("rename_collection", "Prepare rename", Args,
                 lambda _: {"status": "awaiting_input", "requires_human_review": True,
                            "applied": False, "proposal": {"status": "pending"}, **change},
                 "prepare", fulfilled_actions=("COLLECTION_RENAME",)),
    ])
    assert result.error_code == "agent_final_effect_invalid"
    assert result.final is None


def test_selection_receipt_cannot_impersonate_pending_collection_review():
    def review_final(messages):
        response = action(messages)
        response.final.kind = "clarify"
        return response

    result = run(Provider(call("select_assets"), review_final, review_final), [
        ToolSpec("select_assets", "Select", Args,
                 lambda _: {"status": "awaiting_input", "requires_human_review": True,
                            "applied": False, "proposal": {"status": "pending"}}, "prepare"),
    ])
    assert result.error_code == "agent_final_effect_invalid"
    assert result.final is None


def test_pending_review_rejects_foreign_receipt_even_alongside_valid_receipt():
    def foreign_review(messages):
        response = action(messages)
        response.final.kind = "clarify"
        response.final.receipt_ids.append("foreign:1")
        return response

    result = run(Provider(call("rename_collection"), foreign_review, foreign_review), [
        ToolSpec("rename_collection", "Rename", Args,
                 lambda _: {"status": "awaiting_input", "requires_human_review": True,
                            "applied": False, "proposal": {"status": "pending"}},
                 "prepare", fulfilled_actions=("COLLECTION_RENAME",)),
    ])
    assert result.error_code == "agent_final_receipt_invalid"
    assert result.final is None


@pytest.mark.parametrize("status", ["queued", "running"])
def test_compute_receipt_ends_agent_loop_without_claiming_domain_job_completed(status):
    provider = Provider(call("plan"), call("prepare_rewrite", "two"), action)
    result = run(provider, [
        ToolSpec("plan", "Plan", Args,
                 lambda _: {"plan_actions": ["CASE_MODIFY", "CASE_GENERATE"]}, "plan"),
        ToolSpec("prepare_rewrite", "Compute draft", Args,
                 lambda _: {"status": status, "requires_human_review": False, "applied": False,
                            "job_id": "server-job", "assistant_message": "Draft is computing"},
                 "prepare", fulfilled_actions=("CASE_MODIFY",)),
    ])
    assert result.status == "completed"  # Agent loop only.
    assert result.text == "Draft is computing"
    assert result.tool_results[-1]["result"]["status"] == status
    assert not result.tool_results[-1]["result"]["requires_human_review"]
    assert result.events[-1]["type"] == "run_completed"
    assert not any(e["type"] == "plan_continuation" for e in result.events)


def test_scripted_semantic_reference_uses_bounded_catalog_then_exact_observed_selection():
    from casepilot_api.workbench_tools import AssetQueryArguments

    class SelectionArgs(BaseModel):
        ref: str
        version: str

    state = {"selected": ["bad", "good"]}
    rows = [
        {"ref": "bad", "version": "v1", "snapshot": {"title": "Scenario A",
         "description": "Invalid verification code must be rejected", "steps": []}},
        {"ref": "good", "version": "v2", "snapshot": {"title": "Scenario B",
         "description": "Valid verification code authenticates", "steps": []}},
    ]

    def query(args):
        assert args.search == "" and args.scope == "selection"
        return {"cases": rows, "search_mode": "catalog", "truncated": False, "has_more": False}

    def choose(messages):
        outputs = [json.loads(item["output"]) for item in messages
                   if item.get("type") == "function_call_output"]
        assert outputs[-1]["cases"] == rows
        # Scripted choice proves the tool chain, not real-provider interpretation.
        return call("select_assets", "select", '{"ref":"bad","version":"v1"}')

    def select(args):
        assert any(row["ref"] == args.ref and row["version"] == args.version for row in rows)
        state["selected"] = [args.ref]
        return {"status": "completed"}

    provider = Provider(call("query_assets", arguments='{"search":"","scope":"selection"}'),
                        choose, action)
    result = WorkbenchAgent(provider, [
        ToolSpec("query_assets", "Catalog", AssetQueryArguments, query),
        ToolSpec("select_assets", "Select observed identity", SelectionArgs, select, "prepare"),
    ]).run([{"role": "user", "content": "只选当前选中项中错误验证码被拒绝的用例，不选成功用例。"}],
           "Select only a uniquely matching observed case; preserve the authorized scope.")
    assert result.error_code is None
    assert state["selected"] == ["bad"]
    event = next(e for e in result.events if e["type"] == "tool_completed"
                 and e["tool"] == "query_assets")
    assert event["returned_count"] == 2
    assert event["truncated"] is False and event["has_more"] is False
    assert result.events[-1]["final_kind"] == "action"
    assert result.events[-1]["final_effect"] == "prepare"
    assert "verification" not in json.dumps(result.events)
    assert "snapshot" not in json.dumps(result.events)


def test_durable_budget_rejection_precedes_provider_call():
    provider = Provider(ModelTurn(final=FinalAnswer(kind="answer", message="unused")))
    reservations = []

    def reserve(amounts):
        reservations.append(amounts)
        return False

    result = WorkbenchAgent(provider, []).run(
        [{"role": "user", "content": "original"}], "test", reserve_budget=reserve,
    )
    assert result.error_code == "agent_cumulative_budget_exhausted"
    assert not provider.requests
    assert reservations == [{"model_turns": 1, "reserved_sdk_requests": 1}]


def test_old_artifact_observation_gets_only_current_read_receipt():
    provider = Provider(call("prepare_rewrite"), action)
    result = run(provider, [ToolSpec(
        "prepare_rewrite", "Read existing artifact", Args,
        lambda _: {"existing_artifact": True, "status": "completed", "artifact_id": "old"},
        "prepare", fulfilled_actions=("CASE_MODIFY",),
    )])
    assert result.error_code is None
    assert result.final.effect == "read"
    assert result.tool_results[0]["receipt"]["effect"] == "read"


def test_durable_current_step_cannot_finish_from_unrelated_answer_without_new_plan_call():
    provider = Provider(
        ModelTurn(final=FinalAnswer(kind="answer", message="Only an intention.")),
        call("prepare_rewrite"), action,
    )
    agent = WorkbenchAgent(provider, [ToolSpec(
        "prepare_rewrite", "Prepare", Args,
        lambda _: {"status": "queued", "requires_human_review": False, "job_id": "actual"},
        "prepare", fulfilled_actions=("CASE_MODIFY",),
    )])
    result = agent.run([{"role": "user", "content": "Original instruction"}], "Prepare",
                       current_action=lambda: "CASE_MODIFY")
    assert result.error_code is None
    assert any(event["type"] == "plan_continuation" for event in result.events)
    assert result.tool_results[0]["tool"] == "prepare_rewrite"
