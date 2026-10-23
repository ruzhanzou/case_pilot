"""Deterministic preservation rules applied to every rewrite round."""

import re


def preserves(instruction: str, label: str) -> bool:
    """Recognize both '保留预期结果' and '预期结果保持不变'."""
    return bool(
        re.search(
            rf"(?:保留|保持|不修改|不改变|不改动|不要改|不改)[^，。；;\n]{{0,12}}(?:{label})"
            rf"|(?:{label})[^，。；;\n]{{0,8}}(?:保持不变|不变|不修改|不改动|不改)",
            instruction,
        )
    )


def additive_only(instruction: str) -> bool:
    instruction = re.sub(
        r"(?:不要|不得|不能|禁止|不)(?:修改|调整|删除|移除|替换|重写|合并|精简)", "", instruction
    )
    adds = bool(re.search(r"增加|新增|添加|追加|补充|\b(?:add|append)\b", instruction, re.I))
    return adds and not bool(
        re.search(
            r"删除|移除|删去|去掉|替换|改为|修改|调整|修正|重写|重构|拆分|合并|精简|优化|整理"
            r"|\b(?:remove|delete|replace|rewrite|modify|merge)\b",
            instruction,
            re.I,
        )
    )


def permits_step_removal(instruction: str) -> bool:
    # Negated deletion instructions must not grant permission to drop steps.
    clauses = re.split(r"[，。；;\n]", instruction)
    return any(
        re.search(r"删除|移除|删去|去掉|合并|精简|\b(?:remove|delete|merge)\b", clause, re.I)
        and not re.search(
            r"不要|不得|不能|禁止|不允许|不删|不移除|不合并|不精简"
            r"|\b(?:not|never|don't)\b",
            clause,
            re.I,
        )
        for clause in clauses
    )


def contains_in_order(original, proposed) -> bool:
    """Keep duplicates and their order; a set comparison would miss lost rows."""
    remaining = iter(proposed)
    return all(any(item == value for value in remaining) for item in original)


def reference_rewrite_error(request, proposed) -> str | None:
    """Confirmed reference rewrites must change content, not just citations."""
    if not request.context.get("approved_reference_assets"):
        return None
    original = request.test_case
    # Compare normalized text so whitespace-only edits do not satisfy the request.
    def normalized(value):
        if isinstance(value, str):
            return re.sub(r"\s+", "", value)
        if isinstance(value, list):
            return [normalized(item) for item in value]
        if isinstance(value, dict):
            return {key: normalized(item) for key, item in value.items()}
        return value

    before, after = original.model_dump(), proposed.model_dump()
    clauses = re.split(r"[，。；;\n]", request.instruction)
    requests_actions = any(
        re.search(r"(?:改写|重写|修改|优化|整理|完善|补充)[^，。；;\n]*步骤", clause)
        and not re.search(r"不(?:要|得|能)?(?:改写|重写|修改)|禁止", clause)
        for clause in clauses
    ) and not preserves(request.instruction, r"(?:操作|执行)?步骤")
    if requests_actions and normalized([s.action for s in original.steps]) == normalized(
        [s.action for s in proposed.steps]
    ):
        return ("参考改写未改变操作步骤；请采用已确认参考中的相关操作细节，"
                "遵循当前规则和保留约束，不能仅更新来源或空白。"
                "比较基准是items.test_case，不能将参考旧值到候选已有值当作修改；"
                "请补足参考中相关且当前操作尚未明确的细节，不要原样返回已有操作")
    fields = ("title", "module", "priority", "case_type", "tags", "preconditions", "steps")
    if all(normalized(before[field]) == normalized(after[field]) for field in fields):
        return ("参考改写未产生实质内容变化；来源引用不算改写。"
                "请按当前要求修改相关内容；没有适用变化时不要编造修改")
    return None


def preservation_error(request, proposed) -> str | None:
    original, instruction = request.test_case, request.instruction
    fields = {
        "title": "标题",
        "module": "模块",
        "priority": "优先级",
        "preconditions": "前置条件",
        "tags": "标签",
        "source_refs": "来源|引用",
    }
    for field, label in fields.items():
        if preserves(instruction, label) and getattr(original, field) != getattr(proposed, field):
            return f"改写违反保留{label}的要求；请保留原字段值"
    actions = [s.action for s in original.steps if s.action.strip()]
    new_actions = [s.action for s in proposed.steps if s.action.strip()]
    expected = [s.expected for s in original.steps if s.expected.strip()]
    new_expected = [s.expected for s in proposed.steps if s.expected.strip()]
    actions_preserved = (
        contains_in_order(actions, new_actions)
        if additive_only(instruction)
        else actions == new_actions
    )
    if preserves(instruction, r"(?:操作|执行)?步骤") and not actions_preserved:
        return "改写违反保留操作步骤的要求；请使用expected_updates，仅更新预期"
    if preserves(instruction, r"预期(?:结果)?|校验点|检查点") and (
        not contains_in_order(expected, new_expected)
        or (not additive_only(instruction) and expected != new_expected)
    ):
        return "改写违反保留预期结果的要求；保留全部原校验点，仅更新操作"
    if additive_only(instruction):
        before = [(s.action, s.expected) for s in original.steps]
        after = [(s.action, s.expected) for s in proposed.steps]
        if not contains_in_order(before, after):
            return "补充操作遗漏或覆盖了原步骤/校验点；请使用append_steps追加，保留全部原步骤"
        for field in ("preconditions", "tags", "source_refs"):
            if not contains_in_order(getattr(original, field), getattr(proposed, field)):
                return f"补充操作遗漏原{field}；请保留原条目并追加"
    if not permits_step_removal(instruction) and (
        len(new_actions) < len(actions) or len(proposed.steps) < len(original.steps)
    ):
        return "未经要求不得减少原步骤；请使用step_updates局部修改或append_steps追加"
    return None
