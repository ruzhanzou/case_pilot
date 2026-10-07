"""Resolve explicit user references against the current collection, never other spaces."""

import re


def module_parts(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in re.split(r"\s*(?:/|>|::|／)\s*", value) if part.strip())


def module_contains(parent: str, child: str) -> bool:
    prefix, path = module_parts(parent), module_parts(child)
    return path[: len(prefix)] == prefix if prefix else not path


def common_module_path(modules: list[str]) -> str:
    paths = [module_parts(value) for value in modules if value]
    if not paths:
        return ""
    common = list(paths[0])
    for path in paths[1:]:
        matched = 0
        while matched < min(len(common), len(path)) and common[matched] == path[matched]:
            matched += 1
        common = common[:matched]
    return "/".join(common)


def resolve_scope(instruction: str, cases: list[dict]) -> dict | None:
    """None means implicit selection; an explicit empty/error scope must not fall back."""
    text = re.sub(r"\s*(?:/|>|::|／)\s*", "/", instruction).casefold()
    if re.search(r"排除|除外|除了|\b(?:except|excluding)\b", text):
        return {"ids": [], "modules": [], "error": "请在工作区选择排除后的具体范围，避免误操作。"}
    keys = [
        case
        for case in cases
        if any(
            value
            and re.search(
                r"(?<![a-z0-9_-])" + re.escape(value.casefold()) + r"(?![a-z0-9_-])", text
            )
            for value in [str(case.get("case_key", ""))]
        )
        or (len(str(case.get("title", ""))) >= 4 and str(case["title"]).casefold() in text)
    ]
    requested_keys = re.findall(
        r"(?<![a-z0-9_-])(?:CP|CASE|TC|MAP\d*)-[A-Za-z0-9-]+(?![a-z0-9_-])", instruction, re.I
    )
    known_keys = {str(case.get("case_key", "")).casefold() for case in cases}
    if any(key.casefold() not in known_keys for key in requested_keys):
        return {"ids": [], "modules": [], "error": "未找到指定编号的用例，请检查编号或当前集合。"}
    if keys:
        return {"ids": [str(case["id"]) for case in keys], "modules": []}
    paths = {str(case.get("module", "")) for case in cases if case.get("module")}
    aliases: dict[str, set[str]] = {}
    for path in paths:
        parts = module_parts(path)
        for index, part in enumerate(parts):
            prefix = "/".join(parts[: index + 1])
            aliases.setdefault(part, set()).add(prefix)
            aliases.setdefault(prefix, set()).add(prefix)
            numbered = re.fullmatch(r"\d+[-_．.、\s]+(.+)", part)
            if numbered:
                aliases.setdefault(numbered.group(1), set()).add(prefix)
    matched = [
        alias
        for alias in aliases
        if re.search(
            (r"(?<![a-z0-9])" if alias[0].isascii() and alias[0].isalnum() else "")
            + re.escape(alias.casefold())
            + (r"(?![a-z0-9])" if alias[-1].isascii() and alias[-1].isalnum() else ""),
            text,
        )
    ]
    # Prefer a full path over its component aliases.
    matched = [
        alias
        for alias in matched
        if not any(alias != other and alias in other for other in matched)
    ]
    explicit_modules = re.findall(
        r"模块[「“\"]([^」”\"]+)[」”\"]|([^\s，,、；;]+?)模块", instruction
    )
    for quoted, label in explicit_modules:
        name = quoted or label
        if name.endswith(("当前", "整个", "本", "某个")):
            continue
        if not any(name.casefold().endswith(alias.casefold()) for alias in aliases):
            return {
                "ids": [],
                "modules": [],
                "error": "未找到指定模块，请提供完整模块路径或在工作区选择目标。",
            }
    if matched:
        if any(len(aliases[alias]) > 1 for alias in matched):
            return {"ids": [], "modules": [], "error": "模块名称有歧义，请提供完整模块路径。"}
        modules = sorted({next(iter(aliases[alias])) for alias in matched})
        return {
            "ids": [
                str(case["id"])
                for case in cases
                if any(module_contains(module, str(case.get("module", ""))) for module in modules)
            ],
            "modules": modules,
        }
    if re.search(
        r"(?:模块[「“\"].+?[」”\"]|[\w\u4e00-\u9fff]+模块|\bmodule\s+\S+)", instruction, re.I
    ) and not re.search(
        r"当前模块|本模块|整个模块|selected module|current module", instruction, re.I
    ):
        return {
            "ids": [],
            "modules": [],
            "error": "未找到指定模块，请提供完整模块路径或在工作区选择目标。",
        }
    if re.search(r"全部|所有|整个集合|当前集合|\ball\b|\bcollection\b", instruction, re.I):
        return {"ids": [str(case["id"]) for case in cases], "modules": []}
    return None


def filter_priority(instruction: str, cases: list[dict]) -> list[dict]:
    text = re.sub(
        r"(?:改为|改成|设为|设置为|调整为|优先级为|\bto)\s*P[0-3]", "", instruction, flags=re.I
    )
    priorities = set(re.findall(r"(?<![A-Z0-9])P[0-3](?![A-Z0-9])", text.upper()))
    return [case for case in cases if not priorities or case.get("priority") in priorities]


def requested_new_module(instruction: str) -> str:
    """Extract the explicit module name in an additive request, preserving its path."""
    match = re.search(
        r"(?:新增|增加|添加|创建)(?:一个|个)?\s*[「“\"]?([^，,。；;\n」”\"]+?)模块"
        r"|\b(?:add|create)\s+(?:a\s+)?(?:new\s+)?module\s+[\"']?([\w /-]+)",
        instruction, re.I,
    )
    return (next((value for value in match.groups() if value), "").strip() if match else "")[:160]
