"""Live acceptance for output quantities; no application assets are mutated."""

import json
from pathlib import Path

from casepilot_agent.config import get_settings
from casepilot_agent.providers import create_provider
from casepilot_agent.quantity import QUANTITY_INSTRUCTION, OutputQuantity

CASES = [
    ("生成七个登录测试点", None, 7),
    ("不要十条，改成七条登录用例", 7, None),
    ("密码8到20位，失败5次锁定30分钟，生成测试用例", None, None),
    ("为三个模块各生成四条用例", 12, None),
    ("生成20条用例，测试点按覆盖需要设计", 20, None),
    ("Generate exactly a dozen test points for login", None, 12),
    ("先生成八个测试点，再据此生成二十条用例", 20, 8),
    ("评审全部已有用例，其中5条为P0，不新增用例", None, None),
    ("生成五百零一个测试点", None, 501),
]


def main():
    settings = get_settings()
    if settings.provider == "mock":
        raise RuntimeError("Live model configuration required")
    provider = create_provider(settings.provider)
    results = []
    output = Path("artifacts/semantic-acceptance/quantity.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    for prompt, cases, points in CASES:
        try:
            actual, _ = provider.complete(
                stage="output_quantity.interpreted",
                instruction=QUANTITY_INSTRUCTION,
                payload={"prompt": prompt},
                result_type=OutputQuantity,
                model_id="auto",
            )
            record = dict(
                prompt=prompt,
                expected=dict(case_count=cases, test_point_count=points),
                actual=actual.model_dump(),
                passed=actual.case_count == cases and actual.test_point_count == points,
            )
        except Exception as error:
            record = dict(prompt=prompt, passed=False, error_type=type(error).__name__)
        results.append(record)
        output.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(json.dumps(record, ensure_ascii=False), flush=True)
    return int(not all(record["passed"] for record in results))


if __name__ == "__main__":
    raise SystemExit(main())
