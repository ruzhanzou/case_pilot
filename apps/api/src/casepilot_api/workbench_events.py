"""Ephemeral activity only; committed submission receipts remain authoritative."""
from __future__ import annotations

import asyncio
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from redis import Redis
from redis.exceptions import RedisError

from casepilot_api.auth import CurrentAccount, DbSession, require_space_membership
from casepilot_api.config import get_settings
from casepilot_api.models import Conversation

router = APIRouter(prefix="/api/v1", tags=["workbench-events"])
TTL_SECONDS = 900
TERMINAL = {"run_completed", "run_awaiting_input", "run_failed", "run_cancelled"}
EVENT_TYPES = TERMINAL | {
    "run_started", "model_started", "tool_started", "tool_completed", "tool_rejected",
    "tool_failed", "tool_replayed", "plan_continuation", "final_correction",
}
# Names/codes come from server runtime, never arbitrary error messages or arguments.
TOOLS = {
    "get_workspace_context", "query_cases", "query_assets", "query_collections",
    "plan_work", "plan_test_points", "prepare_rewrite", "prepare_delete",
    "review_cases", "deduplicate_cases", "analyze_coverage", "answer_question",
    "prepare_generation", "prepare_review", "prepare_dedup", "prepare_coverage",
    "answer_knowledge", "read_attachment_evidence", "query_candidates", "select_assets",
    "select_collection",
    "create_collection", "rename_collection", "delete_collection", "prepare_reuse",
    "list_attachments", "read_attachment", "search_evidence", "update_selection",
    "query_uploaded_cases", "preview_uploaded_cases",
}
ERROR_CODES = {
    "agent_cancelled", "agent_tool_failed", "agent_stopped", "invalid_tool_arguments",
    "tool_not_allowed", "agent_tool_budget_exhausted", "agent_turn_budget_exhausted",
    "agent_invalid_tool_call", "agent_tool_call_id_conflict", "agent_final_effect_invalid",
    "agent_final_receipt_invalid", "agent_final_receipt_required", "agent_model_contract_invalid",
    "agent_output_validation_failed", "agent_sdk_configuration_invalid", "agent_provider_error",
    "agent_provider_timeout", "agent_provider_connection_error", "agent_model_not_enabled",
    "agent_provider_request_rejected", "agent_provider_authentication_failed",
    "agent_provider_access_denied", "agent_endpoint_or_model_not_found",
    "agent_provider_rate_limited", "agent_provider_unavailable",
    "agent_provider_incomplete_response", "agent_configuration_missing",
}


def safe_event(event):
    if (not isinstance(event, dict) or not isinstance(event.get("type"), str)
            or event["type"] not in EVENT_TYPES):
        return None
    sequence = event.get("sequence")
    if type(sequence) is not int or not 1 <= sequence <= 1000:
        return None
    clean = {"type": event["type"], "sequence": sequence}
    if type(event.get("turn")) is int and 1 <= event["turn"] <= 32:
        clean["turn"] = event["turn"]
    if isinstance(event.get("tool"), str) and event["tool"] in TOOLS:
        clean["tool"] = event["tool"]
    if isinstance(event.get("error_code"), str) and event["error_code"] in ERROR_CODES:
        clean["error_code"] = event["error_code"]
    if (event["type"] == "tool_completed" and clean.get("tool") in {
        "query_assets", "query_candidates", "query_uploaded_cases", "query_collections",
    } and type(event.get("returned_count")) is int and 0 <= event["returned_count"] <= 10000):
        clean["returned_count"] = event["returned_count"]
        for key in ("truncated", "has_more"):
            if type(event.get(key)) is bool:
                clean[key] = event[key]
    if event["type"] in {"tool_rejected", "tool_failed"} and "diagnostic" in event:
        from casepilot_api.workbench_tool_diagnostics import safe_tool_diagnostic
        clean["diagnostic"] = safe_tool_diagnostic(event["diagnostic"])
    if event["type"] in TERMINAL:
        if "completion" in event:
            from casepilot_api.workbench_tool_diagnostics import safe_tool_diagnostic
            clean["completion"] = safe_tool_diagnostic(event["completion"])
        if isinstance(event.get("final_kind"), str) and event["final_kind"] in {
            "answer", "clarify", "action",
        }:
            clean["final_kind"] = event["final_kind"]
        if isinstance(event.get("final_effect"), str) and event["final_effect"] in {
            "none", "read", "prepare",
        }:
            clean["final_effect"] = event["final_effect"]
    return clean


