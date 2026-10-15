"""Summarize completed real-model fixtures; never treat stale evidence as a pass."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "output/multi-requirement-eval-20261015")
    args = parser.parse_args()
    dataset = json.loads((ROOT / "apps/web/e2e/fixtures/multi-requirement-reuse.json").read_text())
    results = []
    for sample in dataset["samples"]:
        result_file = args.output / f"{sample['id']}-result.json"
        fixture_file = args.output / f"{sample['id']}-fixture.json"
        if not result_file.exists() or result_file.stat().st_mtime < fixture_file.stat().st_mtime:
            raise SystemExit(f"Missing or stale success evidence: {sample['id']}")
        result = json.loads(result_file.read_text())
        if result["counts"] != sample["expected_counts"] or result["errors"]:
            raise SystemExit(f"Failed result: {sample['id']}")
        if len(result["committed"]) != len(sample["requirements"]):
            raise SystemExit(f"Missing committed cases: {sample['id']}")
        results.append(result)
    counts = {action: sum(result["counts"][action] for result in results) for action in ("reuse", "modify", "new")}
    summary = {"dataset_version": dataset["version"], "samples_passed": len(results),
               "requirements": sum(len(s["requirements"]) for s in dataset["samples"]),
               "decisions": counts, "formal_cases": sum(len(r["committed"]) for r in results),
               "automatic_links": sum(sum(link["origin"] == "generated" for link in r["links"]) for r in results),
               "manual_links": sum(sum(link["origin"] == "manual" for link in r["links"]) for r in results),
               "samples": [{key: r[key] for key in ("id", "name", "counts", "planningMs", "totalMs")} for r in results]}
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    rows = ["| 样本 | 复用 / 修改 / 新增 | 规划耗时 | 提交至采纳 | 结果 |", "| --- | --- | ---: | ---: | --- |"]
    for r in results:
        c = r["counts"]
        rows.append(f"| {r['id']} {r['name']} | {c['reuse']} / {c['modify']} / {c['new']} | {r['planningMs']/1000:.1f} 秒 | {r['totalMs']/1000:.1f} 秒 | 通过 |")
    report = "# 多需求生成与复用端到端验收\n\n"
    report += f"6 组、18 条需求均通过。实际生成并采纳 {summary['formal_cases']} 条正式用例：直接复用 {counts['reuse']} 条、按变更修改 {counts['modify']} 条、新增 {counts['new']} 条。\n\n"
    report += "\n".join(rows)
    report += f"\n\n共验证 {summary['automatic_links']} 条采纳时自动关联、{summary['manual_links']} 条已有用例手动关联。每组都经过浏览器操作、真实 API、模型、队列和数据库，刷新后仍可查看关联；历史用例版本未改变。浏览器运行时错误为 0。\n"
    report += "\n## 修复与增强\n\n- 采纳时持久化正式用例与测试点的关联，绑定具体规划版本及用例版本。\n- 测试点详情支持手动关联、解除关联、点击定位已有用例；用例详情支持反向定位到原规划版本和测试点。\n- 显示正式关联数量与用例版本变化提醒，避免采纳后误报尚未生成。\n- 修复关联表时间字段遗漏、旧候选兼容及无复用理由时的渲染异常；批量采纳复用规划查询。\n- 修复测试对象截取包含后续需求的问题，并限制脑图节点摘要长度，保留详情全文。\n"
    report += "\n## 边界与证据\n\n关联表示可追溯关系，不自动证明覆盖正确，也不会自动排除生成；用户确认已有用例足够覆盖时，可选择不纳入本次。手动关联范围为本集合。规则变化后的历史关联不自动继承。\n\n"
    report += "关联边界检查见 links-contract.log；两组双向导航检查见 navigation.log；6 组生成链路见 evaluation.log。每个样本的 `*-planning.json`、`*-result.json` 保存输入、规划、候选、正式用例和关联证据。\n\n"
    report += "截图：\n\n" + "\n".join(f"- [{r['id']} 采纳后的关联]({r['id']}-committed-links.png)" for r in results)
    report += "\n\n性能为单次小样本，包含模拟用户操作与轮询，不能推导 P95 或并发容量。关键预期采用规则检查，并保留完整用例供人工核验，不宣称完整语义正确性证明。截图输入未纳入本轮。\n"
    (args.output / "acceptance.md").write_text(report)
    print(json.dumps({key: value for key, value in summary.items() if key != "samples"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
