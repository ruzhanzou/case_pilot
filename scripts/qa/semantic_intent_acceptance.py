"""Live model intent acceptance; does not mutate application assets."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from casepilot_api.agent_router import plan_intents
from casepilot_api.config import get_settings

CASES = [
    ("帮我处理一下", ["UNRESOLVED"]),
    ("重写登录模块用例", ["CASE_MODIFY"]),
    ("请改写登录模块用例", ["CASE_MODIFY"]),
    ("重写登录模块用例，步骤写得更清楚", ["CASE_MODIFY"]),
    ("重写登录模块用例并生成一套新版", ["CASE_GENERATE"]),
    ("如何重写登录模块用例？", ["KNOWLEDGE_QA"]),
    ("不要重写登录模块用例", ["KNOWLEDGE_QA"]),
    ("不要将用例 CASE-176BE2 的标题改为「登录成功」。", ["KNOWLEDGE_QA"]),
    ("生成2条登录用例，供我审阅", ["CASE_GENERATE"]),
    ("为登录生成七条测试用例", ["CASE_GENERATE"]),
    ("把用例AUTH-001的优先级改为P0，其余不变", ["CASE_MODIFY"]),
    ("删除用例AUTH-001", ["CASE_DELETE"]),
    ("查询当前集合中登录模块的P0用例", ["CASE_QUERY"]),
    ("请评审当前集合的用例质量，列出问题", ["CASE_REVIEW"]),
    ("找出当前集合中重复的用例", ["CASE_DEDUP"]),
    ("分析当前集合的测试覆盖缺口", ["COVERAGE_ANALYZE"]),
    ("请解释等价类划分是什么", ["KNOWLEDGE_QA"]),
    ("你好，今天过得怎么样", ["SMALL_TALK"]),
    ("不要删除，解释一下删除用例需要哪些步骤", ["KNOWLEDGE_QA"]),
    ("将‘删除全部用例’翻译成英文", ["KNOWLEDGE_QA"]),
    ("先查询登录模块用例，然后删除刚才查询到的用例", ["CASE_QUERY", "CASE_DELETE"]),
    ("参考历史登录用例，生成一套新版候选供我审阅", ["CASE_GENERATE"]),
]


def main():
    settings = get_settings()
    if settings.agent_provider == "mock" or not settings.agent_api_key:
        raise RuntimeError("Live model configuration required")
    results = []
    output = Path("artifacts/semantic-acceptance/intents.json")
    output.parent.mkdir(parents=True, exist_ok=True)

    def no_rules(_):
        raise AssertionError("Rule classification must not run")

    def run_case(case):
        prompt, expected = case
        plan = plan_intents(
            prompt,
            no_rules,
            has_targets=False,
            phase="idle",
            target_context=[],
            provider=settings.agent_provider,
            model_name=settings.routing_model,
            base_url=settings.agent_base_url,
            api_key=settings.agent_api_key,
            timeout_seconds=settings.agent_timeout_seconds,
            tracing_enabled=False,
        )
        actual = [op.intent for op in plan.operations]
        passed = actual == expected and all(
            op.routing_source == "semantic" for op in plan.operations
        )
        return dict(
            prompt=prompt,
            expected=expected,
            actual=actual,
            passed=passed,
            operations=plan.model_dump(mode="json")["operations"],
        )

    with ThreadPoolExecutor(max_workers=3) as pool:
        for record in pool.map(run_case, CASES):
            results.append(record)
            output.write_text(json.dumps(results, ensure_ascii=False, indent=2))
            print(
                json.dumps(
                    {key: record[key] for key in ("prompt", "passed", "actual")},
                    ensure_ascii=False,
                ),
                flush=True,
            )
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
