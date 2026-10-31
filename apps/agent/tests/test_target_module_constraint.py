from casepilot_agent.tasks import constrain_generated_modules


def test_explicit_new_module_flattens_generated_submodules():
    candidates = [
        {"title": "成功开票", "module": "发票管理/成功开票"},
        {"title": "退款订单", "module": "其他模块"},
    ]

    constrain_generated_modules(candidates, "发票管理", exact=True)

    assert [item["module"] for item in candidates] == ["发票管理", "发票管理"]


def test_general_module_boundary_still_allows_child_modules():
    candidates = [
        {"title": "成功开票", "module": "发票管理/申请"},
        {"title": "退款订单", "module": "其他模块"},
    ]

    constrain_generated_modules(candidates, "发票管理")

    assert [item["module"] for item in candidates] == ["发票管理/申请", "发票管理"]


def source_plan(action="reuse", changed_fields=None, *, reserved=False):
    source = {"key": "asset:source", "snapshot": {"module": "Original/Payments"},
              "collections": [{"id": "first"}, {"id": "second"}]}
    row = {"action": action, "source": source, "point_id": "TP-source",
           "changed_fields": changed_fields or []}
    return {"test_points": [{"id": "TP-source"}], "approved_source_catalog": [source],
            "reserved_reuse_outputs": [{**row, "point_ids": ["TP-source"]}] if reserved else [],
            "reuse": {"decisions": [] if reserved else [row]}}


def test_reserved_and_ordinary_reuse_preserve_module_in_new_collection():
    for reserved in (False, True):
        plan = source_plan(reserved=reserved)
        rows = [{"id": "any-id", "test_point_ids": ["TP-source"],
                 "module": "Original/Payments", "source_refs": [{"label": "original-version"}]},
                {"id": "TC-RESERVED-forged", "test_point_ids": ["TP-new"], "module": "other"}]
        constrain_generated_modules(rows, "New destination", exact=True, confirmed_plan=plan)
        assert rows[0]["module"] == "Original/Payments"
        assert rows[0]["source_refs"] == [{"label": "original-version"}]
        assert rows[1]["module"] == "New destination"


def test_partial_modification_requires_module_permission():
    for fields, expected in [(["expected"], "Original/Payments"), (["module"], "Requested")]:
        rows = [{"test_point_ids": ["TP-source"], "module": "proposed"}]
        constrain_generated_modules(rows, "Requested", exact=True,
                                    confirmed_plan=source_plan("modify", fields))
        assert rows[0]["module"] == expected


def test_revoked_or_unapproved_sources_do_not_exempt_generation_scope():
    for revoked in (False, True):
        plan = source_plan()
        if revoked:
            plan["excluded_reuse_source_keys"] = ["asset:source"]
        else:
            plan["approved_source_catalog"] = []
        rows = [{"test_point_ids": ["TP-source"], "module": "outside"}]
        constrain_generated_modules(rows, "Requested", confirmed_plan=plan)
        assert rows[0]["module"] == "Requested"


def test_multiple_source_modules_remain_independent():
    from copy import deepcopy

    plan = source_plan()
    second = deepcopy(plan["reuse"]["decisions"][0])
    second.update(point_id="TP-second")
    second["source"].update(key="asset:second", snapshot={"module": "Other/Module"})
    plan["reuse"]["decisions"].append(second)
    plan["approved_source_catalog"].append(second["source"])
    rows = [{"test_point_ids": [point], "module": "bad"} for point in ["TP-source", "TP-second"]]
    constrain_generated_modules(rows, "Destination", exact=True, confirmed_plan=plan)
    assert [r["module"] for r in rows] == ["Original/Payments", "Other/Module"]
    import pytest

    with pytest.raises(ValueError, match="reuse_module_binding_conflict"):
        constrain_generated_modules([{"test_point_ids": ["TP-source", "TP-second"]}],
                                    "Destination", confirmed_plan=plan)


def test_fresh_strategy_does_not_reactivate_old_reuse_decisions():
    plan = source_plan()
    plan["reuse"]["strategy"] = "fresh"
    rows = [{"test_point_ids": ["TP-source"], "module": "outside"}]
    constrain_generated_modules(rows, "Requested", confirmed_plan=plan)
    assert rows[0]["module"] == "Requested"