def segment_event_bound(max_turns, max_tool_calls):
    # One start, <=M model starts, <=2T tool events, <=1 correction,
    # SDK terminal + committed terminal. Keep this proof beside the allocator.
    return max_turns + 2 * max_tool_calls + 4


def reserved_segment_base(used, max_turns, max_tool_calls):
    end = (used.get("model_turns", 0) + 2 * used.get("tool_calls", 0)
           + 4 * used.get("segments", 0))
    base = end - segment_event_bound(max_turns, max_tool_calls)
    if base < 0 or end > 1000:
        raise ValueError("workbench_event_budget_invalid")
    return base


_SEGMENT_PUBLISH = """
local active = redis.call('GET', KEYS[1] .. ':segment')
local base = tonumber(ARGV[1])
if ARGV[3] == 'run_started' then
    if active and tonumber(active) > base then return 0 end
    if not active or tonumber(active) < base then
        redis.call('SET', KEYS[1] .. ':segment', ARGV[1], 'EX', ARGV[5])
        redis.call('DEL', KEYS[1] .. ':terminal')
    end
elseif not active or tonumber(active) ~= base then
    return 0
end
local prior = redis.call('HGET', KEYS[1] .. ':sequences', ARGV[2])
if prior then
    if prior == ARGV[4] then return 1 else return 0 end
end
redis.call('HSET', KEYS[1] .. ':sequences', ARGV[2], ARGV[4])
redis.call('ZADD', KEYS[1] .. ':events', ARGV[2], ARGV[4])
redis.call('EXPIRE', KEYS[1] .. ':segment', ARGV[5])
redis.call('EXPIRE', KEYS[1] .. ':sequences', ARGV[5])
redis.call('EXPIRE', KEYS[1] .. ':events', ARGV[5])
if ARGV[6] == '1' then
    redis.call('SET', KEYS[1] .. ':terminal', ARGV[3], 'EX', ARGV[5])
end
return 1
"""


class WorkbenchEventStore:
    def __init__(self, account_id, conversation_id, request_id, *, client=None):
        ids = [str(UUID(str(value))) for value in (account_id, conversation_id, request_id)]
        self.key = "casepilot:workbench:" + ":".join(ids)
        self.client = client or Redis.from_url(
            get_settings().redis_url, decode_responses=True,
            socket_connect_timeout=1, socket_timeout=1,
        )

    def publish(self, event, *, segment_base=None):
        clean = safe_event(event)
        if clean is None:
            return False
        try:
            if segment_base is not None:
                if (type(segment_base) is not int or segment_base < 0
                        or clean["sequence"] <= segment_base):
                    return False
                return bool(self.client.eval(_SEGMENT_PUBLISH, 1, self.key,
                    segment_base, clean["sequence"], clean["type"],
                    json.dumps(clean, sort_keys=True), TTL_SECONDS,
                    "1" if clean["type"] in TERMINAL else "0"))
            # Sorted sequence numbers make retries idempotent and replay ordered.
            pipe = self.client.pipeline(transaction=True)
            pipe.zadd(self.key + ":events", {json.dumps(clean): clean["sequence"]}, nx=True)
            pipe.expire(self.key + ":events", TTL_SECONDS)
            if clean["type"] in TERMINAL:
                pipe.set(self.key + ":terminal", clean["type"], ex=TTL_SECONDS)
            pipe.execute()
            return True
        except RedisError:
            return False  # Redis failure never rolls back a domain transaction.

    def read(self, cursor=0):
        raw = self.client.zrangebyscore(self.key + ":events", f"({cursor}", "+inf")
        events = []
        for value in raw:
            try:
                clean = safe_event(json.loads(value))
            except (ValueError, TypeError):
                continue
            if clean:
                events.append(clean)
        return events

    def is_terminal(self):
        return bool(self.client.exists(self.key + ":terminal"))

    def is_cancelled(self):
        try:
            return bool(self.client.exists(self.key + ":cancel"))
        except RedisError:
            return False

    def request_cancel(self):
        if self.client.exists(self.key + ":terminal"):
            return "already_terminal"
        self.client.set(self.key + ":cancel", "1", ex=TTL_SECONDS)
        return "requested"


