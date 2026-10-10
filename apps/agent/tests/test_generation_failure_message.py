from casepilot_agent.store import generation_failure_message


def test_quality_failure_names_actionable_reasons() -> None:
    message = generation_failure_message(
        "GenerationQualityError",
        {
            "quality": {
                "issues": [
                    {"severity": "error", "message": "测试点没有关联用例"},
                    {"severity": "error", "message": "用例缺少可观察的预期结果"},
                    {"severity": "warning", "message": "标题可能重复"},
                ]
            }
        },
    )
    assert "测试点没有关联用例" in message
    assert "用例缺少可观察的预期结果" in message
    assert "标题可能重复" not in message


def test_quality_failure_without_report_keeps_general_guidance() -> None:
    assert "补充需求后重试" in generation_failure_message(
        "GenerationQualityError", {}
    )


def test_format_failure_reports_preserved_previews():
    message = generation_failure_message("StageContractError", {"generated_count": 5, "total_count": 10})
    assert "本次处理已停止" in message
    assert "5 条预览已保留" in message
    assert "复用已完成阶段" in message
