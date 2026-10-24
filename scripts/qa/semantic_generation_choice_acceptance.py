"""Read-only real-model acceptance for generation and confirmation semantics."""

import json
from pathlib import Path

from casepilot_api.config import get_settings
from casepilot_api.generation_strategy import interpret_generation_choice

CASES = [
    (
        "请再执行一次刚才失败的删除任务",
        None,
        {"retry_requested": True, "retry_kind": "CASE_DELETE"},
    ),
    ("不要重试刚才的任务", None, {"retry_requested": False}),
    ("解释失败后怎么重试", None, {"retry_requested": False}),
    ("参考历史登录用例并补齐新的异常场景", None, {"strategy": "select_and_generate"}),
    ("不要复用已有用例，重新生成", None, {"strategy": "generate"}),
    ("只选第二条和第四条", ["a", "b", "c", "d"], {"selected_ids": ["b", "d"]}),
    (
        "这三条直接用",
        ["a", "b"],
        {"selected_ids": None, "ambiguous": True, "requested_count": 3},
    ),
    ("确认当前测试说明，开始生成用例", None, {"confirms_brief": True}),
    ("不要确认测试说明，先增加安全测试点", None, {"confirms_brief": False}),
    ("如何确认测试说明并生成用例？", None, {"confirms_brief": False}),
    (
        "新增名为发票管理的空模块，不生成用例",
        None,
        {"new_module": "发票管理", "create_empty_module": True},
    ),
    ("为库存系统生成测试点", None, {"test_object": "库存系统"}),
    (
        "不要改写当前候选，参考历史用例生成一套全新用例",
        None,
        {"rewrite_existing_assets": False},
    ),
]


def main():
    settings = get_settings()
    assert settings.agent_provider != "mock"
    results = []
    path = Path("artifacts/semantic-acceptance/generation-details.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    for prompt, ids, expected in CASES:
        actual = interpret_generation_choice(prompt, settings, ids).model_dump()
        passed = all(actual[k] == v for k, v in expected.items())
        results.append(
            dict(prompt=prompt, expected=expected, actual=actual, passed=passed)
        )
        path.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(
            json.dumps(dict(prompt=prompt, passed=passed), ensure_ascii=False),
            flush=True,
        )
    return int(not all(r["passed"] for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
