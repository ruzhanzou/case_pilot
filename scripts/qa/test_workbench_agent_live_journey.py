"""Offline script contracts only; no database, model, credential, or service access."""

import asyncio
import json
import os
import sys
import unittest
from contextlib import ExitStack, redirect_stdout
from io import BytesIO, StringIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import workbench_agent_live_journey as journey
from openpyxl import load_workbook
from PIL import Image


class JourneyContracts(unittest.TestCase):
    def test_preview_scope_rejects_old_extra_case_and_wrong_revision(self):
        cases = {"a": {"id": "a", "current_revision_id": "ra"}}
        item = {
            "target_type": "formal",
            "test_case_id": "a",
            "ref": "a",
            "base_revision_id": "ra",
        }
        journey.validate_preview_scope({"status": "ready", "items": [item]}, cases)
        for items in (
            [item, {**item, "test_case_id": "b", "ref": "b"}],
            [{**item, "base_revision_id": "old"}],
            [{**item, "operation": "delete"}],
            [{**item, "ref": "b"}],
        ):
            with self.assertRaises(journey.JourneyFailure):
                journey.validate_preview_scope(
                    {"status": "ready", "items": items}, cases
                )

    def test_preview_accepts_explicit_confirmation_or_actual_compute_artifact(self):
        confirmed = {
            "assistant_message": {
                "metadata": {"modification_confirmation": {"required": True}}
            }
        }
        self.assertTrue(journey.preview_requires_confirmation(confirmed, {}))
        self.assertFalse(
            journey.preview_requires_confirmation({"action": {"job_id": "actual"}}, {})
        )
        self.assertFalse(
            journey.preview_requires_confirmation(
                {}, {"related_change_set_id": "actual"}
            )
        )
        for turn, operation in (
            ({}, {}),
            ({"action": {"status": "queued"}}, {"status": "queued"}),
        ):
            with self.assertRaises(journey.JourneyFailure):
                journey.preview_requires_confirmation(turn, operation)

    def test_priority_review_requires_actual_requested_diff_before_human_apply(self):
        diff = {"field": "priority", "before": "P2", "after": "P1"}
        journey.validate_priority_diff({"items": [{"field_diff": [diff]}]}, "P1")
        for items in (
            [],
            [{"field_diff": []}],
            [{"field_diff": [{**diff, "after": "P0"}]}],
            [{"field_diff": [diff, diff]}],
        ):
            with self.assertRaises(journey.JourneyFailure):
                journey.validate_priority_diff({"items": items}, "P1")

    def test_candidate_ready_preview_binds_exact_ref_and_version(self):
        candidate = {"ref": "uploaded-draft", "version": 3}
        item = {"ref": "uploaded-draft", "target_type": "candidate", "base_version": 3}
        journey.validate_candidate_preview(
            {"status": "ready", "items": [item]}, candidate
        )
        for preview in (
            {"status": "generating", "items": [item]},
            {"status": "ready", "items": [item, item]},
            {"status": "ready", "items": [{**item, "ref": "other"}]},
            {"status": "ready", "items": [{**item, "base_version": 2}]},
            {"status": "ready", "items": [{**item, "target_type": "formal"}]},
        ):
            with self.assertRaises(journey.JourneyFailure):
                journey.validate_candidate_preview(preview, candidate)

    def test_single_operation_rejects_missing_artifact_and_ambiguous_scope(self):
        actual = {"id": "operation", "related_job_id": "job"}
        self.assertEqual(
            journey.single_prepared_operation(
                {"operation_plan": {"operations": [actual]}}
            ),
            actual,
        )
        for turn in (
            {},
            {"operation_plan": None},
            {
                "operation_plan": {
                    "operations": [{"id": "operation", "status": "queued"}]
                }
            },
            {"operation_plan": {"operations": [actual, actual]}},
        ):
            with self.assertRaises(journey.JourneyFailure):
                journey.single_prepared_operation(turn)

    def test_semantic_fixture_hides_meaning_in_description_and_steps_not_title(self):
        with patch.object(sys, "path", [str(journey.ROOT / "apps/api/src"), *sys.path]):
            from casepilot_api.schemas import TestCaseCreate
        bad = journey.semantic_case_payload("SYNTHETIC-ITEM-X17", True)
        good = journey.semantic_case_payload("SYNTHETIC-ITEM-Y42", False)
        for payload in (bad, good):
            TestCaseCreate.model_validate(payload)
            self.assertTrue(payload["title"].isascii())
            self.assertNotIn("BAD", payload["title"])
            self.assertNotIn("GOOD", payload["title"])
        self.assertIn("拒绝登录", bad["steps"][0]["expected"])
        self.assertIn("成功", good["steps"][0]["expected"])
        self.assertNotEqual(bad["description"], good["description"])

    def test_semantic_read_state_rejects_foreign_catalog_destination_and_writes(self):
        valid = {
            "collection_id": "current",
            "context": {
                "workbench_plan": {
                    "source_catalog": {"asset:bad": {}, "asset:good": {}}
                }
            },
        }
        journey.verify_semantic_read_state(
            valid, "current", {"bad", "good"}, {"foreign", "other"}
        )
        for invalid in (
            {**valid, "collection_id": "other"},
            {**valid, "candidates": [{}]},
            {**valid, "operation_history": [{"id": "write"}]},
            {
                **valid,
                "context": {
                    "workbench_plan": {"source_catalog": {"asset:foreign": {}}}
                },
            },
            {
                **valid,
                "context": {
                    "workbench_plan": {"source_catalog": {"asset:unknown": {}}}
                },
            },
        ):
            with self.assertRaises(journey.JourneyFailure):
                journey.verify_semantic_read_state(
                    invalid, "current", {"bad", "good"}, {"foreign", "other"}
                )

    def test_safe_query_counts_and_typed_terminal_never_emit_content(self):
        diagnostic = journey.runtime_diagnostics(
            {
                "events": [
                    {
                        "type": "tool_completed",
                        "tool": "query_assets",
                        "returned_count": 0,
                        "truncated": False,
                        "has_more": False,
                        "content": "private-content",
                    },
                    {
                        "type": "run_completed",
                        "final_kind": "answer",
                        "final_effect": "read",
                        "message": "private-content",
                    },
                ]
            }
        )
        self.assertEqual(
            diagnostic["query_returned_counts"],
            [
                {
                    "tool": "query_assets",
                    "returned_count": 0,
                    "truncated": False,
                    "has_more": False,
                }
            ],
        )
        self.assertEqual(diagnostic["final_kind"], "answer")
        self.assertEqual(diagnostic["final_effect"], "read")
        self.assertNotIn("private-content", json.dumps(diagnostic))
        unknown = journey.runtime_diagnostics(
            {
                "events": [
                    {
                        "type": "run_completed",
                        "final_kind": ["private"],
                        "final_effect": "private",
                    }
                ]
            }
        )
        self.assertIsNone(unknown["final_kind"])
        self.assertIsNone(unknown["final_effect"])

    def test_operation_binding_is_strictly_nested_payload_not_legacy_top_level(self):
        state = {"version": 4}
        operation = {
            "payload": {
                "selection_version": 4,
                "destination_collection_id": "collection",
            }
        }
        journey.validate_operation_binding(operation, state, "collection")
        for invalid in (
            {"selection_version": 4, "destination_collection_id": "collection"},
            {
                "payload": {
                    "selection_version": 3,
                    "destination_collection_id": "collection",
                }
            },
            {"payload": {"selection_version": 4, "destination_collection_id": "other"}},
            {
                "payload": {
                    "selection_version": "4",
                    "destination_collection_id": "collection",
                }
            },
            {"payload": {"selection_version": 4}},
        ):
            with self.assertRaises(journey.JourneyFailure):
                journey.validate_operation_binding(invalid, state, "collection")

    def test_new_reuse_destination_is_observed_catalog_delta_not_precreated(self):
        before = [
            {"id": "default", "name": "Default"},
            {"id": "source", "name": "Source"},
        ]
        target = {"id": "new", "name": "Destination"}
        self.assertEqual(
            journey.created_destination(before, [*before, target], "Destination"),
            target,
        )
        for after in (
            before,
            [target],
            [*before, {**target, "name": "Wrong"}],
            [*before, target, {"id": "extra", "name": "Unexpected"}],
        ):
            with self.assertRaises(journey.JourneyFailure):
                journey.created_destination(before, after, "Destination")
        self.assertEqual(
            journey.safe_code("generation_new_collection_required"),
            "generation_new_collection_required",
        )

    def test_mixed_candidate_adoption_names_exact_ids_and_versions(self):
        candidates = [{"id": "reused", "version": 2}, {"id": "new-gap", "version": 3}]
        self.assertEqual(
            journey.exact_candidate_commit(candidates),
            {
                "candidate_ids": ["reused", "new-gap"],
                "candidate_versions": {"reused": 2, "new-gap": 3},
            },
        )
        for invalid in (
            [],
            [candidates[0], candidates[0]],
            [{"id": "gap"}],
            [{"id": "gap", "version": 0}],
        ):
            with self.assertRaises(journey.JourneyFailure):
                journey.exact_candidate_commit(invalid)

    def test_execute_configuration_matches_actual_backend_fields_without_network(self):
        with patch.object(
            sys,
            "path",
            [
                str(journey.ROOT / "apps/api/src"),
                str(journey.ROOT / "apps/agent/src"),
                *sys.path,
            ],
        ):
            from casepilot_agent.config import AgentSettings
            from casepilot_api.config import Settings
        with patch.dict(
            os.environ,
            {"CASEPILOT_AGENT_PROVIDER": "mock", "CASEPILOT_AI_MODE": "mock"},
        ):
            api, worker = Settings(_env_file=None), AgentSettings(_env_file=None)
        with ExitStack() as stack:
            for settings, values in zip(
                (api, worker),
                journey.configuration_overrides(
                    "offline-placeholder", "synthetic-model", "/tmp/synthetic-storage"
                ),
                strict=True,
            ):
                for name, value in values.items():
                    self.assertTrue(hasattr(settings, name), name)
                    stack.enter_context(patch.object(settings, name, value))
            self.assertEqual(api.ai_mode, "live")
            self.assertTrue(api.is_agent_model_allowed("synthetic-model"))
            self.assertEqual(api.agent_provider, "openai_compatible")
            self.assertEqual(worker.provider, "openai_compatible")
            self.assertEqual(api.agent_api_type, "responses")
            self.assertEqual(worker.api_type, "responses")
            self.assertFalse(api.agent_tracing_enabled)
            self.assertFalse(worker.tracing_enabled)
            self.assertEqual(worker.embedding_provider, "disabled")

    def test_exact_canonical_selection_and_mixed_gap_identity(self):
        case = {"current_revision_id": "revision"}
        state = {
            "context": {
                "workbench_selection": {
                    "version": 2,
                    "active_collection_id": "collection",
                    "items": [
                        {
                            "case_id": "case",
                            "ref": "asset:case",
                            "kind": "asset",
                            "version": "revision",
                            "collection_ids": ["collection"],
                        }
                    ],
                }
            }
        }
        journey.validate_selection(state, {"case": case}, "collection", previous=1)
        for expected, collection in [
            ({"wrong": case}, "collection"),
            ({"case": {"current_revision_id": "stale"}}, "collection"),
            ({"case": case}, "wrong"),
        ]:
            with self.assertRaises(journey.JourneyFailure):
                journey.validate_selection(state, expected, collection)
        source, gap = (
            {"id": "source", "title": "成功"},
            {"id": "gap", "title": "错误验证码被拒绝"},
        )
        self.assertEqual(
            journey.mixed_gap_case([source, gap], "source", {"foreign"}), gap
        )
        with self.assertRaises(journey.JourneyFailure):
            journey.mixed_gap_case(
                [source, {"id": "foreign", "title": "错误验证码"}],
                "source",
                {"foreign"},
            )

    def test_known_typed_final_errors_survive_redaction_but_unknown_text_does_not(self):
        for code in (
            "agent_final_effect_invalid",
            "agent_final_receipt_invalid",
            "agent_final_receipt_required",
            "agent_model_contract_invalid",
            "agent_output_validation_failed",
            "agent_sdk_configuration_invalid",
            "agent_provider_error",
            "agent_tool_failed",
            "agent_stopped",
            "agent_configuration_missing",
            "agent_provider_incomplete_response",
        ):
            self.assertEqual(journey.safe_code(code), code)
            self.assertEqual(
                journey.runtime_diagnostics({"error_code": code})["runtime_error_code"],
                code,
            )
        self.assertEqual(
            journey.safe_code("private provider message or key"), "unrecognized"
        )
        self.assertEqual(
            journey.safe_code(
                {"code": "agent_final_receipt_required", "message": "private"}
            ),
            "unrecognized",
        )

    def test_exact_candidate_adoption_payload_and_selection_cleanup(self):
        candidate = {"id": "00000000-0000-4000-8000-000000000001", "version": 3}
        payload = journey.candidate_commit_payload(candidate)
        self.assertEqual(
            payload,
            {
                "candidate_ids": [candidate["id"]],
                "candidate_versions": {candidate["id"]: 3},
            },
        )
        with patch.object(
            sys,
            "path",
            [
                str(journey.ROOT / "apps/api/src"),
                str(journey.ROOT / "apps/agent/src"),
                *sys.path,
            ],
        ):
            from casepilot_api.schemas import WorkspaceCandidateCommitRequest
        request = WorkspaceCandidateCommitRequest.model_validate(payload)
        self.assertEqual(list(request.candidate_versions.values()), [3])
        before = {
            "version": 4,
            "items": [{"ref": "candidate:C-1", "candidate_ref": "C-1"}],
        }
        after = {"version": 5, "items": []}
        journey.verify_adopted_candidate_selection(before, after, "C-1")
        for invalid in [before, {"version": 5, "items": before["items"]}]:
            with self.assertRaises(journey.JourneyFailure):
                journey.verify_adopted_candidate_selection(before, invalid, "C-1")
        with self.assertRaises(journey.JourneyFailure):
            journey.verify_adopted_candidate_selection(
                {"version": 4, "items": []}, after, "C-1"
            )

    def test_actual_rebuilt_tool_names_remain_safe_diagnostics(self):
        names = [
            "query_collections",
            "delete_collection",
            "query_candidates",
            "select_assets",
            "select_collection",
            "query_uploaded_cases",
            "preview_uploaded_cases",
            "prepare_generation",
            "prepare_review",
            "prepare_dedup",
            "prepare_coverage",
            "answer_knowledge",
        ]
        result = journey.runtime_diagnostics(
            {"events": [{"type": "tool_completed", "tool": name} for name in names]}
        )
        self.assertEqual([event["tool"] for event in result["tool_events"]], names)

    def test_opt_in_guard(self):
        output = StringIO()
        with patch.object(journey, "execute") as run, redirect_stdout(output):
            self.assertEqual(journey.main([]), 1)
        run.assert_not_called()
        summary = json.loads(output.getvalue())
        self.assertEqual(summary["error_code"], "live_permission_required")
        self.assertEqual(summary["requests_attempted"], 0)
        self.assertFalse(summary["passed"])

    def test_synthetic_fixtures(self):
        rows = list(
            load_workbook(BytesIO(journey.synthetic_spreadsheet())).active.values
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][0], "SYNTHETIC-1")
        self.assertEqual(rows[1][3], "P2")
        image = Image.open(BytesIO(journey.synthetic_png()))
        self.assertEqual(image.size, (128, 128))
        self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))

    def test_metadata_never_emits_content_arguments_or_unknown_names(self):
        data = journey.runtime_diagnostics(
            {
                "error_code": "agent_tool_failed",
                "content": "SECRET",
                "events": [
                    {
                        "type": "tool_started",
                        "tool": "query_cases",
                        "arguments": "SECRET",
                    },
                    {
                        "type": "tool_completed",
                        "tool": "query_cases",
                        "returned_count": 3,
                        "output": "SECRET",
                    },
                    {"type": "tool_failed", "tool": "SECRET"},
                    {"type": "run_failed"},
                ],
            }
        )
        self.assertEqual(data["runtime_error_code"], "agent_tool_failed")
        self.assertEqual(data["terminal_event"], "run_failed")
        self.assertEqual(
            data["query_returned_counts"],
            [{"tool": "query_cases", "returned_count": 3}],
        )
        self.assertNotIn("SECRET", json.dumps(data))
        self.assertIsNone(journey.runtime_diagnostics({})["query_returned_counts"])

    def test_task_dispatch_whitelist_deduplication_and_failure(self):
        dispatch = journey.Dispatch()
        seen = []
        task = SimpleNamespace(
            run=lambda identifier: seen.append(identifier) or {"status": "completed"}
        )
        tasks = SimpleNamespace(generate_test_cases=task)
        dispatch.enqueue(None, "casepilot.agent.generate", ["job"])
        dispatch.enqueue(None, "casepilot.agent.generate", ["job"])
        asyncio.run(dispatch.drain(tasks))
        self.assertEqual(seen, ["job"])
        self.assertEqual(dispatch.executed, 1)
        with self.assertRaises(journey.JourneyFailure):
            dispatch.enqueue(
                None, "casepilot.agent.deliver_integration_callbacks", ["job"]
            )
        dispatch.enqueue(None, "casepilot.agent.generate", ["failed-job"])
        task.run = lambda identifier: {"status": "failed", "error": "SECRET"}
        with self.assertRaisesRegex(journey.JourneyFailure, "^worker_task_failed$"):
            asyncio.run(dispatch.drain(tasks))


