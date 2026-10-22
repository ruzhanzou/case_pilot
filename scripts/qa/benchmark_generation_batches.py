"""Real-provider batch matrix. Stores timing/contracts, never credentials."""

import json
import os
import time
from pathlib import Path
from threading import Lock
from dotenv import load_dotenv

root = Path(__file__).resolve().parents[2]
load_dotenv(root / ".env")
from casepilot_agent.config import get_settings
from casepilot_agent.contracts import GenerationRequest
from casepilot_agent.pipeline import GenerationPipeline
from casepilot_agent.providers import create_provider

output = (
    root
    / "output/journey-acceptance-20261021"
    / os.environ.get("BENCHMARK_OUTPUT", "batch-benchmark.json")
)
provider = create_provider(get_settings().provider)
# Independent, explicitly stated endpoints avoid artificial identical-case padding.
count = int(os.environ.get("BENCHMARK_CASE_COUNT", "20"))
requirements = "\n".join(
    f"规则R{i}：已登录管理员访问独立报表端点/report/{i}，返回报表{i}及状态200。"
    for i in range(count)
)
plan = {
    "feature_points": [
        {
            "id": "F1",
            "name": "报表读取",
            "description": requirements,
            "module": "报表",
            "requirement_refs": ["R1"],
            "source_refs": [],
        }
    ],
    "test_points": [
        {
            "id": f"P{i}",
            "title": f"R{i}读取报表{i}",
            "scenario": f"独立报表{i}",
            "objective": f"访问/report/{i}返回报表{i}及状态200",
            "feature_point_ids": ["F1"],
            "source_refs": [],
            "priority": "P1",
            "priority_reason": "报表读取失败影响业务",
            "category": "functional",
        }
        for i in range(count)
    ],
}
results = []
configurations = [
    tuple(map(int, value.split(":")))
    for value in os.environ.get(
        "BENCHMARK_CONFIGS", "3:1,3:2,3:4,5:1,5:2,5:4,10:1,10:2,10:4"
    ).split(",")
]
for repetition in range(int(os.environ.get("BENCHMARK_REPEATS", "1"))):
    for size, concurrency in configurations:
        start = time.monotonic()
        calls, previews = [], []
        lock = Lock()

        def execute(stage, instruction, payload, result_type, model_id):
            began = time.monotonic()
            try:
                result, usage = provider.complete(
                    stage=stage,
                    instruction=instruction,
                    payload=payload,
                    result_type=result_type,
                    model_id=model_id,
                )
                with lock:
                    calls.append(
                        {
                            "stage": stage,
                            "seconds": time.monotonic() - began,
                            "usage": usage.model_dump(mode="json"),
                            "input_chars": len(json.dumps(payload, ensure_ascii=False)),
                            "slots": payload.get("batch_slots"),
                            "retry": payload.get("retry_attempt"),
                            "prompt_version": payload.get("prompt_version"),
                        }
                    )
                return result
            except Exception as exc:
                with lock:
                    calls.append(
                        {
                            "stage": stage,
                            "seconds": time.monotonic() - began,
                            "error": type(exc).__name__,
                        }
                    )
                raise

        request = GenerationRequest(
            prompt="测试对象：报表验收系统。\n" + requirements,
            confirmed_plan=plan,
            output_contract=os.environ.get("BENCHMARK_CONTRACT", "case_batch_v2"),
            batch_size=size,
            batch_concurrency=concurrency,
        )
        try:
            result = GenerationPipeline(provider).run(
                request,
                context={},
                answers={},
                execute_stage=execute,
                on_batch=lambda cases, total: previews.append(
                    {"seconds": time.monotonic() - start, "count": len(cases)}
                ),
            )
            row = {
                "contract": request.output_contract,
                "effective_batch_size": 20 if request.output_contract == "legacy" else size,
                "size": size,
                "concurrency": concurrency,
                "seconds": time.monotonic() - start,
                "calls": calls,
                "previews": previews,
                "count": len(result.test_cases),
                "quality": result.quality.model_dump(mode="json"),
                "cases": [case.model_dump(mode="json") for case in result.test_cases],
            }
        except Exception as exc:
            row = {
                "size": size,
                "concurrency": concurrency,
                "seconds": time.monotonic() - start,
                "calls": calls,
                "error": type(exc).__name__,
            }
        results.append(row)
        output.write_text(
            json.dumps(
                {"model": get_settings().model, "case_count": count, "runs": results},
                ensure_ascii=False,
                indent=2,
            )
        )
        print(
            size,
            concurrency,
            round(row["seconds"], 2),
            row.get("count"),
            row.get("error"),
            flush=True,
        )
