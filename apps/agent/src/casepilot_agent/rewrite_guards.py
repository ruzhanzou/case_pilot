"""Deterministic preservation rules applied to every rewrite round."""

import re

_SETUP_OPERATIONS = (
    (
        "签发验证码",
        r"(?:已|已经|成功|完成).{0,16}(?:签发|获取).{0,8}验证码",
        r"(?:调用|请求|重新|再次|执行|发起).{0,12}签发.{0,8}验证码|(?:重新|再次)?获取验证码",
        r"(?:重新|再次|重复|先|调用|执行|发起|补充|增加|新增).{0,12}(?:签发|获取).{0,8}验证码",
    ),
    (
        "注册账号",
        r"(?:账号|用户|手机号).{0,10}(?:已|已经|成功|完成).{0,6}注册|(?:已|已经|成功|完成).{0,10}注册",
        r"(?:重新|再次|执行|发起|完成|创建).{0,8}注册|注册(?:账号|用户|手机号)",
        r"(?:重新|再次|重复|先|执行|发起|补充|增加|新增).{0,10}注册",
    ),
    (
        "创建数据",
        r"(?:数据|订单|记录|对象|资源).{0,12}(?:已|已经|成功|完成).{0,6}创建|(?:已|已经|成功|完成).{0,10}创建",
        r"(?:重新|再次|执行|发起).{0,8}创建|创建(?:数据|订单|记录|对象|资源)",
        r"(?:重新|再次|重复|先|执行|发起|补充|增加|新增).{0,10}创建",
    ),
    (
        "上传文件",
        r"(?:文件|附件).{0,10}(?:已|已经|成功|完成).{0,6}上传|(?:已|已经|成功|完成).{0,10}上传",
        r"(?:重新|再次|执行|发起).{0,8}上传|上传(?:文件|附件)",
        r"(?:重新|再次|重复|先|执行|发起|补充|增加|新增).{0,10}上传",
    ),
)


def _requested_action_rewrite(instruction: str) -> bool:
    clauses = re.split(r"[，。；;\n]", instruction)
    return any(
        re.search(r"(?:改写|重写|修改|优化|整理|完善|补充)[^，。；;\n]*步骤", clause)
        and not re.search(r"不(?:要|得|能)?(?:改写|重写|修改)|禁止", clause)
        for clause in clauses
    ) and not preserves(instruction, r"(?:操作|执行)?步骤")


def _boundary_variants(instruction: str) -> list[set[str]]:
    """Return explicit numeric boundaries, including exact unit conversions."""
    groups: list[set[str]] = []
    for number, unit in re.findall(
        r"(?<![\d.])(\d+(?:\.\d+)?)\s*(毫秒|ms|秒|s|分钟|分|小时|天|次|个|元|%|％)",
        instruction,
        re.I,
    ):
        canonical = f"{number.rstrip('0').rstrip('.') if '.' in number else number}{unit.lower()}"
        variants = {canonical}
        value = float(number)
        if unit in {"秒", "s"} and value >= 60 and value % 60 == 0:
            minutes = int(value / 60)
            variants.update({f"{minutes}分钟", f"{minutes}分"})
        elif unit in {"分钟", "分"}:
            seconds = value * 60
            if seconds.is_integer():
                variants.update({f"{int(seconds)}秒", f"{int(seconds)}s"})
        groups.append({re.sub(r"\s+", "", item).lower() for item in variants})
    return groups


def _result_trigger_steps(instruction: str, proposed):
    """Prefer steps that assert an explicit result marker; otherwise use the final check."""
    checked = [step for step in proposed.steps if step.action.strip() and step.expected.strip()]
    if not checked:
        return []
    markers = set(
        re.findall(
            r"\b(?=[A-Z0-9_-]*[A-Z])(?=[A-Z0-9_-]*\d)[A-Z][A-Z0-9_-]{2,}\b",
            instruction,
        )
    )
    marked = [step for step in checked if any(marker in step.expected for marker in markers)]
    return marked or checked[-1:]


