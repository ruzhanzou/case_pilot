"""Offline contract checks; every HTTP request terminates in MockTransport."""

import json
import ssl
import threading
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import httpx
import workbench_agent_live_acceptance as live


class TransportContracts(unittest.IsolatedAsyncioTestCase):
    async def send(
        self,
        budget,
        *,
        url=live.BASE_URL + "responses",
        status=200,
        response_status="completed",
        body=None,
        handler=None,
    ):
        handler = handler or (
            lambda request: httpx.Response(
                status,
                json={"status": response_status},
                headers={"Location": "https://example.test"},
            )
        )
        async with httpx.AsyncClient(
            transport=live.CountingAsyncTransport(budget, httpx.MockTransport(handler)),
            follow_redirects=False,
        ) as client:
            return await client.post(
                url, json=body or {"store": False, "max_output_tokens": 8192}
            )

    async def test_global_limit_across_clients_and_threads(self):
        budget = live.RequestBudget(20)
        for _ in range(20):
            await self.send(budget)
        with self.assertRaises(live.SafetyStop):
            await self.send(budget)
        self.assertEqual(budget.count, 20)
        self.assertEqual(len(budget.calls), 20)
        budget = live.RequestBudget(20)

        def reserve():
            try:
                budget.reserve()
            except live.SafetyStop:
                pass

        threads = [threading.Thread(target=reserve) for _ in range(100)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(budget.count, 20)

    async def test_host_path_port_tls_redirect_guards(self):
        for url in [
            "http://ark.cn-beijing.volces.com/api/v3/responses",
            "https://example.test/api/v3/responses",
            "https://ark.cn-beijing.volces.com:444/api/v3/responses",
            live.BASE_URL + "chat/completions",
            live.BASE_URL + "responses?x=1",
        ]:
            budget = live.RequestBudget()
            with self.assertRaises(live.SafetyStop):
                await self.send(budget, url=url)
            self.assertEqual(budget.count, 0)
        budget = live.RequestBudget()
        with self.assertRaises(live.SafetyStop):
            await self.send(budget, status=307)
        self.assertEqual(budget.count, 1)
        self.assertEqual(budget.stop_code, "redirect_rejected")

    async def test_store_output_budget_search_and_incomplete_fail_closed(self):
        for body in [
            {"store": True, "max_output_tokens": 8192},
            {"store": False},
            {
                "store": False,
                "max_output_tokens": 8192,
                "tools": [{"type": "web_search"}],
            },
            {"store": False, "max_output_tokens": 8192, "stream": True},
        ]:
            budget = live.RequestBudget()
            with self.assertRaises(live.SafetyStop):
                await self.send(budget, body=body)
            self.assertEqual(budget.count, 0)
        budget = live.RequestBudget()
        with self.assertRaises(live.SafetyStop):
            await self.send(budget, response_status="incomplete")
        with self.assertRaises(live.SafetyStop):
            await self.send(budget)
        self.assertEqual(budget.count, 1)

    async def test_sanitized_error_and_usage_telemetry(self):
        budget = live.RequestBudget()
        await self.send(
            budget,
            handler=lambda request: httpx.Response(
                404,
                json={
                    "error": {"code": "ModelNotOpen", "message": "never-report-secret"}
                },
            ),
        )
        self.assertEqual(budget.diagnostics["provider_code"], "ModelNotOpen")
        await self.send(
            budget,
            handler=lambda request: httpx.Response(
                400, json={"error": {"code": "never-report-secret"}}
            ),
        )
        self.assertEqual(budget.diagnostics["provider_code"], "unrecognized")
        token = live.set_stage("asset_query")
        try:
            await self.send(
                budget,
                handler=lambda request: httpx.Response(
                    200,
                    json={
                        "status": "completed",
                        "usage": {
                            "input_tokens": 3,
                            "output_tokens": 4,
                            "total_tokens": 7,
                        },
                        "output": [{"type": "message", "text": "never-report-secret"}],
                    },
                ),
            )
        finally:
            live.STAGE.reset(token)
        self.assertEqual(budget.calls[-1]["stage"], "asset_query")
        self.assertEqual(budget.usage["total_tokens"], 7)
        self.assertNotIn(
            "never-report-secret", json.dumps([budget.calls, budget.summary()])
        )

    async def test_real_sdk_text_image_and_structured_loops_without_network(self):
        generated = {
            "case_id": "SYNTHETIC-1",
            "title": "Login",
            "steps": ["Enter demo"],
            "expected": "Accepted",
        }
        revised = {**generated, "title": "SYNTHETIC REVISED"}
        texts = [
            None,
            "SYNTHETIC_OK",
            None,
            "SYNTHETIC_OK red",
            json.dumps(generated),
            json.dumps(revised),
        ]
        seen = []

        def respond(request):
            index = len(seen)
            seen.append(json.loads(request.content))
            text = texts[index]
            output = (
                [
                    {
                        "type": "function_call",
                        "id": f"fc_{index}",
                        "call_id": f"call_{index}",
                        "name": "synthetic_lookup",
                        "arguments": '{"identifier":"SYNTHETIC-1"}',
                    }
                ]
                if text is None
                else [
                    {
                        "type": "message",
                        "id": f"msg_{index}",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": text, "annotations": []}
                        ],
                    }
                ]
            )
            return httpx.Response(
                200,
                json={
                    "id": f"resp_{index}",
                    "object": "response",
                    "created_at": 1,
                    "status": "completed",
                    "model": live.MODEL,
                    "output": output,
                    "parallel_tool_calls": False,
                    "tool_choice": "auto",
                    "tools": [],
                    "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                },
            )

        budget, report = live.RequestBudget(), {"checks": []}
        with patch.object(
            httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(respond)
        ):
            await live.provider_acceptance(
                "offline-placeholder", live.MODEL, budget, report
            )
        self.assertEqual(budget.count, 6)
        self.assertEqual(len(report["checks"]), 4)
        self.assertTrue(all(c["passed"] for c in report["checks"]))
        self.assertTrue(
            all(r["store"] is False and r["max_output_tokens"] == 8192 for r in seen)
        )

    async def test_ssl_and_sdk_exception_diagnostics(self):
        from openai import APIConnectionError
        def fail(request):
            error = ssl.SSLCertVerificationError(1, "never-report-secret")
            error.verify_code = 62
            raise httpx.ConnectError("never-report-secret", request=request) from error

        budget = live.RequestBudget()
        with (
            patch.object(
                httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(fail)
            ),
            self.assertRaises(APIConnectionError),
        ):
            await live.provider_acceptance(
                "offline-placeholder", live.MODEL, budget, {"checks": []}
            )
        self.assertEqual(budget.count, 1)
        self.assertEqual(budget.diagnostics["ssl_verification_code"], 62)
        self.assertEqual(budget.diagnostics["sdk_exception"], "APIConnectionError")
        self.assertNotIn("never-report-secret", json.dumps(budget.summary()))


class EntryContracts(unittest.TestCase):
    def test_opt_in_guard_never_reads_key_or_executes(self):
        stream = StringIO()
        with patch.object(live, "provider_acceptance") as run, redirect_stdout(stream):
            self.assertEqual(live.main([]), 1)
        run.assert_not_called()
        report = json.loads(stream.getvalue())
        self.assertEqual(report["error_code"], "live_permission_required")
        self.assertEqual(report["requests_attempted"], 0)

    def test_proxy_and_tls_environment_honored(self):
        for bypass, expected in [(False, "http://proxy.test:8080"), (True, None)]:
            with (
                patch.object(
                    live, "getproxies", return_value={"https": "http://proxy.test:8080"}
                ),
                patch.object(live, "proxy_bypass", return_value=bypass),
                patch.object(httpx, "AsyncHTTPTransport") as transport,
            ):
                live.environment_http_transport()
            transport.assert_called_once_with(
                proxy=expected, verify=True, trust_env=True, retries=0
            )

    def test_hard_max(self):
        for value in [0, 201, True]:
            with self.assertRaises(ValueError):
                live.RequestBudget(value)


if __name__ == "__main__":
    live.disable_sensitive_logging()
    unittest.main()
