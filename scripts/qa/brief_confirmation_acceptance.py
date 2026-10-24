"""Live regression corpus for revision versus confirmation, including observed failure."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from casepilot_api.config import get_settings
from casepilot_api.generation_strategy import interpret_generation_choice

CASES = [
    (
        "在现有测试规划上增加一个测试点：用户登录后点击退出，返回登录页，会话失效。原有两个测试点保持不变。",
        "revise",
        False,
    ),
    ("从测试规划中删除退出登录测试点，其他两个测试点保持不变。", "revise", False),
    ("把第二个测试点修改为密码错误三次后锁定，其他不变。", "revise", False),
    ("确认当前测试规划，开始生成用例", "confirm", True),
    ("可以，但先补上安全测试点再给我确认", "revise", False),
    ("如何确认测试说明并生成用例？", "none", False),
]


def check(spec):
    text, action, confirmed = spec
    try:
        actual = interpret_generation_choice(text, get_settings()).model_dump()
        return {
            "prompt": text,
            "expected": {"brief_action": action, "confirms_brief": confirmed},
            "actual": actual,
            "passed": actual["brief_action"] == action
            and actual["confirms_brief"] == confirmed,
        }
    except Exception as error:  # Independent cases retain failures without skipping remaining requests.
        return {"prompt": text, "passed": False, "error": str(error)}


if __name__ == "__main__":
    assert get_settings().agent_provider != "mock"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(check, CASES * 2))
    output = Path("artifacts/deep-dialogue-acceptance/brief-confirmations.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(
        json.dumps({"passed": sum(r["passed"] for r in results), "total": len(results)})
    )
    raise SystemExit(int(not all(r["passed"] for r in results)))
