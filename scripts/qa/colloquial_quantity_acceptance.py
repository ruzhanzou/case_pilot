"""Live contextual quantity probes; these do not substitute for workflow tests."""
import argparse
import json
from pathlib import Path
from casepilot_agent.config import get_settings
from casepilot_agent.providers import create_provider
from casepilot_agent.quantity import QUANTITY_INSTRUCTION, OutputQuantity

CASES = [
    ("不用五条了，三条就行，测试点还是原来的两个。", "规划两个测试点，生成五条用例", 3, 2),
    ("就按刚才的数量生成。", "规划两个测试点，生成四条用例", 4, 2),
    ("每个点各来两条，普通账号和管理员账号各一条。", "确认两个测试点：成功登录、失败登录", 4, 2),
    ("先别生成，只解释四条是否够用。", "规划两个测试点，生成四条用例", None, None),
    ("不是改成两条，是再生成两条，已有的三条别动。", "已经生成三条用例", 2, None),
    ("用例一共四条就够，原有的两条保留，再补缺少的。", "已有两条用例", 2, None),
    ("两个测试点不变，别增加测试点，每个点普通账号和管理员账号各一条。", "规划两个测试点，生成两条用例", 4, 2),
    ("只把第二条标题改了，不新增。", "生成四条用例", None, None),
]

EXPRESSION_CASES = [
    ("两点，每点各来三条，普通、管理员、访客各一条；别拆成六个点。", "", 6, 2),
    ("五条太多，留三条就行，我说的是要生成的用例数。", "要生成五条用例", 3, None),
    ("凑够六条就停，已经有四条了，只补差的。", "当前集合已有四条用例", 2, None),
    ("不是再加四条，是加完一共四条；原来的三条留着。", "当前已有三条用例", 1, None),
    ("Don't make five. Generate three cases for the same two test points.", "Plan two test points and five cases", 3, 2),
    ("先来一打用例，测试点别限定数量。", "", 12, None),
    ("账号三种，各两条，用例一共六条；测试点就两个。", "", 6, 2),
    ("密码错三回锁五分钟，密码八到二十位。帮我生成用例，数量按覆盖需要来。", "", None, None),
    ("一条也别新增，现有第二条的标题改一下。", "刚生成四条用例", None, None),
    ("先别执行，我只是问：如果生成十条够不够？", "", None, None),
]

def main(output_path, expressions=False):
    settings = get_settings()
    assert settings.provider != "mock"
    provider = create_provider(settings.provider)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    records = []
    for prompt, history, case_count, point_count in (EXPRESSION_CASES if expressions else CASES):
        expected = {"case_count": case_count, "test_point_count": point_count}
        record = {"prompt": prompt, "history": history, "expected": expected}
        try:
            actual, _ = provider.complete(stage="output_quantity.interpreted", instruction=QUANTITY_INSTRUCTION,
                payload={"prompt": prompt, "conversation_memory": [{"role": "user", "content": history}]},
                result_type=OutputQuantity, model_id="doubao-seed-2.0-lite")
            record.update(actual=actual.model_dump(), passed=actual.model_dump() == expected)
        except Exception as exc:
            record.update(passed=False, error_type=type(exc).__name__)
        records.append(record)
        output.write_text(json.dumps(records, ensure_ascii=False, indent=2))
        print(json.dumps(record, ensure_ascii=False), flush=True)
    return int(not all(r["passed"] for r in records))

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="artifacts/natural-language-freedom/quantity-round-2.json")
    p.add_argument("--expressions", action="store_true")
    args = p.parse_args()
    raise SystemExit(main(args.output, args.expressions))