class AsyncContracts(unittest.IsolatedAsyncioTestCase):
    async def test_natural_seed_priorities_validate_against_product_schema(self):
        with patch.object(
            sys,
            "path",
            [
                str(journey.ROOT / "apps/api/src"),
                str(journey.ROOT / "apps/agent/src"),
                *sys.path,
            ],
        ):
            from casepilot_api.schemas import TestCaseCreate
        runner = journey.Journey(None, None, None, {"checks": []}, "synthetic")
        runner.post = AsyncMock(
            return_value={"id": "case", "current_revision_id": "revision"}
        )
        for label, priorities in journey.NATURAL_PRIORITIES:
            for index, priority in enumerate(priorities, 1):
                await runner.seed_case("collection", f"{label}{index}", priority)
                self.assertEqual(
                    TestCaseCreate.model_validate(
                        runner.post.await_args.args[1]
                    ).priority,
                    priority,
                )

    async def test_revision_scope_guards(self):
        runner = journey.Journey(None, None, None, {"checks": []}, "synthetic")
        runner.request = AsyncMock(
            side_effect=[
                {"current_revision_id": "new"},
                {"current_revision_id": "unchanged"},
            ]
        )
        await runner.assert_revisions(
            {"selected": "old", "other": "unchanged"}, changed_id="selected"
        )
        runner.request = AsyncMock(return_value={"current_revision_id": "unexpected"})
        with self.assertRaisesRegex(
            journey.JourneyFailure, "unselected_revision_changed"
        ):
            await runner.assert_revisions({"other": "unchanged"}, changed_id="selected")

    async def test_message_requires_real_workbench_metadata(self):
        runner = journey.Journey(None, None, None, {"checks": []}, "synthetic")
        runner.workspace = AsyncMock(return_value={"context": {}})
        runner.post = AsyncMock(
            return_value={
                "assistant_message": {"content": "looks successful", "metadata": {}}
            }
        )
        with self.assertRaisesRegex(journey.JourneyFailure, "workbench_agent_not_used"):
            await runner.message("workspace", "synthetic")
        runner.post = AsyncMock(
            return_value={
                "assistant_message": {
                    "metadata": {
                        "workbench_agent": {
                            "status": "failed",
                            "error_code": "agent_tool_failed",
                        }
                    }
                }
            }
        )
        with self.assertRaisesRegex(journey.JourneyFailure, "workbench_agent_failed"):
            await runner.message("workspace", "synthetic")
        self.assertEqual(
            runner.report["runtime_diagnostics"]["runtime_error_code"],
            "agent_tool_failed",
        )


