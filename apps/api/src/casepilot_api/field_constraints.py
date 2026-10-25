"""Shared field constraints for persisted cases and interpreted assignments."""

PRIORITIES = ("P0", "P1", "P2")
PRIORITY_PATTERN = r"^(?:" + "|".join(PRIORITIES) + r")$"
PRIORITY_ASSIGNMENT_DESCRIPTION = (
    "本轮明确要求写入优先级字段的新值，逐字提取，即使无效也原样返回，不纠正或猜测。"
    "没有赋值则null；查询/筛选条件、否定或撤回的值、标题/步骤中的文字不属于优先级赋值。"
    "例如优先级改成P9返回P9；不是P9改P2返回P2；标题改为P9返回null。"
)


def priority_assignment_error(value: str | None) -> str | None:
    if value is None or value in PRIORITIES:
        return None
    return f"优先级 {value} 不受支持，请选择 {'、'.join(PRIORITIES)}。其他修改要求已保留。"
