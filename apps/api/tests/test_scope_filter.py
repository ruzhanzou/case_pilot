import pytest

from casepilot_api.scope_filter import ScopeFilter, apply_scope_filter


def test_boolean_filters_scan_full_catalog_without_truncation():
    cases = [
        {
            "id": str(i),
            "module": "支付/退款" if i % 2 else "账号",
            "priority": "P0" if i % 3 == 0 else "P1",
            "steps": [{"action": "提交", "expected": "超时后回滚"}],
        }
        for i in range(5001)
    ]
    plan = ScopeFilter(
        groups=[
            [
                {"field": "module", "operator": "module_tree", "value": "支付"},
                {"field": "priority", "operator": "equals", "value": "P0", "negate": True},
                {"field": "steps", "operator": "contains", "value": "回滚"},
            ],
            [{"field": "module", "operator": "equals", "value": "不存在"}],
        ]
    )
    assert apply_scope_filter(plan, cases, {}) == [str(i) for i in range(5001) if i % 2 and i % 3]


def test_empty_previous_query_never_expands_to_collection():
    plan = ScopeFilter(groups=[[]], reference="previous_query")
    assert apply_scope_filter(plan, [{"id": "1"}], {"latest_query": {"ids": []}}) == []


def test_union_and_negation_preserve_reference_scope():
    cases = [
        {"id": "a", "title": "成功"},
        {"id": "b", "title": "超时"},
        {"id": "c", "title": "成功"},
    ]
    plan = ScopeFilter(
        reference="selection",
        groups=[
            [{"field": "title", "operator": "equals", "value": "成功"}],
            [{"field": "title", "operator": "contains", "value": "超时"}],
        ],
    )
    assert apply_scope_filter(plan, cases, {"selected_ids": ["a", "b"]}) == ["a", "b"]


def test_ambiguous_filter_cannot_execute():
    with pytest.raises(ValueError):
        apply_scope_filter(ScopeFilter(groups=[[]], ambiguous=True), [{"id": "a"}], {})


def test_reference_union_can_add_outside_old_module():
    cases = [
        {"id": "a", "case_key": "TC-A"},
        {"id": "b", "case_key": "TC-B"},
        {"id": "c", "case_key": "TC-C"},
    ]
    plan = ScopeFilter(
        groups=[
            [{"field": "reference", "operator": "equals", "value": "selection"}],
            [{"field": "case_key", "operator": "equals", "value": "TC-C"}],
        ]
    )
    assert apply_scope_filter(plan, cases, {"selected_ids": ["a"]}) == ["a", "c"]


def test_body_search_does_not_match_metadata_or_json_keys():
    cases = [{"id": "expected", "title": "登录", "steps": [{"expected": "成功"}]}]
    plan = ScopeFilter(groups=[[{"field": "text", "operator": "contains", "value": "expected"}]])
    assert apply_scope_filter(plan, cases, {}) == []


def test_invalid_operator_is_rejected_even_for_empty_catalog():
    with pytest.raises(ValueError):
        ScopeFilter(groups=[[{"field": "priority", "operator": "module_tree", "value": "P0"}]])
