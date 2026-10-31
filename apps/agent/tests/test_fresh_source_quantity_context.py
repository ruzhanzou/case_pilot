"""Real draft worker seam: confirmed sources are not already-created test points."""
from copy import deepcopy
from uuid import uuid4

import pytest
from test_compact_generation import request
from test_draft_planning_progress import Store
from test_reserved_generation import reservation

from casepilot_agent import tasks
from casepilot_agent.contracts import UsageMetadata
from casepilot_agent.quantity import OutputQuantity
from casepilot_agent.reuse import ReuseAnalysis


@pytest.mark.parametrize("mode", [
    "fresh", "reviewed", "unreviewed_existing", "ordinary", "one_point_conflict", "background_only",
    "revoked_draft", "revoked_reviewed", "legacy_reviewed", "missing_reviewed", "missing_draft",
    "stale_legacy", "recover_mapping", "recover_withdraw", "recover_model_omission",
    "recover_source_removed", "recover_unconfirmed", "recover_subset",
])
def test_quantity_context_applies_only_before_first_points_and_reservation_is_subtracted_once(
    monkeypatch, mode,
):
    store = Store()
    store.job["space_id"] = uuid4()
    original = request(2).confirmed_plan
    source = reservation(None)["source"]
    source["kind"] = "formal"
    previous = {}
    if mode in {"reviewed", "unreviewed_existing", "legacy_reviewed",
                "missing_reviewed", "missing_draft", "stale_legacy",
                "recover_mapping", "recover_withdraw", "recover_model_omission",
                "recover_source_removed", "recover_unconfirmed", "recover_subset"}:
        previous = deepcopy(original)
        previous["reuse"] = {"strategy": "regression", "decisions": [{
            "point_id": "P-0", "action": "reuse", "source": source,
            "point_snapshot": deepcopy(original["test_points"][0]),
        }]}
        previous["reserved_reuse_outputs"] = [reservation(request(2))]
        previous["point_review_receipt"] = {"brief_id": str(uuid4()), "version": 1,
            "kind": "points", "point_ids": [point["id"] for point in original["test_points"]]}
    if mode in {"legacy_reviewed", "missing_reviewed", "missing_draft", "stale_legacy",
                "recover_mapping", "recover_withdraw", "recover_model_omission",
                "recover_source_removed", "recover_unconfirmed", "recover_subset"}:
        previous.pop("reserved_reuse_outputs")
    if mode in {"missing_reviewed", "missing_draft", "recover_mapping", "recover_withdraw",
                "recover_model_omission",
                "recover_source_removed", "recover_unconfirmed", "recover_subset"}:
        previous["reuse"]["decisions"] = []
    if mode == "stale_legacy":
        previous["reuse"]["decisions"][0]["source"] = {**source, "revision": "old-revision"}
    if mode in {"unreviewed_existing", "missing_draft"}:
        previous.pop("point_review_receipt")
    revoked = mode in {"revoked_draft", "revoked_reviewed"}
    if revoked:
        previous = deepcopy(original)
        previous["excluded_reuse_source_keys"] = [source["key"]]
        previous["reuse"] = {"user_choices": {"P-0": "new", "removed-point": "exclude"},
                             "decisions": []}
        if mode == "revoked_reviewed":
            previous["point_review_receipt"] = {"brief_id": str(uuid4()), "version": 1,
                "kind": "points", "point_ids": [p["id"] for p in original["test_points"]]}
    prompt = "原样复用已确认来源，再新增一条缺口；共2条用例和2个测试点。"
    memory = [{"role": "user", "content": prompt}]
    store.job["input_payload"].update(
        prompt=prompt,
        generation_strategy="generate" if mode == "ordinary" else "select_and_generate",
        asset_selection_confirmed=mode != "ordinary", confirmed_asset_sources=[source],
        current_test_brief={"planning": previous}, conversation_memory=memory,
    )
    if mode == "recover_subset":
        store.job["input_payload"]["confirmed_asset_sources"].append({**source, "key": "asset:b"})
    initial_sources = deepcopy(store.job["input_payload"]["confirmed_asset_sources"])
    if revoked:
        # Another allowed background source must not be indiscriminately revoked.
        store.job["input_payload"]["confirmed_asset_sources"].append({**source, "key": "asset:b"})
    store.attach_reuse_collections = lambda connection, items, **kwargs: items
    store.persist_test_brief = lambda connection, job, content: (
        store.briefs.append(deepcopy(content)) or 1
    )
    quantities, counts, compared_sources = [], [], []
    withdrawn = False

    class Provider:
        def complete(self, *, stage, payload, **kwargs):
            if stage == "output_quantity.interpreted":
                quantities.append(deepcopy(payload))
                value = OutputQuantity(
                    required_reuse_source_keys=[]
                    if withdrawn or revoked or mode in {"background_only", "ordinary"}
                    else [s["key"] for s in initial_sources],
                    test_point_count=1 if mode == "one_point_conflict" else 2,
                    output_case_count=2,
                    new_case_count=2 if withdrawn or mode == "background_only" else 1,
                )
            elif stage in {"requirement.analyzed", "requirement.extracted"}:
                value = ReuseAnalysis(summary="Account login", test_object="Account",
                                      test_object_specified=True, generation_strategy="regression")
            else:
                raise AssertionError(stage)
            return value, UsageMetadata(model="fixture")

    def build(*args, target_count, **kwargs):
        counts.append(target_count)
        value = deepcopy(original)
        value["test_points"] = value["test_points"][:target_count]
        return value

    monkeypatch.setattr(tasks, "JobStore", lambda *args: store)
    monkeypatch.setattr(tasks, "create_provider", lambda *args: Provider())
    monkeypatch.setattr(tasks, "create_embedding_provider", lambda: None)
    monkeypatch.setattr(tasks, "_context_payload", lambda *args, **kwargs: {"evidence": []})
    monkeypatch.setattr(tasks, "build_planning", build)
    def compare(plan, strategy, sources, *args, **kwargs):
        compared_sources.append(deepcopy(sources))
        return {"strategy": "regression", "decisions": []}

    monkeypatch.setattr(tasks, "plan_reuse", compare)
    prior_input = deepcopy(store.job["input_payload"]["current_test_brief"])
    tasks.draft_test_brief(str(store.job["id"]))
    assert len(quantities) == 1
    payload = quantities[0]
    assert payload["prompt"] == prompt and payload["conversation_memory"] == memory
    context = payload["planning_context"]
    plan = store.briefs[0]["planning"]
    if mode in {"legacy_reviewed", "missing_reviewed", "missing_draft", "stale_legacy",
                "recover_mapping", "recover_withdraw", "recover_model_omission",
                "recover_source_removed", "recover_unconfirmed", "recover_subset"}:
        assert store.job["input_payload"]["current_test_brief"] == prior_input
        assert plan["test_points"] == prior_input["planning"]["test_points"]
        assert plan["feature_points"] == prior_input["planning"]["feature_points"]
        assert not counts
        if mode == "legacy_reviewed":
            assert plan["reserved_reuse_outputs"][0]["point_ids"] == ["P-0"]
            # All-new comparison cannot erase the prior exact mapping.
            assert len(compared_sources) == 1
        else:
            assert not compared_sources
            pending = plan["pending_reserved_outputs"]
            assert pending["reason"] == "reserved_reuse_mapping_requires_clarification"
            assert pending["quantity"]["required_reuse_source_keys"] == [
                s["key"] for s in initial_sources
            ]
            assert pending["required_sources"] == initial_sources
            assert store.briefs[0]["open_questions"][-1]["blocking"]
            prior_receipt = prior_input["planning"].get("point_review_receipt")
            assert plan.get("point_review_receipt") == prior_receipt
        if mode in {"recover_mapping", "recover_withdraw", "recover_model_omission",
                "recover_source_removed", "recover_unconfirmed", "recover_subset"}:
            resumed = deepcopy(plan)
            if mode == "recover_mapping":
                resumed["reuse"] = {"decisions": [{"point_id": "P-0", "action": "reuse",
                    "source": deepcopy(source),
                    "point_snapshot": deepcopy(original["test_points"][0])}]}
            else:
                withdrawn = True  # Model omits must; only actual authority may revoke it.
                if mode == "recover_withdraw":
                    resumed["excluded_reuse_source_keys"] = [source["key"]]
                    resumed["reuse"] = {"user_choices": {"P-0": "new"}, "decisions": []}
                elif mode == "recover_source_removed":
                    store.job["input_payload"]["confirmed_asset_sources"] = []
                elif mode == "recover_subset":
                    store.job["input_payload"]["confirmed_asset_sources"] = [source]
                elif mode == "recover_unconfirmed":
                    store.job["input_payload"]["asset_selection_confirmed"] = False
                    store.job["input_payload"]["generation_strategy"] = "generate"
            store.job["input_payload"]["current_test_brief"] = {"planning": resumed}
            tasks.draft_test_brief(str(store.job["id"]))
            result = store.briefs[-1]["planning"]
            assert result["test_points"] == original["test_points"] and not counts
            if mode in {"recover_model_omission", "recover_unconfirmed", "recover_subset"}:
                pending = result["pending_reserved_outputs"]
                assert pending["quantity"]["required_reuse_source_keys"] == [source["key"]]
                assert store.briefs[-1]["open_questions"][-1]["blocking"]
                return
            assert "pending_reserved_outputs" not in result
            if withdrawn:
                if mode == "recover_withdraw":
                    assert result["excluded_reuse_source_keys"] == [source["key"]]
                assert not result.get("reserved_reuse_outputs")
                assert result["output_obligations"]["required_reuse_source_keys"] == []
            else:
                assert result["reserved_reuse_outputs"][0]["point_ids"] == ["P-0"]
    elif revoked:
        assert "fresh_source_confirmation" not in context
        assert context["excluded_reuse_source_keys"] == [source["key"]]
        assert context["reviewer_choices"] == {"P-0": "new"}
        assert [s["key"] for s in payload["approved_source_catalog"]] == ["asset:b"]
        assert [s["key"] for s in compared_sources[0]] == ["asset:b"]
        assert plan["excluded_reuse_source_keys"] == [source["key"]]
        assert plan["reuse"]["user_choices"] == {"P-0": "new"}
        assert not plan.get("reserved_reuse_outputs")
        assert not counts and plan["test_points"] == previous["test_points"]
    elif mode in {"reviewed", "unreviewed_existing"}:
        assert "fresh_source_confirmation" not in context
        assert counts == [] and plan["test_points"] == previous["test_points"]
    elif mode == "ordinary":
        assert "fresh_source_confirmation" not in context
        assert counts == [2] and not plan.get("reserved_reuse_outputs")
    else:
        fresh = context["fresh_source_confirmation"]
        assert fresh["existing_test_point_count"] == 0
        assert fresh["test_point_count_scope"] == "complete_new_plan_before_source_reservation"
        assert "required_reuse_source_keys" in fresh["instruction"]
        assert "required_reuse_source_keys" not in fresh  # Must has not been inferred yet.
        if mode == "one_point_conflict":
            assert not counts
            assert plan["pending_reserved_outputs"]["reason"] == (
                "reserved_reuse_point_budget_requires_clarification"
            )
            assert store.briefs[0]["open_questions"][-1]["blocking"]
        elif mode == "background_only":
            assert counts == [2] and not plan.get("reserved_reuse_outputs")
        else:
            assert counts == [1]  # Total two minus exactly one reserved coverage point.
            assert len(plan["test_points"]) == 2
            assert len(plan["reserved_reuse_outputs"]) == 1
