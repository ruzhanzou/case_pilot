"""Offline guard and exact-contract tests; never call providers or services."""

import ast
import json
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import workbench_agent_live_acceptance as transport
import workbench_agent_live_collection_delete as live
import workbench_agent_live_journey as base


class Contracts(unittest.TestCase):
    def test_catalog_preserves_default_and_every_non_target_collection(self):
        default = {"id": "default", "name": "Default"}
        other = {"id": "other", "name": "Protected"}
        target = {"id": "target", "name": "Delete only this"}
        before = [default, target, other]
        live.verify_catalog_removal(before, [other, default], "target")
        for after in (
            [other],
            [default],
            [default, other, target],
            [default, other, {"id": "extra", "name": "Unexpected"}],
            [default, {**other, "name": "Changed"}],
            [default, other, other],
        ):
            with self.assertRaises(base.JourneyFailure):
                live.verify_catalog_removal(before, after, "target")

    def test_shared_guards_refuse_without_optin(self):
        self.assertIs(live.read_key, transport.read_key)
        self.assertIs(live.RequestBudget, transport.RequestBudget)
        output = StringIO()
        with patch.object(live, "execute_delete") as execute, redirect_stdout(output):
            self.assertEqual(live.main([]), 1)
        execute.assert_not_called()
        result = json.loads(output.getvalue())
        self.assertEqual(result["error_code"], "live_permission_required")
        self.assertEqual(result["requests_attempted"], 0)
        self.assertFalse(result["hard_delete_tested"])
        self.assertFalse(result["restore_tested"])

    def test_four_checks_gate_and_credential_redaction(self):
        for count, failed in [(3, False), (4, False), (5, False), (4, True)]:

            async def fake(
                key, model, budget, report, storage, count=count, failed=failed
            ):
                report["checks"] = [{"passed": not failed} for _ in range(count)]

            output = StringIO()
            with (
                patch.object(sys, "stdin", StringIO("offline-private-key\n")),
                patch.object(live, "execute_delete", fake),
                patch.object(Path, "mkdir"),
                redirect_stdout(output),
            ):
                code = live.main(["--allow-live", "--key-stdin"])
            self.assertEqual(code, 0 if count == 4 and not failed else 1)
            self.assertNotIn("offline-private-key", output.getvalue())

        async def fail(*args):
            raise base.JourneyFailure("private-provider-body-offline-private-key")

        output = StringIO()
        with (
            patch.object(sys, "stdin", StringIO("offline-private-key\n")),
            patch.object(live, "execute_delete", fail),
            patch.object(Path, "mkdir"),
            redirect_stdout(output),
        ):
            self.assertEqual(live.main(["--allow-live", "--key-stdin"]), 1)
        self.assertEqual(
            json.loads(output.getvalue())["error_code"],
            "collection_delete_journey_failed",
        )
        self.assertNotIn("private-provider-body", output.getvalue())
        self.assertNotIn("offline-private-key", output.getvalue())

    def test_exact_delete_identity_aggregate_and_actual_receipt(self):
        proposal = {
            "id": "proposal",
            "status": "pending",
            "action": "delete",
            "collection_id": "target",
            "name": "Synthetic",
            "impact": {"member_case_count": 2, "affected_conversation_count": 1},
        }
        turn = {
            "action": {"type": "collection_proposal", "proposal": proposal},
            "assistant_message": {
                "metadata": {
                    "workbench_agent": {
                        "receipts": [{"tool": "delete_collection", "effect": "prepare"}]
                    }
                }
            },
        }
        self.assertIs(live.exact_proposal(turn, "target", "Synthetic", 2), proposal)
        for key, value in [
            ("action", "rename"),
            ("status", "confirmed"),
            ("collection_id", "foreign"),
            ("name", "wrong"),
            ("impact", {"member_case_count": 3, "affected_conversation_count": 1}),
        ]:
            invalid = {
                **turn,
                "action": {**turn["action"], "proposal": {**proposal, key: value}},
            }
            with self.assertRaises(base.JourneyFailure):
                live.exact_proposal(invalid, "target", "Synthetic", 2)
        with self.assertRaises(base.JourneyFailure):
            live.exact_proposal({"action": turn["action"]}, "target", "Synthetic", 2)

    def test_preservation_checks_revisions_memberships_and_asset_state(self):
        before = {"cases": ["live"], "revisions": ["rev"], "memberships": ["shared"]}
        live.preserved(before, dict(before))
        for field in before:
            with self.assertRaises(base.JourneyFailure):
                live.preserved(before, {**before, field: []})

    def test_nl_no_injected_intent_or_ids_and_cli_has_no_scenarios(self):
        tree = ast.parse(Path(live.__file__).read_text())
        messages = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "message"
        ]
        self.assertEqual(len(messages), 1)
        self.assertFalse(messages[0].keywords)
        output = StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as stopped:
            live.main(["--help"])
        self.assertEqual(stopped.exception.code, 0)
        self.assertIn("--key-stdin", output.getvalue())
        self.assertNotIn("--scenarios", output.getvalue())


class DriverContracts(unittest.IsolatedAsyncioTestCase):
    async def test_exact_delegate_budget_identity_and_driver_restoration(self):
        original = base.Journey
        budget, report = transport.RequestBudget(40), {}

        async def execute(
            key, model, received_budget, scenarios, received_report, storage
        ):
            self.assertIs(base.Journey, live.CollectionDeleteJourney)
            self.assertIs(received_budget, budget)
            self.assertIs(received_report, report)
            self.assertEqual(scenarios, {"collection_delete"})
            self.assertEqual(
                (key, model, storage), ("offline", "synthetic", "/tmp/synthetic")
            )

        with patch.object(base, "execute", execute):
            await live.execute_delete(
                "offline", "synthetic", budget, report, "/tmp/synthetic"
            )
        self.assertIs(base.Journey, original)

        async def fail(*args):
            raise ValueError("offline")

        with patch.object(base, "execute", fail), self.assertRaises(ValueError):
            await live.execute_delete(
                "offline", "synthetic", budget, report, "/tmp/synthetic"
            )
        self.assertIs(base.Journey, original)
        self.assertEqual(budget.count, 0)


if __name__ == "__main__":
    unittest.main()
