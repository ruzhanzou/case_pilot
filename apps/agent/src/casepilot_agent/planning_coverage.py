"""Bounded planning coverage bookkeeping, not an independent quality oracle.

The provider proposes evidence-backed obligations. These checks validate linkage,
not whether prose really proves a business rule; independent QA remains necessary.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_serializer
from pydantic_core import PydanticCustomError

from casepilot_agent.planning_boundary import BOUNDARY_VALIDATION_CODES, BoundaryContract

MAX_COVERAGE_OBLIGATIONS = 48

COVERAGE_INSTRUCTION = """
先列出本批明确规则的 coverage_obligations，再让测试点逐项覆盖；这不是用数量代替覆盖。
boundary 义务明确区分数值边界与定性/未解析边界。数值 boundary_contract 的 evidence_binding
只选本批 boundary_evidence_bindings；服务器绑定来源、threshold、unit、quantity_axis_id，
以及 sampling_step/sampling_literal。不要另填这些隐藏字段；一个选择同时绑定数量与已授权采样。
每个数量均有 sampling_step=null 的明确无采样选项；
没有授权步长时只能给 at 坐标，不能猜 before/after。
quantity_axis_id 是稳定数量来源身份，
不是测量维度、时间原点、比较关系或业务预期的正确性证明。
axis/time_origin 是拟议、待人审的显示描述，不要求逐字复制原文；不能据此宣称已完成语义核验。
仅非时间轴的 time_origin 使用 not_applicable。单位只使用服务器已识别的明确原文单位，不换算。
不支持的单位、复杂关系或缺失业务语义使用 unresolved；即便坐标完整也保留语义待人审提示。
若无合适数值绑定、定性边界或缺少必要语义，boundary_contract 使用
{"status":"unresolved","reason":"具体缺失依据"}；不输出该义务的 boundary_samples。
系统保留普通测试点，把该义务投影为 clarification 和空 point_ids（未核验，不算覆盖）。
模型输出的 boundary 义务必须显式输出 boundary_contract；无法解析时使用上述 unresolved 对象，
并保持 point_ids 为空。clarification 不替代该必填合同字段；没有采样步长不可猜测。
绑定中的 sampling_literal 必须逐字来自 context.test_setup 或服务器提供的
context.sampling_instruction_sources 中真实用户原文；后者所选 literal 自身必须含明确采样/取样指令。
仅选单一正向采样分句，不包含逗号等分隔的其它子句；数值必须是该句明确步长而非业务阈值。
不能从业务时限、派生摘要、附件或历史对话推测采样步长；否定、撤销或含混改动保持未核验。

没有该资料时 sampling_step 为 null，保留未核验缺口；只能给已知阈值 at，禁止猜测 before/after 坐标。
数值抽取不证明 comparator 或业务预期语义。
用 boundary_samples 选择 obligation_id 和 before/at/after；value 由服务器按已验证阈值与步长派生，
不要填写 value；initial_state 与 assertion 仍需明确区分并待人审；
assertion_binding 从 primary_bindings 选择真正断言功能和来源；
assertion_role=primary 必须为本点主要功能，
assertion_role=secondary 必须为另一已关联功能，不得把主功能标为 secondary。
前置条件引用不等于断言，未规定输入分区或阈值域外行为必须 clarification，不能创造预期。
这些字段是独立样本展示块，不覆盖原 scenario，不增加用户指定点数。
每项 basis 必须说明实际提供的规则依据；不能推测短信策略、角色、时限或其他未给出的业务规则。
normal 检查正常路径；boundary 对明确阈值分别考虑小于、等于、大于，只有单位和离散步长明确时
才使用相邻值；具体边界样例还必须明确时间起点、初始状态和比较规则；缺少任一必要语义时
保留 clarification，不臆造步长或起始状态。exception 保留明确例外和拒绝条件；
state 检查已说明的状态变化、重置和相关规则组合。
这些维度是检查清单，不要求给每个功能机械地生成固定数量。不同边界值或状态前提不得合并成一项。
primary_binding 必须选择本请求 primary_bindings 的一个合法枚举，显式同时选择主要功能和其依据。
系统从所选配对生成 primary_feature_id 和必需的主要来源，不要另填 primary_feature_id。
feature_point_ids 只填额外关联功能（可空），source_refs 只填额外依赖来源（可空）；
系统保留这些合法依赖并把配对主功能置首，不得选择本目录不存在的配对或其它分片来源。
配对功能必须对应此点主要可观察结果；其他条件、前置状态和引用属于次要依赖，
不能因为某规则提供前置条件就把它设为主要归属。跨规则测试的归属功能和证据依赖分别填写。
补齐时仅为原来未覆盖且无 clarification 的义务添加点；新增点的主要归属必须属于该原义务，
并由同一义务的 point_ids 引用。不能新增独立目标或把其他功能的点作为缺口补齐。
未提供的等号、单位、重置或角色语义写入 clarification，
不要自创预期。point_ids 只引用本批真实输出点；未覆盖义务保持空列表，不得宣称已覆盖。
duplicate_suggestions 只能建议复核完全相同的前提、输入和预期；标题相似不等于重复。
不要自动合并测试点，尤其不能合并不同阈值边界或状态。所有建议仍需人审。

