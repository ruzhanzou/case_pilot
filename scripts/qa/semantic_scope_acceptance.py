"""Read-only model acceptance for review-all, quantities, references and collections."""

import json
from pathlib import Path

from casepilot_api.agent_router import select_case_scope
from casepilot_api.config import get_settings
from casepilot_api.generation_strategy import interpret_generation_choice

CATALOG = [
    {
        "id": f"case-{i}",
        "case_key": f"AUTH-{i:03}",
        "kind": "formal",
        "title": title,
        "module": module,
        "priority": priority,
        "steps": [{"action": "登录", "expected": "成功"}],
    }
    for i, (title, module, priority) in enumerate(
        [
            ("密码登录", "登录", "P0"),
            ("短信登录", "登录", "P1"),
            ("账号退出", "登录", "P1"),
            ("下单", "订单", "P0"),
        ],
        1,
    )
]
CASES = [
    ("review全部", "CASE_REVIEW", {item["id"] for item in CATALOG}, None),
    ("评审全部登录模块用例，但P0先不评审", "CASE_REVIEW", {"case-2", "case-3"}, None),
    ("把刚才查到的这两条用例优先级改为P0", "CASE_MODIFY", {"case-2", "case-3"}, 2),
    ("查询用例AUTH-002", "CASE_QUERY", {"case-2"}, None),
]
COLLECTIONS = [
    {"id": "collection-login", "name": "登录"},
    {"id": "collection-order", "name": "订单"},
]


def main():
    s = get_settings()
    assert s.agent_provider != "mock"
    output = Path("artifacts/semantic-acceptance/scopes.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    results = []

    def record(item):
        results.append(item)
        output.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(json.dumps(item, ensure_ascii=False), flush=True)

    for prompt, intent, expected, count in CASES:
        result = select_case_scope(
            prompt,
            CATALOG,
            {
                "phase": "maintenance",
                "selected_ids": [],
                "latest_query": {"ids": ["case-2", "case-3"]},
            },
            intent=intent,
            model_name=s.routing_model,
            base_url=s.agent_base_url,
            api_key=s.agent_api_key,
            timeout_seconds=s.agent_timeout_seconds,
            tracing_enabled=False,
        )
        record(
            dict(
                prompt=prompt,
                actual=result.model_dump(),
                passed=not result.ambiguous
                and set(result.ids) == expected
                and (count is None or result.requested_count == count),
            )
        )
    for prompt, expected in [
        ("请评审订单集合中的全部用例", "collection-order"),
        ("为订单业务增加用例，继续维护当前集合", None),
        ("不要切换到订单集合", None),
    ]:
        result = interpret_generation_choice(
            prompt, s, collection_catalog=COLLECTIONS, explicit_collection_only=True
        )
        record(
            dict(
                prompt=prompt,
                expected=expected,
                actual=result.target_collection_id,
                passed=result.target_collection_id == expected,
            )
        )
    return int(not all(item["passed"] for item in results))


if __name__ == "__main__":
    raise SystemExit(main())