def authorized_store(db, account, conversation_id, request_id):
    # Plain SELECT: never wait for the in-flight submission's FOR UPDATE lock.
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.account_id != account.id:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    require_space_membership(db, account.id, conversation.space_id)
    return WorkbenchEventStore(account.id, conversation_id, request_id)


async def event_stream(request, store, cursor=0):
    # Bounded connection lifetime; browser can reconnect with its cursor.
    for _ in range(TTL_SECONDS * 2):
        if await request.is_disconnected():
            return
        try:
            # Read marker first: if it appears between reads, the next poll must
            # still deliver the terminal event rather than close prematurely.
            terminal = await asyncio.to_thread(store.is_terminal)
            events = await asyncio.to_thread(store.read, cursor)
        except RedisError:
            yield 'event: workbench.unavailable\ndata: {"code":"activity_unavailable"}\n\n'
            return
        for event in events:
            cursor = event["sequence"]
            yield f"id: {cursor}\nevent: workbench.activity\ndata: {json.dumps(event)}\n\n"
            if event["type"] in TERMINAL:
                return
        if not events:
            if terminal:
                return
            yield ": pending-or-expired; database state remains authoritative\n\n"
        await asyncio.sleep(0.5)


@router.get("/conversations/{conversation_id}/agent-runs/{request_id}/events")
def stream_events(
    conversation_id: UUID, request_id: UUID, request: Request,
    account: CurrentAccount, db: DbSession,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    cursor: int = Query(default=0, ge=0, le=1000),
):
    store = authorized_store(db, account, conversation_id, request_id)
    # Authentication is complete; no ORM objects are used by the generator.
    # Release the read transaction now, not when the long-lived stream closes.
    db.close()
    if last_event_id is not None:
        try:
            cursor = int(last_event_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="activity_cursor_invalid") from None
        if not 0 <= cursor <= 1000:
            raise HTTPException(status_code=422, detail="activity_cursor_invalid")
    return StreamingResponse(event_stream(request, store, cursor), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/conversations/{conversation_id}/agent-runs/{request_id}/cancel")
def cancel_run(conversation_id: UUID, request_id: UUID, account: CurrentAccount, db: DbSession):
    from sqlalchemy import or_, select

    from casepilot_api.models import GenerationJob, WorkbenchRun
    from casepilot_api.workbench_continuation import cancel_run as cancel_durable_run

    store = authorized_store(db, account, conversation_id, request_id)
    run = db.scalar(select(WorkbenchRun).where(
        WorkbenchRun.conversation_id == conversation_id,
        WorkbenchRun.account_id == account.id,
        or_(WorkbenchRun.id == request_id, WorkbenchRun.request_id == request_id),
    ))
    if run is not None:
        if run.status == "completed":
            return {"status": "already_terminal", "transport_aborted": False}
        job_id = run.checkpoint.get("waiting_job_id")
        cancel_durable_run(db, run.id)
        db.commit()  # Cancellation must be visible before any domain lock is awaited.
        store = authorized_store(db, account, conversation_id, run.request_id)
        if job_id:
            from casepilot_api.generation import cancel_generation

            job = db.get(GenerationJob, UUID(str(job_id)))
            if job is not None and str(getattr(job.status, "value", job.status)) in {
                "queued", "running", "awaiting_input",
            }:
                cancel_generation(job.id, account, db)
        from contextlib import suppress

        # Durable cancellation remains authoritative during Redis failure.
        with suppress(RedisError):
            store.client.set(store.key + ":cancel", "1", ex=TTL_SECONDS)
        return {"status": "cancelled", "transport_aborted": False}
    from casepilot_api.workbench_continuation import cancel_initial_reservation

    cancel_initial_reservation(db, account.id, conversation_id, request_id)
    db.commit()
    # Close the race with an initial segment committing while its reservation
    # cancellation waited for the final checkpoint lock.
    committed_run = db.scalar(select(WorkbenchRun).where(
        WorkbenchRun.conversation_id == conversation_id,
        WorkbenchRun.account_id == account.id, WorkbenchRun.request_id == request_id,
    ).execution_options(populate_existing=True))
    if committed_run is not None and committed_run.status != "completed":
        cancel_durable_run(db, committed_run.id)
        db.commit()
    try:
        status = store.request_cancel()
    except RedisError:
        status = "requested"  # The durable tombstone does not depend on Redis.
    return {"status": status, "transport_aborted": False}
