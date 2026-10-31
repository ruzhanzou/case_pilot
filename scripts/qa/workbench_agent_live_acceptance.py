#!/usr/bin/env python3
"""Opt-in synthetic Responses/Agents SDK contract; not application E2E.

Credentials are accepted only from piped stdin or transient VOLCENGINE_API_KEY.
No credential lookup, persisted credential, model text, reasoning, or payload logs.
stdout is sanitized JSONL (bounded HTTP observations, then one final summary).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import logging
import os
import ssl
import sys
import threading
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path
from time import monotonic
from unittest.mock import patch
from urllib.request import getproxies, proxy_bypass

import httpx

os.environ["ORT_DISABLE_TELEMETRY"] = "1"
BASE_URL = "https://ark.cn-beijing.volces.com/api/v3/"
MODEL = "doubao-seed-2-0-lite-260428"
ROOT = Path(__file__).resolve().parents[2]
STAGE = ContextVar("acceptance_stage", default="unspecified")
STAGES = frozenset(
    {
        "nl_sampling_submit",
        "sampling_draft_worker",
        "text_sdk_tool_loop",
        "image_sdk_tool_loop",
        "generation_contract",
        "feature.generated",
        "test_point.generated",
        "planning_coverage_completion",
        "rewrite_contract",
        "setup",
        "generation_request",
        "brief_worker",
        "brief_confirm",
        "generation_worker",
        "adoption",
        "rewrite_request",
        "rewrite_confirm",
        "rewrite_worker",
        "rewrite_apply",
        "cancel_request",
        "asset_query",
        "asset_reuse",
        "asset_confirm",
        "gap_generation",
        "gap_selection",
        "gap_rewrite",
        "selection_update",
        "selection_stale_apply",
        "spreadsheet_upload",
        "spreadsheet_index",
        "spreadsheet_select",
        "spreadsheet_rewrite",
        "image_upload",
        "image_index",
        "image_question",
    }
)
PROVIDER_CODES = frozenset(
    {
        "ModelNotOpen",
        "InvalidApiKey",
        "InvalidAPIKey",
        "AuthenticationError",
        "AuthenticationFailed",
        "InvalidParameter",
        "InvalidParameterValue",
        "MissingParameter",
        "PermissionDenied",
        "AccessDenied",
        "ModelNotFound",
        "NotFound",
        "RateLimitExceeded",
        "TooManyRequests",
        "QuotaExceeded",
        "InsufficientQuota",
        "InternalServerError",
        "ServiceUnavailable",
        "InvalidEndpointOrModel.NotFound",
        "InvalidEndpointOrModel.Disabled",
    }
)
EXCEPTION_NAMES = frozenset(
    {
        "ConnectError",
        "ConnectTimeout",
        "ReadError",
        "ReadTimeout",
        "WriteError",
        "WriteTimeout",
        "PoolTimeout",
        "ProxyError",
        "RemoteProtocolError",
        "LocalProtocolError",
        "UnsupportedProtocol",
        "SSLError",
        "SSLCertVerificationError",
        "APIConnectionError",
        "APITimeoutError",
        "APIStatusError",
        "BadRequestError",
        "AuthenticationError",
        "PermissionDeniedError",
        "NotFoundError",
        "RateLimitError",
        "InternalServerError",
        "UnprocessableEntityError",
        "ModelBehaviorError",
        "MaxTurnsExceeded",
        "AgentProviderError",
        "SafetyStop",
        "TimeoutError",
        "ConnectionError",
        "ValidationError",
        "StageContractError",
        "ValueError",
        "TypeError",
        "KeyError",
        "RuntimeError",
        "AttributeError",
        "AssertionError",
        "IndexError",
        "LookupError",
    }
)
OUTPUT_TYPES = frozenset(
    {"message", "function_call", "reasoning", "function_call_output"}
)


class SafetyStop(Exception):
    pass


def set_stage(value):
    return STAGE.set(value if value in STAGES else "unspecified")


def exception_name(error):
    name = type(error).__name__
    return name if name in EXCEPTION_NAMES else "unrecognized"


def ssl_code(error):
    seen = set()
    while error is not None and id(error) not in seen and len(seen) < 12:
        seen.add(id(error))
        if isinstance(error, ssl.SSLCertVerificationError):
            value = getattr(error, "verify_code", None)
            return value if type(value) is int else None
        error = error.__cause__ or error.__context__
    return None


def disable_sensitive_logging():
    logging.disable(logging.CRITICAL)
    for name in (
        "OPENAI_AGENTS_DISABLE_TRACING",
        "OPENAI_AGENTS_DONT_LOG_MODEL_DATA",
        "OPENAI_AGENTS_DONT_LOG_TOOL_DATA",
        "ORT_DISABLE_TELEMETRY",
    ):
        os.environ[name] = "1"


class RequestBudget:
    def __init__(self, limit=20, emit=None):
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("budget_invalid")
        self.limit, self.count, self.lock = limit, 0, threading.Lock()
        self.started = monotonic()
        self.stop_code = None
        self.usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        self.calls = []
        self.emit = emit
        self.before_request = None
        self.diagnostics = {
            "http_status": None,
            "provider_code": None,
            "transport_exception": None,
            "ssl_verification_code": None,
            "sdk_exception": None,
            "response_status": None,
            "output_types": [],
        }

    def stop(self, code):
        with self.lock:
            self.stop_code = self.stop_code or code
        raise SafetyStop(code)

    def reserve(self):
        with self.lock:
            if self.stop_code:
                raise SafetyStop(self.stop_code)
            if self.count >= self.limit:
                self.stop_code = "request_budget_exhausted"
                raise SafetyStop(self.stop_code)
            self.count += 1
            record = {
                "event": "http_attempt",
                "number": self.count,
                "stage": STAGE.get() if STAGE.get() in STAGES else "unspecified",
                "http_status": None,
                "elapsed_seconds": None,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            }
            self.calls.append(record)
            if self.before_request is not None:
                self.before_request(record)
            return record

    def summary(self):
        return {
            "requests_attempted": self.count,
            "request_limit": self.limit,
            "usage": self.usage,
            "diagnostics": self.diagnostics,
            "elapsed_seconds": round(monotonic() - self.started, 3),
        }


class CountingAsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self, budget, inner):
        self.budget, self.inner = budget, inner

    async def handle_async_request(self, request):
        url = request.url
        if (
            url.scheme != "https"
            or url.host != "ark.cn-beijing.volces.com"
            or url.port not in (None, 443)
            or url.path != "/api/v3/responses"
            or url.query
            or url.fragment
            or url.userinfo
            or request.method != "POST"
        ):
            self.budget.stop("endpoint_rejected")
        try:
            body = json.loads(await request.aread())
        except (ValueError, httpx.HTTPError):
            self.budget.stop("request_contract_invalid")
        if (
            not isinstance(body, dict)
            or body.get("store") is not False
            or body.get("stream", False) is not False
        ):
            self.budget.stop("privacy_contract_invalid")
        tokens = body.get("max_output_tokens")
        if type(tokens) is not int or not 512 <= tokens <= 32768:
            self.budget.stop("output_budget_invalid")
        if any(tool.get("type") != "function" for tool in body.get("tools", [])):
            self.budget.stop("hosted_tool_rejected")
        for item in (
            body.get("input", []) if isinstance(body.get("input"), list) else []
        ):
            content = item.get("content") if isinstance(item, dict) else None
            for part in content if isinstance(content, list) else []:
                if part.get("type") == "input_image" and not part.get(
                    "image_url", ""
                ).startswith("data:image/png;base64,"):
                    self.budget.stop("external_image_rejected")
        record, started = self.budget.reserve(), monotonic()
        try:
            return await self._send(request, record)
        finally:
            record["elapsed_seconds"] = round(monotonic() - started, 3)
            if self.budget.emit:
                with self.budget.lock:
                    self.budget.emit(dict(record))

    async def _send(self, request, record):
        try:
            response = await self.inner.handle_async_request(request)
        except Exception as exc:
            self.budget.diagnostics.update(
                transport_exception=exception_name(exc),
                ssl_verification_code=ssl_code(exc),
            )
            raise
        record["http_status"] = response.status_code
        self.budget.diagnostics["http_status"] = response.status_code
        if 300 <= response.status_code < 400:
            await response.aclose()
            self.budget.stop("redirect_rejected")
        try:
            data = json.loads(await response.aread())
        except (ValueError, httpx.HTTPError):
            self.budget.stop("response_contract_invalid")
        if not isinstance(data, dict):
            self.budget.stop("response_contract_invalid")
        if response.status_code >= 400:
            error = data.get("error", data)
            code = error.get("code") if isinstance(error, dict) else None
            self.budget.diagnostics["provider_code"] = (
                code
                if isinstance(code, str) and code in PROVIDER_CODES
                else "unrecognized"
            )
        else:
            status = data.get("status")
            self.budget.diagnostics["response_status"] = (
                status
                if status
                in {
                    "completed",
                    "incomplete",
                    "failed",
                    "queued",
                    "in_progress",
                    "cancelled",
                }
                else "unrecognized"
            )
            output = data.get("output")
            self.budget.diagnostics["output_types"] = (
                sorted(
                    {
                        item.get("type")
                        if item.get("type") in OUTPUT_TYPES
                        else "unrecognized"
                        for item in output
                        if isinstance(item, dict)
                    }
                )
                if isinstance(output, list)
                else []
            )
            usage = data.get("usage")
            with self.budget.lock:
                for name in self.budget.usage:
                    value = usage.get(name, 0) if isinstance(usage, dict) else 0
                    if type(value) is int and value >= 0:
                        record[name] = value
                        self.budget.usage[name] += value
            if status != "completed":
                await response.aclose()
                self.budget.stop("provider_incomplete_response")
        return response

    async def aclose(self):
        await self.inner.aclose()


def environment_http_transport():
    proxies = getproxies()
    proxy = (
        None
        if proxy_bypass("ark.cn-beijing.volces.com")
        else proxies.get("https") or proxies.get("all")
    )
    # A custom transport disables AsyncClient's automatic environment proxy mounts.
    # Explicit proxy plus trust_env honors platform routing and SSL_CERT_FILE/DIR.
    return httpx.AsyncHTTPTransport(proxy=proxy, verify=True, trust_env=True, retries=0)


@asynccontextmanager
async def bounded_clients(key, budget):
    import openai

    original = openai.AsyncOpenAI
    clients = []

    class ObservedClient(original):
        async def request(self, *args, **kwargs):
            try:
                return await super().request(*args, **kwargs)
            except Exception as exc:
                budget.diagnostics["sdk_exception"] = exception_name(exc)
                raise

    def factory(*args, **kwargs):
        if args:
            budget.stop("client_factory_invalid")
        kwargs.update(
            api_key=key,
            base_url=BASE_URL,
            max_retries=0,
            timeout=90,
            http_client=httpx.AsyncClient(
                transport=CountingAsyncTransport(budget, environment_http_transport()),
                follow_redirects=False,
                trust_env=False,
                timeout=90,
            ),
        )
        client = ObservedClient(**kwargs)
        clients.append(client)
        return client

    with patch.object(openai, "AsyncOpenAI", factory):
        try:
            yield
        finally:
            for client in clients:
                if not client.is_closed():
                    try:
                        await client.close()
                    except Exception as exc:  # noqa: BLE001 -- No exception text may expose credentials.
                        budget.diagnostics["cleanup_exception"] = exception_name(exc)


def synthetic_png():
    from PIL import Image

    stream = io.BytesIO()
    Image.new("RGB", (128, 128), (255, 0, 0)).save(stream, format="PNG")
    return stream.getvalue()


async def provider_acceptance(key, model, budget, report):
    from agents import (
        Agent,
        ModelSettings,
        OpenAIResponsesModel,
        RunConfig,
        Runner,
        function_tool,
        set_tracing_disabled,
    )
    from pydantic import BaseModel

    set_tracing_disabled(True)
    config = RunConfig(tracing_disabled=True, trace_include_sensitive_data=False)
    settings = ModelSettings(store=False, max_tokens=8192, parallel_tool_calls=False)
    async with bounded_clients(key, budget):
        from openai import AsyncOpenAI

        client = AsyncOpenAI()
        sdk_model = OpenAIResponsesModel(model=model, openai_client=client)
        for mode in ("text", "image"):
            set_stage(mode + "_sdk_tool_loop")
            observed = []

            @function_tool
            def synthetic_lookup(identifier: str) -> str:
                """Read only the synthetic local fixture, with no network or writes."""
                observed.append(identifier)  # noqa: B023 -- Each SDK loop is fully awaited before advancing.
                return "SYNTHETIC_OK"

            agent = Agent(
                name="Synthetic acceptance",
                instructions="Follow the synthetic user task. Use only the supplied local tool.",
                model=sdk_model,
                model_settings=settings,
                tools=[synthetic_lookup],
            )
            content = [
                {
                    "type": "input_text",
                    "text": "Call synthetic_lookup exactly once with identifier SYNTHETIC-1, then include its token in your final answer."
                    + (
                        " Identify the image color in English."
                        if mode == "image"
                        else ""
                    ),
                }
            ]
            if mode == "image":
                content.append(
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,"
                        + base64.b64encode(synthetic_png()).decode("ascii"),
                    }
                )
            result = await Runner.run(
                agent,
                [{"role": "user", "content": content}],
                max_turns=4,
                run_config=config,
            )
            text = str(result.final_output or "")
            ok = (
                observed == ["SYNTHETIC-1"]
                and "SYNTHETIC_OK" in text
                and (mode != "image" or "red" in text.lower())
            )
            report["checks"].append(
                {
                    "check": mode + "_sdk_tool_loop",
                    "passed": ok,
                    "tool_count": len(observed),
                }
            )
            if not ok:
                raise SafetyStop("sdk_loop_acceptance_failed")

        class SyntheticCase(BaseModel):
            case_id: str
            title: str
            steps: list[str]
            expected: str

        agent = Agent(
            name="Synthetic structured contract",
            instructions="Return exactly the requested structured synthetic test case.",
            model=sdk_model,
            model_settings=settings,
            output_type=SyntheticCase,
        )
        set_stage("generation_contract")
        generated = (
            await Runner.run(
                agent,
                "Create one test: case_id SYNTHETIC-1; login accepts password demo. Include title, steps, expected.",
                max_turns=3,
                run_config=config,
            )
        ).final_output
        ok = (
            generated.case_id == "SYNTHETIC-1"
            and bool(generated.steps)
            and bool(generated.expected)
        )
        report["checks"].append(
            {"check": "generation_structured_provider_contract", "passed": ok}
        )
        if not ok:
            raise SafetyStop("generation_contract_failed")
        set_stage("rewrite_contract")
        rewritten = (
            await Runner.run(
                agent,
                "Preserve case_id, steps and expected; set title exactly SYNTHETIC REVISED. Input: "
                + generated.model_dump_json(),
                max_turns=3,
                run_config=config,
            )
        ).final_output
        ok = (
            rewritten.case_id == generated.case_id
            and rewritten.expected == generated.expected
            and rewritten.steps == generated.steps
            and rewritten.title == "SYNTHETIC REVISED"
        )
        report["checks"].append(
            {"check": "rewrite_structured_provider_contract", "passed": ok}
        )
        if not ok:
            raise SafetyStop("rewrite_contract_failed")


def parser(description=__doc__):
    result = argparse.ArgumentParser(description=description)
    result.add_argument("--allow-live", action="store_true")
    result.add_argument("--key-stdin", action="store_true")
    result.add_argument("--model", default=MODEL)
    result.add_argument("--max-requests", type=int, choices=range(1, 201), default=20)
    return result


def read_key(args):
    if not args.allow_live:
        raise SafetyStop("live_permission_required")
    if args.key_stdin and sys.stdin.isatty():
        raise SafetyStop("stdin_must_be_noninteractive")
    key = (
        sys.stdin.readline(16384).strip()
        if args.key_stdin
        else os.environ.pop("VOLCENGINE_API_KEY", "")
    )
    if not key or len(key) > 8192 or any(c.isspace() for c in key):
        raise SafetyStop("credential_missing_or_invalid")
    return key


def emit_json(value):
    print(json.dumps(value, separators=(",", ":")), flush=True)


def main(argv=None):
    args = parser().parse_args(argv)
    disable_sensitive_logging()
    budget = RequestBudget(args.max_requests, emit_json)
    report = {
        "event": "summary",
        "scope": "synthetic_sdk_provider_contract_only",
        "app_domain_e2e": False,
        "passed": False,
        "checks": [],
    }
    key = ""
    try:
        key = read_key(args)
        asyncio.run(provider_acceptance(key, args.model, budget, report))
        report["passed"] = len(report["checks"]) == 4 and all(
            c["passed"] for c in report["checks"]
        )
    except Exception as exc:  # noqa: BLE001 -- Emit only local constant codes or allowlisted classes.
        known = {
            "live_permission_required",
            "stdin_must_be_noninteractive",
            "credential_missing_or_invalid",
            "sdk_loop_acceptance_failed",
            "generation_contract_failed",
            "rewrite_contract_failed",
        }
        code = exc.args[0] if isinstance(exc, SafetyStop) and exc.args else None
        report["error_code"] = budget.stop_code or (
            code if code in known else "provider_acceptance_failed"
        )
        report["exception_class"] = exception_name(exc)
    finally:
        key = ""
    report.update(budget.summary())
    emit_json(report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
