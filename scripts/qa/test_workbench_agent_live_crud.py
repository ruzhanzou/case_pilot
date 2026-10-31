"""Offline-only auditing of the standalone CRUD acceptance driver."""

import ast
import json
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import httpx
import workbench_agent_live_acceptance as transport
import workbench_agent_live_crud as crud
import workbench_agent_live_journey as base


class CrudContracts(unittest.TestCase):
    def test_reuses_credential_and_budget_guards_and_refuses_no_opt_in(self):
        self.assertIs(crud.read_key, transport.read_key)
        self.assertIs(crud.RequestBudget, transport.RequestBudget)
        output = StringIO()
        with patch.object(crud, "execute_crud") as execute, redirect_stdout(output):
            self.assertEqual(crud.main(["--max-requests", "150"]), 1)
        execute.assert_not_called()
        summary = json.loads(output.getvalue())
        self.assertEqual(summary["error_code"], "live_permission_required")
        self.assertEqual(summary["requests_attempted"], 0)
        self.assertFalse(summary["collection_delete_tested"])

    def test_exact_nine_check_gate_and_private_errors_never_escape(self):
        for count, failing in [(8, False), (9, False), (10, False), (9, True)]:

            async def fake_execute(
                key, model, budget, report, storage, count=count, failing=failing
            ):
                self.assertEqual(key, "offline-private-key")
                report["checks"] = [
                    {"check": "offline", "passed": not failing} for _ in range(count)
                ]

            output = StringIO()
            with (
                patch.object(sys, "stdin", StringIO("offline-private-key\n")),
                patch.object(crud, "execute_crud", fake_execute),
                patch.object(Path, "mkdir"),
                redirect_stdout(output),
            ):
                code = crud.main(
                    ["--allow-live", "--key-stdin", "--max-requests", "150"]
                )
            result = json.loads(output.getvalue())
            expected = count == 9 and not failing
            self.assertEqual(result["passed"], expected)
            self.assertEqual(code, 0 if expected else 1)
            self.assertNotIn("offline-private-key", output.getvalue())

        async def private_error(*args):
            raise base.JourneyFailure("private-provider-body-with-offline-private-key")

        output = StringIO()
        with (
            patch.object(sys, "stdin", StringIO("offline-private-key\n")),
            patch.object(crud, "execute_crud", private_error),
            patch.object(Path, "mkdir"),
            redirect_stdout(output),
        ):
            self.assertEqual(crud.main(["--allow-live", "--key-stdin"]), 1)
        self.assertEqual(
            json.loads(output.getvalue())["error_code"], "crud_journey_failed"
        )
        self.assertNotIn("private-provider-body", output.getvalue())
        self.assertNotIn("offline-private-key", output.getvalue())

    def test_generation_fixture_identity_and_priority_are_checked(self):
        requirement = crud.synthetic_requirements().decode("utf-8")
        self.assertIn(crud.GOOD_MARKER, requirement)
        self.assertIn(crud.BAD_MARKER, requirement)
        good = {"id": "good", "title": crud.GOOD_MARKER, "priority": "P2"}
        bad = {"id": "bad", "title": crud.BAD_MARKER, "priority": "P1"}
        self.assertEqual(crud.identify_generated([bad, good]), (good, bad))
        for invalid in [
            [good],
            [good, {**bad, "priority": "P0"}],
            [good, {**bad, "id": "good"}],
        ]:
            with self.assertRaises(base.JourneyFailure):
                crud.identify_generated(invalid)

    def test_delete_review_binds_one_formal_id_and_exact_revision(self):
        case = {"id": "selected", "current_revision_id": "revision"}
        item = {
            "operation": "delete",
            "target_type": "formal",
            "ref": "selected",
            "test_case_id": "selected",
            "base_revision_id": "revision",
        }
        preview = {"status": "ready", "items": [item]}
        self.assertEqual(
            crud.exact_delete_review(preview, case),
            {"review_refs": ["selected"], "accepted_fields": {"selected": ["delete"]}},
        )
        for invalid in [
            {"status": "ready", "items": [item, item]},
            {"status": "ready", "items": [{**item, "test_case_id": "other"}]},
            {"status": "ready", "items": [{**item, "base_revision_id": "stale"}]},
            {"status": "generating", "items": [item]},
        ]:
            with self.assertRaises(base.JourneyFailure):
                crud.exact_delete_review(invalid, case)

    def test_read_receipt_checks_actual_tool_and_effect(self):
        turn = {
            "assistant_message": {
                "metadata": {
                    "workbench_agent": {
                        "receipts": [{"tool": "query_collections", "effect": "read"}]
                    }
                }
            }
        }
        self.assertTrue(crud.has_receipt(turn, {"query_collections"}, "read"))
        self.assertFalse(crud.has_receipt(turn, {"create_collection"}, "prepare"))
        self.assertFalse(crud.has_receipt({}, {"query_collections"}, "read"))

    def test_no_nl_call_injects_targets_intent_or_selection_and_task_exists(self):
        tree = ast.parse(Path(crud.__file__).read_text())
        messages = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "message"
        ]
        self.assertGreater(len(messages), 5)
        for call in messages:
            self.assertFalse(
                {keyword.arg for keyword in call.keywords}
                & {
                    "targets",
                    "target_case_ids",
                    "target_scope",
                    "intent_override",
                    "selection_version",
                }
            )
        tasks_tree = ast.parse(
            (transport.ROOT / "apps/agent/src/casepilot_agent/tasks.py").read_text()
        )
        self.assertTrue(
            any(
                isinstance(node, ast.FunctionDef)
                and node.name == "answer_knowledge_question"
                for node in tasks_tree.body
            )
        )


