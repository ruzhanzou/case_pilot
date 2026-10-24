"""Live semantic checks using the same instruction and schema as generation."""

import json
from pathlib import Path

from casepilot_agent.compact_generation import (
    POINT_SEMANTIC_INSTRUCTION,
    PointSemanticChecks,
)
from casepilot_agent.config import get_settings
from casepilot_agent.providers import create_provider

CASES = [
    (
        "等价单位",
        "连续失败五次后锁定半小时",
        "连续输错密码五次，检查锁定持续时间",
        "账号锁定1800秒",
        False,
    ),
    (
        "遗漏时长",
        "连续失败五次后锁定半小时",
        "连续输错密码五次",
        "账号进入锁定状态",
        True,
    ),
    (
        "先后顺序",
        "退出后原会话失效",
        "执行退出，然后用退出前的同一token请求受保护资源",
        "原会话失效，资源访问被拒绝",
        False,
    ),
    (
        "遗漏动作",
        "退出后原会话失效",
        "使用已失效的token请求受保护资源",
        "访问被拒绝",
        True,
    ),
]


def main():
    settings = get_settings()
    assert settings.provider != "mock", "Live model configuration required"
    provider = create_provider(settings.provider)
    output = Path("artifacts/semantic-acceptance/content.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    results = []
    for label, requirement, action, expected, should_fail in CASES:
        payload = {
            "points": [
                {
                    "slot": 1,
                    "point": {"objective": requirement, "scenario": requirement},
                }
            ],
            "test_cases": [
                {
                    "slot": 1,
                    "title": label,
                    "preconditions": ["账号处于可用状态，已建立有效会话"],
                    "steps": [{"action": action, "expected": expected}],
                }
            ],
        }
        checks, _ = provider.complete(
            stage="test_case.semantics_checked",
            instruction=POINT_SEMANTIC_INSTRUCTION,
            payload=payload,
            result_type=PointSemanticChecks,
            model_id="auto",
        )
        passed = (
            len(checks.checks) == 1
            and checks.checks[0].slot == 1
            and bool(checks.checks[0].errors) == should_fail
        )
        record = dict(
            label=label,
            expected_errors=should_fail,
            actual=checks.model_dump(),
            passed=passed,
        )
        results.append(record)
        output.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(json.dumps(record, ensure_ascii=False), flush=True)
    return int(not all(item["passed"] for item in results))


if __name__ == "__main__":
    raise SystemExit(main())
