from copy import deepcopy
from unittest.mock import Mock
from uuid import uuid4

import pytest
from openpyxl import Workbook
from sqlalchemy.dialects import postgresql
from test_compact_generation import execute, request, run

from casepilot_agent.knowledge import parse_document
from casepilot_agent.reuse import (
    ReuseDecisions,
    normalize_sources,
    plan_reuse,
    shortlist,
)
from casepilot_agent.store import JobStore


def source():
    return {
        "key": "asset:one",
        "kind": "formal",
        "label": "资产 TC-001",
        "locator": "版本 4",
        "revision": "revision-4",
        "snapshot": {
            "title": "有效账号建立会话",
            "module": "登录",
            "case_type": "functional",
            "priority": "P1",
            "preconditions": ["已有有效账号"],
            "steps": [{"action": "输入正确凭据登录", "expected": "建立用户会话"}],
        },
    }


def with_decision(action="reuse", count=2):
    req = request(count)
    decision = {
        "point_id": "P-0",
        "point_snapshot": deepcopy(req.confirmed_plan["test_points"][0]),
        "action": action,
        "source_key": "asset:one",
        "source": source(),
        "reason": "核心登录规则未变",
    }
    req.confirmed_plan["reuse"] = {"strategy": "regression", "decisions": [decision]}
    return req


def test_reuse_preserves_content_and_does_not_call_model_for_reused_slot():
    req, calls = with_decision(), []

    def tracked(*args):
        calls.append(args[2]["batch_slots"])
        return execute(*args)

    result = run(req, tracked)
    assert calls == [[2]]
    first = result.test_cases[0]
    assert first.title == source()["snapshot"]["title"]
    assert [s.model_dump() for s in first.steps] == source()["snapshot"]["steps"]
    assert "revision-4" in first.source_refs[-1].excerpt
    assert "复用" in first.source_refs[-1].label


def test_all_reused_never_calls_generation_model():
    result = run(with_decision(count=1), Mock(side_effect=AssertionError("unnecessary call")))
    assert len(result.test_cases) == 1


def test_modified_case_receives_original_and_retains_source():
    calls = []

    def tracked(*args):
        calls.append(args[2]["reuse_modifications"])
        return execute(*args)

    result = run(with_decision("modify", count=1), tracked)
    assert calls[0][0]["original"] == source()["snapshot"]
    assert any("修改参考" in ref.label for ref in result.test_cases[0].source_refs)


def test_changed_point_cannot_use_stale_reuse_decision():
    req = with_decision()
    req.confirmed_plan["test_points"][0]["objective"] = "改成短信登录"
    with pytest.raises(ValueError, match="reuse_plan_changed"):
        run(req)


def test_fresh_strategy_ignores_old_decisions():
    req = with_decision(count=1)
    req.confirmed_plan["reuse"]["strategy"] = "fresh"
    result = run(req)
    assert result.test_cases[0].title != source()["snapshot"]["title"]


def test_one_reused_case_can_cover_two_points_without_duplicate_candidates():
    req = with_decision()
    second = deepcopy(req.confirmed_plan["reuse"]["decisions"][0])
    second.update(point_id="P-1", point_snapshot=deepcopy(req.confirmed_plan["test_points"][1]))
    req.confirmed_plan["reuse"]["decisions"].append(second)
    result = run(req, Mock(side_effect=AssertionError("unnecessary call")))
    assert len(result.test_cases) == 1
    assert result.test_cases[0].test_point_ids == ["P-0", "P-1"]


@pytest.mark.parametrize(
    "bad", ["unknown_source", "missing_point", "duplicate_point", "new_with_source"]
)
def test_reuse_decisions_reject_invented_sources_and_incomplete_coverage(bad):
    req = request(1)
    row = {"point_id": "P-0", "action": "reuse", "source_key": "asset:one", "reason": "未变"}
    rows = [row]
    if bad == "unknown_source":
        row["source_key"] = "asset:other-space"
    elif bad == "missing_point":
        rows = []
    elif bad == "duplicate_point":
        rows = [row, row]
    else:
        row["action"] = "new"
    with pytest.raises(ValueError):
        plan_reuse(
            req.confirmed_plan,
            "change",
            [source()],
            lambda *args: ReuseDecisions(decisions=rows),
            "验证码改为2分钟",
        )


def test_excel_headers_survive_multiple_blocks_and_preserve_identity(tmp_path):
    path = tmp_path / "旧用例.xlsx"
    book = Workbook()
    book.active.title = "登录"
    book.active.append(["用例编号", "用例名称", "前置条件", "测试步骤", "预期结果"])
    for i in range(45):
        book.active.append([f"TC-{i:03}", f"场景{i}", "有账号", "登录", "建立会话"])
    book.create_sheet("需求").append(["编号", "规则"])
    book.save(path)
    blocks = parse_document(path, "application/octet-stream")
    rows = [r for block in blocks for r in block.metadata.get("reference_cases", [])]
    assert len(rows) == 45 and rows[-1]["row"] == 46
    assert rows[0]["original_id"] == "TC-000"
    document_id = str(uuid4())
    evidence = [
        {"document_id": document_id, "chunk_id": str(uuid4()), "label": path.name, **block.metadata}
        for block in blocks
    ]
    # Parent chunk splitting must not duplicate source cases.
    sources = normalize_sources([], evidence + evidence)
    assert len(sources) == 45 and "行 46" in sources[-1]["locator"]