【独立边界与跨规则自查】
逐条核对明确规则中的每个下界、上界与等号归属，不以“区间内”“边界正常”等概述替代具体观察。
有用户授权采样时分别检查边界内、边界上、边界外；只能断言规则已定义的取值域，不能为域外输入编造行为。
初次规划时，对未纳入本批义务的明确边界先列其义务再规划点；已有缺口不能靠其它正常点或重复点抵消。
补齐轮仍只处理 coverage_gaps，不新建或改写原义务；无法处理的遗漏留待人审。
时间点与经过时长分开：在 scenario/initial_state 写清观察时刻、相关事件起点及二者之差。
不要把“事件发生在某时刻”改写成“已过去该时长”。
同一场景涉及多个计时规则时分别列出各自起点，不能共用含混的 t。
隔离一条边界时，其它会导致相同拒绝或阻止成功的条件也要明确；只有输入明确允许的测试设置才能用于隔离。
可用设置不等于本点已执行设置。若需要新的资源或状态，写明何时预置及它不会改变哪些既有状态；
不能从解除限制推导资源仍有效，也不能从预置新资源推导计数已重置。
缺少依据则 clarification/unresolved，不能默补前提。
先明确本点实际观察的状态变化或结果，再选择主要功能及该结果的规则依据；使操作可执行的前置规则只作依赖。
跨规则点必须保留必要依据；合法枚举、数值绑定及引用存在只证明结构，不证明选对了主功能。
比较同批和已展示 existing_plan 中的前提、输入、预期与状态变化；完全相同的行为只建议重复复核，
不得将重述计为新的边界覆盖，也不得自动删除；不同边界坐标、状态或可观察结果仍须分开。
自查完成不改变 pending_independent_review；不能宣称独立质量通过，
也不得改变数量预算、补齐轮数或覆盖警告。

