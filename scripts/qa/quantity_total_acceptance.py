"""Live total-vs-additional interpretation and latency; no user assets are changed."""
import json
from pathlib import Path
from time import monotonic

from casepilot_agent.config import get_settings
from casepilot_agent.providers import create_provider
from casepilot_agent.quantity import OutputQuantity, QUANTITY_INSTRUCTION, resolve_case_budget


def main():
    settings = get_settings()
    assert settings.provider != "mock", "Real provider required"
    provider = create_provider(settings.provider)
    inventory = [{"id": str(i), "title": f"登录场景{i}", "module": "登录"} for i in range(17)]
    records = []
    output = Path("artifacts/semantic-acceptance/quantity-scope-reuse-repair.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    for prompt, expected in [
        ("17个case太少了，增加到30个", 13),
        ("保留已有用例，再增加30个", 30),
        ("补足到三十条，原来的别动", 13),
        ("只修改第二条标题，不新增用例", None),
        ("只把登录模块补到30条，订单模块不变", 13),
        ("复用已确认的17条用例，再新增13条", 30),
    ]:
        started = monotonic()
        try:
            cases = inventory + ([{"id": f"order-{i}", "title": "订单", "module": "订单"}
                                  for i in range(20)] if "订单" in prompt else [])
            sources = [{"source": {"key": str(i)}, "action": "reuse"} for i in range(17)] if "复用" in prompt else []
            result, _ = provider.complete(
                stage="output_quantity.interpreted", instruction=QUANTITY_INSTRUCTION,
                payload={"prompt": prompt, "existing_cases": cases, "reuse_sources": sources},
                result_type=OutputQuantity, model_id="auto")
            actual = resolve_case_budget(result, cases)
            if actual is not None and not result.count_includes_reuse:
                actual += len(sources)
            record = dict(prompt=prompt, expected=expected, actual=actual,
                          interpretation=result.model_dump(), passed=actual == expected)
        except Exception as error:
            record = dict(prompt=prompt, passed=False, error_type=type(error).__name__)
        record["seconds"] = round(monotonic() - started, 3)
        records.append(record)
        output.write_text(json.dumps(records, ensure_ascii=False, indent=2))
        print(json.dumps(record, ensure_ascii=False), flush=True)
    return int(not all(row["passed"] for row in records))


if __name__ == "__main__":
    raise SystemExit(main())