class PreviewComputeContracts(unittest.IsolatedAsyncioTestCase):
    async def test_short_canonical_scenario_dispatches_without_generation_or_crud(self):
        runner = journey.Journey(
            None,
            SimpleNamespace(),
            {},
            {"checks": [], "workspace_ids": []},
            "synthetic",
        )
        runner.post = AsyncMock(return_value={"spaces": [{"id": "space"}]})
        runner.canonical_rewrite = AsyncMock()
        runner.generation = AsyncMock()
        runner.natural_selection = AsyncMock()
        runner.asset_reuse = AsyncMock()
        await runner.run({"canonical_rewrite"})
        runner.canonical_rewrite.assert_awaited_once_with("space")
        runner.generation.assert_not_awaited()
        runner.natural_selection.assert_not_awaited()
        runner.asset_reuse.assert_not_awaited()

    async def test_compute_runs_worker_without_apply_and_only_resumes_confirmation(
        self,
    ):
        for confirmation in (False, True):
            runner = journey.Journey(
                None,
                SimpleNamespace(drain=AsyncMock()),
                {},
                {"checks": [], "workspace_ids": []},
                "synthetic",
            )
            operation = {"id": "actual-operation", "related_job_id": "actual-job"}
            turn = {"operation_plan": {"operations": [operation]}}
            if confirmation:
                turn["assistant_message"] = {
                    "metadata": {"modification_confirmation": True}
                }
            runner.post = AsyncMock()
            runner.workspace = AsyncMock(
                return_value={
                    "operation_history": [
                        {
                            "id": "old-operation",
                            "related_change_set_id": "stale-preview",
                        },
                        {
                            "id": "actual-operation",
                            "related_change_set_id": "actual-preview",
                        },
                    ]
                }
            )
            runner.request = AsyncMock(return_value={"status": "ready", "items": []})
            change, _ = await runner.compute_prepared_preview("workspace", turn)
            self.assertEqual(change, "actual-preview")
            runner.dispatch.drain.assert_awaited_once_with({})
            runner.request.assert_awaited_once_with(
                "GET", "/case-change-sets/actual-preview"
            )
            if confirmation:
                runner.post.assert_awaited_once_with(
                    "/conversation-operations/actual-operation/resume",
                    {"confirm_modification": True},
                )
            else:
                runner.post.assert_not_awaited()

    async def test_job_artifact_without_current_operation_preview_fails_closed(self):
        runner = journey.Journey(
            None,
            SimpleNamespace(drain=AsyncMock()),
            {},
            {"checks": [], "workspace_ids": []},
            "synthetic",
        )
        runner.workspace = AsyncMock(
            return_value={
                "operation_history": [
                    {"id": "old", "related_change_set_id": "old-preview"}
                ]
            }
        )
        runner.post, runner.request = AsyncMock(), AsyncMock()
        with self.assertRaises(journey.JourneyFailure):
            await runner.compute_prepared_preview(
                "workspace",
                {
                    "operation_plan": {
                        "operations": [{"id": "new", "related_job_id": "actual-job"}]
                    }
                },
            )
        runner.post.assert_not_awaited()
        runner.request.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()