class DriverContract(unittest.IsolatedAsyncioTestCase):
    async def test_only_harness_driver_and_task_whitelist_are_scoped(self):
        original_driver, original_tasks = base.Journey, dict(base.TASKS)
        shared_budget, report = transport.RequestBudget(), {}
        calls = []

        async def fake_execute(key, model, budget, scenarios, received_report, storage):
            self.assertIs(base.Journey, crud.CrudJourney)
            self.assertEqual(
                base.TASKS["casepilot.agent.answer_question"],
                "answer_knowledge_question",
            )
            self.assertIs(budget, shared_budget)
            self.assertIs(received_report, report)
            self.assertEqual(
                (key, model, storage),
                ("offline-placeholder", "synthetic", "/tmp/synthetic"),
            )
            calls.append(scenarios)

        with patch.object(base, "execute", fake_execute):
            await crud.execute_crud(
                "offline-placeholder",
                "synthetic",
                shared_budget,
                report,
                "/tmp/synthetic",
            )
        self.assertEqual(calls, [{"crud_continuous"}])
        self.assertIs(base.Journey, original_driver)
        self.assertEqual(base.TASKS, original_tasks)

        async def fail_execute(*args):
            raise ValueError("offline-failure")

        with patch.object(base, "execute", fail_execute), self.assertRaises(ValueError):
            await crud.execute_crud(
                "offline-placeholder",
                "synthetic",
                shared_budget,
                report,
                "/tmp/synthetic",
            )
        self.assertIs(base.Journey, original_driver)
        self.assertEqual(base.TASKS, original_tasks)

    async def test_shared_transport_clients_close_without_network(self):
        class ClosedTransport(httpx.AsyncBaseTransport):
            closed = False

            async def handle_async_request(self, request):
                raise AssertionError("offline-test-must-not-request")

            async def aclose(self):
                self.closed = True

        inner = ClosedTransport()
        budget = transport.RequestBudget()
        with patch.object(transport, "environment_http_transport", return_value=inner):
            async with transport.bounded_clients("offline-placeholder", budget):
                from openai import AsyncOpenAI

                client = AsyncOpenAI()
        self.assertTrue(client.is_closed())
        self.assertTrue(inner.closed)
        self.assertEqual(budget.count, 0)


if __name__ == "__main__":
    unittest.main()