""".strip()


class CoverageObligation(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    feature_point_ids: list[str] = Field(min_length=1, max_length=24)
    dimension: Literal["normal", "boundary", "exception", "state"]
    basis: str = Field(min_length=1, max_length=2000)
    point_ids: list[str] = Field(default_factory=list, max_length=48)
    clarification: str = Field(default="", max_length=2000)


    boundary_contract: BoundaryContract | None = None

    @model_serializer(mode="wrap")
    def serialize_legacy_compatible(self, handler):
        data = handler(self)
        if self.boundary_contract is None:
            data.pop("boundary_contract", None)
        return data


class CoverageDuplicateSuggestion(BaseModel):
    point_ids: list[str] = Field(min_length=2, max_length=48)
    reason: str = Field(min_length=1, max_length=2000)


class CoverageReport(BaseModel):
    uncovered: list[CoverageObligation] = Field(default_factory=list)
    clarifications: list[CoverageObligation] = Field(default_factory=list)
    duplicate_suggestions: list[CoverageDuplicateSuggestion] = Field(default_factory=list)


def validate_coverage(obligations, points, feature_ids, duplicate_suggestions=(), *, incomplete=()):
    """Validate current-batch relationships without changing points or their IDs.

    Ambiguous obligations stay explicit and are not eligible for automatic filling.
    A nonempty clarification cannot simultaneously count as covered. Suggestions
    never change or remove points, even if the suggested points are truly identical.
    """
    obligations = [CoverageObligation.model_validate(item) for item in obligations]
    suggestions = [
        CoverageDuplicateSuggestion.model_validate(item) for item in duplicate_suggestions
    ]
    if len(obligations) > MAX_COVERAGE_OBLIGATIONS:
        raise ValueError("planning_coverage_obligation_limit")
    point_map = {point.id: point for point in points}
    if len(point_map) != len(points):
        raise ValueError("planning_coverage_point_id_duplicate")
    known_features = set(feature_ids)
    seen = set()
    uncovered, clarifications = [], []
    for item in obligations:
        if not item.id.strip() or item.id in seen:
            raise ValueError("planning_coverage_obligation_id_invalid")
        seen.add(item.id)
        if not item.basis.strip():
            raise ValueError("planning_coverage_basis_invalid")
        owners = set(item.feature_point_ids)
        if not owners or owners - known_features or len(owners) != len(item.feature_point_ids):
            raise ValueError("planning_coverage_feature_reference_invalid")
        refs = set(item.point_ids)
        if refs - point_map.keys() or len(refs) != len(item.point_ids):
            raise ValueError("planning_coverage_point_reference_invalid")
        if any(not owners.intersection(point_map[ref].feature_point_ids) for ref in refs):
            raise ValueError("planning_coverage_point_ownership_invalid")
        if item.clarification.strip():
            if refs:
                raise ValueError("planning_coverage_ambiguous_claim")
            clarifications.append(item)
        elif not refs or item.id in incomplete:
            uncovered.append(item)
    for suggestion in suggestions:
        refs = set(suggestion.point_ids)
        if (
            len(refs) < 2
            or len(refs) != len(suggestion.point_ids)
            or refs - point_map.keys()
            or not suggestion.reason.strip()
        ):
            raise ValueError("planning_duplicate_suggestion_invalid")
    return CoverageReport(
        uncovered=uncovered,
        clarifications=clarifications,
        duplicate_suggestions=suggestions,
    )


def validate_completion_ownership(original, candidate, *, incomplete=()):
    """Allow new points only for the original, unambiguous uncovered goals.

    Identity/content immutability remains the caller's snapshot check. This guard
    checks structural authority, not the semantic truth of a model's attribution.
    A legacy base point without a primary field uses its first owner; an explicit
    but empty primary field is not silently repaired.
    """
    previous = list(getattr(original, "coverage_obligations", []))
    revised = list(getattr(candidate, "coverage_obligations", []))
    previous_by_id = {item.id: item for item in previous}
    revised_by_id = {item.id: item for item in revised}
    if (len(previous_by_id) != len(previous) or len(revised_by_id) != len(revised)
            or previous_by_id.keys() != revised_by_id.keys()):
        raise ValueError("planning_coverage_completion_goal_invalid")
    eligible = {
        item.id for item in previous
        if (not item.point_ids or item.id in incomplete) and not item.clarification.strip()
    }
    existing_points = {point.id for point in original.test_points}
    for point in candidate.test_points:
        if point.id in existing_points:
            continue
        linked = {item.id for item in revised if point.id in item.point_ids}
        if not linked or linked - eligible:
            raise ValueError("planning_coverage_completion_unlinked_point")
        primary = getattr(point, "primary_feature_id", None)
        if primary is None:
            primary = next(iter(point.feature_point_ids), None)
        if any(primary not in previous_by_id[identifier].feature_point_ids
               for identifier in linked):
            raise ValueError("planning_coverage_completion_owner_invalid")


COVERAGE_VALIDATION_CODES = BOUNDARY_VALIDATION_CODES | frozenset(
    [
        "planning_coverage_obligation_limit",
        "planning_coverage_point_id_duplicate",
        "planning_coverage_obligation_id_invalid",
        "planning_coverage_basis_invalid",
        "planning_coverage_feature_reference_invalid",
        "planning_coverage_point_reference_invalid",
        "planning_coverage_point_ownership_invalid",
        "planning_coverage_ambiguous_claim",
        "planning_duplicate_suggestion_invalid",
        "planning_coverage_existing_point_changed",
        "planning_coverage_obligation_changed",
        "planning_coverage_completion_goal_invalid",
        "planning_coverage_completion_unlinked_point",
        "planning_coverage_completion_owner_invalid",
        "planning_boundary_contract_required",
        "planning_boundary_binding_conflict",
        "planning_primary_binding_conflict",
        "planning_primary_binding_unavailable",
        "planning_primary_feature_invalid",
        "planning_primary_source_missing",
        "planning_point_sources_required",
        "planning_point_scenario_required",
    ]
)


def schema_coverage_guard(check, *args, **kwargs):
    """Preserve fixed diagnostics through the SDK structured-output error chain."""
    try:
        return check(*args, **kwargs)
    except ValueError as error:
        code = str(error)
        if code not in COVERAGE_VALIDATION_CODES:
            raise
        # Only producer-attached structural metadata, never exception text/input.
        # Both diagnostic sinks independently re-allowlist this untrusted mapping.
        metadata = getattr(error, "casepilot_safe_metadata", None)
        context = {"metadata": metadata} if isinstance(metadata, dict) else None
        raise PydanticCustomError(code, "Planning coverage contract rejected", context) from error