def test_incomplete_excel_case_is_not_fabricated(tmp_path):
    path = tmp_path / "不完整.xlsx"
    book = Workbook()
    book.active.append(["用例名称", "测试步骤", "预期结果"])
    book.active.append(["登录", "登录", ""])
    book.save(path)
    assert (
        normalize_sources(
            [], [{"document_id": "x", "label": "x", **b.metadata} for b in parse_document(path, "")]
        )
        == []
    )


def test_shortlist_has_hard_input_budget_without_truncating_snapshots():
    sources = [{**source(), "key": str(i)} for i in range(100)]
    selected = shortlist(sources, [{"title": "登录"}], limit=10, budget=1000)
    import json

    assert 0 < len(selected) <= 10
    assert sum(len(json.dumps(s, ensure_ascii=False)) for s in selected) <= 1000
    assert all(s["snapshot"] == source()["snapshot"] for s in selected)


def test_asset_search_is_bounded_scoped_and_escapes_wildcards():
    connection = Mock()
    connection.execute.return_value.mappings.return_value = []
    JobStore.__new__(JobStore).search_reuse_cases(connection, space_id=uuid4(), terms=["登录%_"])
    statement = connection.execute.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "space_id =" in sql and "deleted_at IS NULL" in sql
    assert "current_revision_id" in sql and "LIMIT" in sql and "ESCAPE" in sql


@pytest.mark.parametrize("strategy", ["fresh", "regression", "change"])
def test_draft_workflow_queries_assets_only_for_reuse_and_persists_decisions(monkeypatch, strategy):
    from test_draft_planning_progress import Store
    from test_parallel_planning import features, points

    from casepilot_agent import tasks
    from casepilot_agent.contracts import UsageMetadata
    from casepilot_agent.reuse import ReuseAnalysis

    store = Store()
    store.job["space_id"] = uuid4()
    search = Mock(return_value=[{"ref": "one", "snapshot": source()["snapshot"]}])
    store.search_reuse_cases = search

    class Provider:
        def complete(self, *, stage, payload, result_type, **kwargs):
            if stage == "requirement.analyzed":
                result = ReuseAnalysis(
                    summary="登录",
                    test_object="登录",
                    test_object_specified=True,
                    generation_strategy=strategy,
                    case_search_terms=["登录"],
                )
            elif stage == "feature.generated":
                result = features(6)
            elif stage == "reuse.compared":
                result = result_type(
                    decisions=[
                        {
                            "point_id": p["id"],
                            "action": "reuse",
                            "source_key": payload["sources"][0]["key"],
                            "reason": "登录规则未变",
                        }
                        for p in payload["test_points"]
                    ]
                )
            else:
                result = points(payload, fill_budget=True)
            return result, UsageMetadata(model="mock")

    monkeypatch.setattr(tasks, "JobStore", lambda *args: store)
    monkeypatch.setattr(tasks, "create_provider", lambda *args: Provider())
    monkeypatch.setattr(tasks, "create_embedding_provider", lambda: None)
    monkeypatch.setattr(tasks, "_context_payload", lambda *args, **kwargs: {"evidence": []})
    tasks.draft_test_brief(str(store.job["id"]))
    reuse = store.briefs[0]["planning"]["reuse"]
    assert reuse["strategy"] == strategy
    assert reuse["summary"] == ({"new": 12} if strategy == "fresh" else {"reuse": 12})
    assert search.call_count == (0 if strategy == "fresh" else 1)
    if strategy != "fresh":
        assert search.call_args.kwargs["space_id"] == store.job["space_id"]
        events = [event["event"] for event in store.events]
        assert events.index("cases.searching") < events.index("reuse.comparing")
        assert events[-1] == "brief.completed"


def test_reference_budget_never_causes_unverified_direct_reuse():
    req = request(1)
    req.confirmed_plan["test_points"][0]["source_refs"] = [{"chunk_id": "chunk", "label": "规则"}]
    req.confirmed_plan["evidence"] = [{"chunk_id": "chunk", "excerpt": "x" * 24001}]
    result = plan_reuse(
        req.confirmed_plan,
        "change",
        [source()],
        lambda *args: ReuseDecisions(
            decisions=[
                {
                    "point_id": "P-0",
                    "action": "reuse",
                    "source_key": "asset:one",
                    "reason": "未变化",
                }
            ]
        ),
        "新需求",
    )
    assert result["decisions"][0]["action"] == "new"
    assert "source" not in result["decisions"][0]


def test_reuse_comparison_bounds_concurrency_and_batch_payloads():
    from threading import Barrier, Lock

    req = request(36)
    lock, barrier = Lock(), Barrier(3)
    active = peak = calls = 0

    def complete(stage, instruction, payload, result_type):
        nonlocal active, peak, calls
        with lock:
            active += 1
            peak = max(peak, active)
            calls += 1
        assert len(payload["test_points"]) <= 12
        assert len(payload["sources"]) <= 30
        barrier.wait(timeout=5)
        result = result_type(decisions=[{
            "point_id": p["id"], "action": "new", "source_key": None, "reason": "缺口"
        } for p in payload["test_points"]])
        with lock:
            active -= 1
        return result

    result = plan_reuse(req.confirmed_plan, "regression", [source()], complete, "登录回归")
    assert peak == 3 and calls == 3
    assert len(result["decisions"]) == 36


def test_cancelled_reuse_does_not_start_model_work():
    complete = Mock()

    def cancelled():
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        plan_reuse(request(12).confirmed_plan, "change", [source()], complete, "改版",
                   check_cancelled=cancelled)
    complete.assert_not_called()