def _setup_reexecution_issues(request, original, proposed) -> list[str]:
    if not _requested_action_rewrite(request.instruction):
        return []
    original_actions = "\n".join(step.action for step in original.steps)
    proposed_actions = "\n".join(step.action for step in proposed.steps)
    if re.sub(r"\s+", "", original_actions) == re.sub(r"\s+", "", proposed_actions):
        return []
    setup = "\n".join(original.preconditions)
    issues = []
    for label, setup_pattern, action_pattern, permission_pattern in _SETUP_OPERATIONS:
        if (
            re.search(setup_pattern, setup)
            and re.search(action_pattern, proposed_actions)
            and not re.search(action_pattern, original_actions)
            and not re.search(permission_pattern, request.instruction)
        ):
            issues.append(
                f"前置条件已声明{label}完成，不得在步骤中再次执行；只补充记录、边界推进或触发验证所需操作"
            )
    return issues


def complete_reference_trigger_boundaries(request, proposed):
    """Fill an explicit boundary into the business-result action when unambiguous."""
    if (
        not request.context.get("approved_reference_assets")
        or not _requested_action_rewrite(request.instruction)
        or not preserves(request.instruction, r"预期(?:结果)?|校验点|检查点")
        or _setup_reexecution_issues(request, request.test_case, proposed)
    ):
        return proposed
    boundaries = _boundary_variants(request.instruction)
    original_actions = re.sub(
        r"\s+", "", "\n".join(step.action for step in request.test_case.steps)
    ).lower()
    trigger_steps = _result_trigger_steps(request.instruction, proposed)
    missing = [
        group
        for group in boundaries
        if any(term in original_actions for term in group)
        and not any(
            any(term in re.sub(r"\s+", "", step.action).lower() for term in group)
            for step in trigger_steps
        )
    ]
    if not missing or not trigger_steps:
        return proposed
    completed = proposed.model_copy(deep=True)
    completed_triggers = _result_trigger_steps(request.instruction, completed)
    normalized_instruction = re.sub(r"\s+", "", request.instruction).lower()
    labels = [
        next(
            (
                term
                for term in sorted(group, key=len, reverse=True)
                if term in normalized_instruction
            ),
            sorted(group, key=len, reverse=True)[0],
        )
        for group in missing
    ]
    prefix = f"在{'、'.join(labels)}边界条件下，"
    for step in completed_triggers:
        step.action = prefix + step.action
    return completed


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
    requests_actions = _requested_action_rewrite(request.instruction)
    if requests_actions and normalized([s.action for s in original.steps]) == normalized(
        [s.action for s in proposed.steps]
    ):
        return (
            "参考改写未改变操作步骤；请采用已确认参考中的相关操作细节，"
            "遵循当前规则和保留约束，不能仅更新来源或空白。"
            "比较基准是items.test_case，不能将参考旧值到候选已有值当作修改；"
            "请补足参考中相关且当前操作尚未明确的细节，不要原样返回已有操作"
        )
    fields = ("title", "module", "priority", "case_type", "tags", "preconditions", "steps")
    if all(normalized(before[field]) == normalized(after[field]) for field in fields):
        return (
            "参考改写未产生实质内容变化；来源引用不算改写。"
            "请按当前要求修改相关内容；没有适用变化时不要编造修改"
        )
    issues = _setup_reexecution_issues(request, original, proposed)
    original_actions = "\n".join(step.action for step in original.steps)
    proposed_actions = "\n".join(step.action for step in proposed.steps)
    boundaries = _boundary_variants(request.instruction)
    if (
        requests_actions
        and preserves(request.instruction, r"预期(?:结果)?|校验点|检查点")
        and boundaries
        and normalized(original_actions) != normalized(proposed_actions)
    ):
        trigger_actions = [
            re.sub(r"\s+", "", step.action).lower()
            for step in _result_trigger_steps(request.instruction, proposed)
        ]
        missing = [
            sorted(group, key=len, reverse=True)[0]
            for group in boundaries
            if any(term in normalized(original_actions).lower() for term in group)
            and not any(any(term in action for term in group) for action in trigger_actions)
        ]
        if missing:
            issues.append(
                "关键边界必须同时写入触发预期结果的操作，避免“该数据”等指代失去条件："
                + "、".join(missing)
            )
    if issues:
        return "；".join(issues)
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
