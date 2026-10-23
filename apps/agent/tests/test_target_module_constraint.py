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
