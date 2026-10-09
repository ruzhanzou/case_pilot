"""Rebuild the 80-case evidence index; no application mutations or model calls."""
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output/nl-e2e-fix-20261009"
DESIGN = ROOT / "docs/evaluations/casepilot-natural-language-eval-2026-10-09.json"


def main():
    attempts = []

    def walk(node, path):
        for spec in node.get("specs", []):
            for item in spec.get("tests", []):
                for run in item.get("results", []):
                    for case_id in set(re.findall(r"NL-[A-Z]+-\d+", spec["title"])):
                        attempts.append({"id": case_id, "title": spec["title"],
                            "status": run["status"].upper(), "at": run.get("startTime", ""),
                            "evidence": str(path.relative_to(ROOT)),
                            "error": run.get("error", {}).get("message", "")[:1200]})
        for child in node.get("suites", []):
            walk(child, path)

    for path in OUT.glob("*-results.json"):
        try:
            walk(json.loads(path.read_text()), path)
        except json.JSONDecodeError:
            continue

    # Individual journals remain usable when another test in the suite is running.
    for path in OUT.glob("*/*/evidence.json"):
        data = json.loads(path.read_text())
        name = str(data.get("collection", {}).get("name", ""))
        match = re.search(r"NL-[A-Z]+-\d+", name)
        if match and data.get("status"):
            attempts.append({"id": match[0], "status": data["status"].upper(),
                "at": data.get("startedAt", ""), "evidence": str(path.relative_to(ROOT)),
                "error": "\n".join(data.get("errors", []))[:1200]})

    for directory in ["supplement", "supplement-isolated", "compound-isolated",
                      "faults-v3", "fault-continuation"]:
        for path in (OUT / directory).glob("NL-*.json"):
            data = json.loads(path.read_text())
            attempts.append({"id": data["id"], "status": data.get("status", "NOT_RUN"),
                "at": datetime.fromtimestamp(data.get("started", 0), timezone.utc).isoformat(),
                "evidence": str(path.relative_to(ROOT)), "error": data.get("error", "")[:1200]})

    cases = []
    for design in json.loads(DESIGN.read_text())["cases"]:
        history = sorted((x for x in attempts if x["id"] == design["id"]), key=lambda x: x["at"])
        tested = [x for x in history if x["status"] not in {"SKIPPED", "NOT_RUN"}]
        latest = tested[-1] if tested else None
        result = ("PASS" if latest["status"] in {"PASSED", "PASS"} else "FAIL") if latest else "NOT_RUN"
        cases.append({"id": design["id"], "title": design["title"], "result": result,
            "assertions": design["scenario_assertions"], "notes": "",
            "evidence": [latest["evidence"]] if latest else [], "attempts": history})
    by_id = {case["id"]: case for case in cases}

    def assess(code, result, notes, *evidence):
        row = by_id[code]
        row.update(result=result, notes=notes)
        row["evidence"] = list(dict.fromkeys(row["evidence"] + [
            "output/nl-e2e-fix-20261009/" + item for item in evidence]))

    # These qualifications are deliberate: a passing implementation check is not
    # equivalent to every assertion in the wider acceptance design.
    assess("NL-SCP-04", "PARTIAL", "父子模块目标及正式版本通过；未独立核对脑图和列表的范围展示。", "evaluation-results.json")
    assess("NL-SCP-05", "PARTIAL", "同名模块会澄清且不修改；澄清后继续指定模块的路径未单独执行。", "supplement/NL-SCP-05.json")
    assess("NL-REV-04", "PARTIAL", "服务端409且人工版本完整保留；冲突页面中的对象说明及重新生成入口尚未完整验收。", "full-results.json")
    assess("NL-REV-08", "PARTIAL", "取消和再次确认删除已验证；软删除审计记录未单独断言。", "supplement/NL-REV-08.json")
    assess("NL-MUL-06", "PARTIAL", "真实12条完整链路验证部分纳入后只修改剩余候选；与设计的3条固定样本数量不同。", "full-chain-final-results.json", "full-chain-final-journal/deep-results.json")
    assess("NL-MUL-07", "PARTIAL", "12条链路验证候选修改和纳入分离；未使用指定K1/K2/K3三条基线。", "full-chain-final-results.json")
    assess("NL-REC-05", "FAIL", "首批20条落盘后杀死并重启worker；120秒内仍生成中，无恢复或明确失败，随后取消验收任务。", "worker-interrupt.json")
    assess("NL-PER-03", "FAIL", "1/25/100条通过；1000条范围识别约60.85秒超时，未形成可审阅建议。模型调用数及token未完整采集。", "api-capacity-stable/1.json", "api-capacity-stable/25.json", "api-capacity-stable/100.json", "api-capacity-ranges/1000.json")
    assess("NL-PER-04", "PARTIAL", "千条真实数据交互及模拟脑图回归已运行；目标20条自然语言修改未与该UI样本串成完整链路。早期性能数据对应已替换的实现，不作为最终性能结论。", "capacity-results.json", "map-measured-results.json")
    assess("NL-PER-05", "PARTIAL", "五用户各100条采纳均恰增一个版本；记录采纳耗时。尚未同场验证百条保存中的按钮防重复和失败提示。", "concurrency/summary.json", "full-results.json")
    if (OUT / "concurrency/summary.json").exists():
        concurrency = json.loads((OUT / "concurrency/summary.json").read_text())
        assess("NL-PER-06", "PARTIAL" if concurrency["status"] == "PASS" else "FAIL",
            "五用户各100条数据隔离及最终版本通过；每用户仅1次样本，总体分位数仅描述本次运行，不能建立稳定SLA。与其他验收共享服务。", "concurrency/summary.json")
    assess("NL-UX-01", "BLOCKED", "需要首次使用者参与并记录两次确认的误判人数；自动化不能代替此项用户研究。", "full-retry-results.json")
    assess("NL-UX-03", "PARTIAL", "12条链路覆盖3条部分纳入及9条剩余候选，未按设计的正式1/候选2/目标2逐视图核对。", "full-chain-final-results.json")
    assess("NL-UX-05", "PARTIAL", "键盘提交、确认、审阅及采纳通过，留有焦点截图；没有独立断言弹窗关闭后的焦点恢复。", "recovery-ui-results.json")
    assess("NL-UX-06", "PARTIAL", "640×360 CSS视口可操作，用作1280×720下200%缩放的布局近似；没有实际浏览器缩放验收。", "recovery-ui-results.json")
    assess("NL-SEC-01", "BLOCKED", "当前角色模型只有owner/member，无法建立只读成员前提；越权账号拒绝写入由SEC-02覆盖，不能替代只读角色验收。")
    assess("NL-SEC-04", "PARTIAL", "脚本式标题在审阅、列表和脑图中无img节点且不触发dialog；未记录完整外部请求列表。", "evaluation-results.json")

    # Additional evaluated mappings and overrides are maintained separately so
    # re-indexing completed tests does not erase a reviewed qualification.
    override_path = OUT / "acceptance-overrides.json"
    if override_path.exists():
        for code, value in json.loads(override_path.read_text()).items():
            assess(code, value["result"], value["notes"], *value.get("evidence", []))
    output = {"schema_version": "1.0", "updated_at": datetime.now(timezone.utc).isoformat(),
        "decision": "NOT_ACCEPTED", "counts": dict(Counter(x["result"] for x in cases)),
        "limitations": ["80条为验收设计数，不等于80条已通过。", "10条预留同义盲测未执行。",
                        "历史失败与修复后复测均保留；不能把重跑次数算作独立验收条目。"], "cases": cases}
    (OUT / "acceptance-matrix.json").write_text(json.dumps(output, ensure_ascii=False, indent=2))
    report = ROOT / "docs/test-reports/natural-language-full-acceptance-2026-10-09.md"
    if report.exists():
        labels = {"PASS": "通过", "FAIL": "失败", "PARTIAL": "部分覆盖",
                  "BLOCKED": "前提阻塞", "NOT_RUN": "未执行"}
        counts = "，".join(f"{labels.get(key, key)} {value} 条"
                           for key, value in output["counts"].items())
        rows = ["## 逐条验收结果", "", f"共 80 条：{counts}。", "",
                "通过表示本条记录中的自动化断言通过；部分覆盖及前提阻塞均不计为通过。",
                "", "| 编号 | 场景 | 判定 | 说明与证据 |", "| --- | --- | --- | --- |"]
        for case in cases:
            note = case["notes"] or ("自动化断言通过。" if case["result"] == "PASS" else "见原始执行结果。")
            links = " ".join(f"[证据{index + 1}](../../{path})"
                             for index, path in enumerate(case["evidence"]))
            rows.append(f"| {case['id']} | {case['title']} | {labels[case['result']]} | {note.replace('|', '／')} {links} |")
        start, end = "<!-- ACCEPTANCE_MATRIX_START -->", "<!-- ACCEPTANCE_MATRIX_END -->"
        source = report.read_text()
        before, remainder = source.split(start, 1)
        _, after = remainder.split(end, 1)
        report.write_text(before + start + "\n" + "\n".join(rows) + "\n" + end + after)
    print(json.dumps(output["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