def test_safe_turn_evidence_only_keeps_display_clarification_and_bounded_state():
    secret = "synthetic-private-test-secret"
    response = {"assistant_message": {"content": f"请选择具体用例 {secret} sk-abcdef123456",
        "metadata": {"workbench_agent": {"status": "awaiting_input", "events": [{
            "type": "run_awaiting_input", "final_kind": "clarify", "final_effect": "none"}],
            "raw_response": "MUST_NOT_SAVE", "reasoning": "MUST_NOT_SAVE"}}}}
    result = journey.safe_turn_evidence(response, {"context": {"workbench_selection": {
        "version": 3, "items": [{"ref": "private-ref"}]} }}, {
        "selection_version": 3, "target_case_ids": ["a", "a"], "target_scope": "selected",
        "raw_prompt": "MUST_NOT_SAVE"}, "rewrite_request", secret)
    assert result["canonical_count"] == result["request_case_count"] == 1
    assert result["canonical_version"] == 3
    assert "请选择具体用例" in result["display_clarification"]
    assert secret not in str(result) and "sk-abcdef" not in str(result)
    assert "MUST_NOT_SAVE" not in str(result) and "private-ref" not in str(result)
    response["assistant_message"]["metadata"]["workbench_agent"]["events"][0]["final_kind"] = "answer"
    assert "display_clarification" not in journey.safe_turn_evidence(response, {}, {}, "other")
