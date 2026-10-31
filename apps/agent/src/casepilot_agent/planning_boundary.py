"""Evidence-linked boundary coordinates; structural checks are not semantic proof."""

import hashlib
import json
import re
from copy import deepcopy
from decimal import Decimal
from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator, model_serializer


class BoundarySourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source_id: str | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    label: str
    locator: str = ""
    excerpt: str = ""


class BoundaryContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["model_proposed"] = "model_proposed"
    source_slot: str = ""
    source_ref: BoundarySourceRef | None = None
    quantity_axis_id: str | None = Field(default=None, pattern=r"^qaxis:[0-9a-f]{64}$")
    source_literal: str = Field(min_length=1)
    threshold: FiniteFloat
    unit: str = Field(min_length=1)
    comparator: Literal["lt", "lte", "gt", "gte", "eq"]
    axis: str = Field(min_length=1)
    time_origin: str = Field(min_length=1)
    sampling_step: FiniteFloat | None = Field(default=None, gt=0)
    sampling_literal: str = ""

    @model_serializer(mode="wrap")
    def canonical_serialization(self, handler):
        data = handler(self)
        if self.quantity_axis_id is None:
            data.pop("quantity_axis_id", None)
        if self.source_ref is not None:
            data.pop("source_slot", None)
        return data

    @field_validator("source_literal", "unit", "axis", "time_origin")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Boundary field must not be blank")
        return value


class UnresolvedBoundaryContract(BaseModel):
    """Request-local alternative; projected to the existing clarification field."""
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["unresolved"]
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Boundary reason must not be blank")
        return value


class BoundarySample(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    obligation_id: str = Field(min_length=1)
    position: Literal["before", "at", "after"]
    value: FiniteFloat
    initial_state: str = Field(min_length=1)
    assertion: str = Field(min_length=1)
    assertion_role: Literal["primary", "secondary"]
    assertion_feature_id: str = Field(min_length=1)
    assertion_source_slot: str = ""
    assertion_source_ref: BoundarySourceRef | None = None
    quantity_axis_id: str | None = Field(default=None, pattern=r"^qaxis:[0-9a-f]{64}$")
    unit: str = ""
    axis: str = ""
    time_origin: str = ""

    @model_serializer(mode="wrap")
    def canonical_serialization(self, handler):
        data = handler(self)
        if self.quantity_axis_id is None:
            data.pop("quantity_axis_id", None)
        if self.assertion_source_ref is not None:
            data.pop("assertion_source_slot", None)
        return data

    @field_validator("obligation_id", "initial_state", "assertion",
                     "assertion_feature_id")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Boundary field must not be blank")
        return value


BOUNDARY_VALIDATION_CODES = frozenset({
    "planning_boundary_source_invalid", "planning_boundary_literal_invalid",
    "planning_boundary_threshold_invalid", "planning_boundary_unit_invalid",
    "planning_boundary_axis_invalid", "planning_boundary_time_origin_invalid",
    "planning_boundary_sampling_invalid", "planning_boundary_sample_link_invalid",
    "planning_boundary_coordinate_invalid", "planning_boundary_assertion_owner_invalid",
    "planning_boundary_contract_required", "planning_boundary_binding_conflict",
    "planning_boundary_relation_invalid",
})


def _get(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)



def _contract(value):
    data = value.model_dump(mode="json") if isinstance(value, BaseModel) else deepcopy(value)
    if isinstance(data, dict):
        data.pop("evidence_binding", None)
    return BoundaryContract.model_validate(data)


def _sample(value):
    # The dynamic provider schema validates this pair before this pure helper.
    # It is a request-local selector, never a persisted provenance identifier.
    data = value.model_dump(mode="json") if isinstance(value, BaseModel) else deepcopy(value)
    if isinstance(data, dict):
        data.pop("assertion_binding", None)
    return BoundarySample.model_validate(data)


_NUMERIC_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_.])[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?(?![\d.])"
)


def _number_present(value, literal):
    return Decimal(str(value)) in {Decimal(m.group()) for m in _NUMERIC_TOKEN.finditer(literal)}


def _evidence_clauses(text):
    # Delimiters only, never natural-language comparator/axis inference.
    return [part.strip() for part in re.split(r"[,，;；。!?！？\n]|\.(?=\s|$)", text)
            if part.strip()]


def _quantity_tokens(clause):
    # A quantity has an explicitly adjacent lexical unit. Multiple numbers,
    # including bare range endpoints, stay unresolved: their axis relation cannot
    # be established by token adjacency alone.
    if len(list(_NUMERIC_TOKEN.finditer(clause))) != 1:
        return []
    result = []
    for match in _NUMERIC_TOKEN.finditer(clause):
        unit = re.match(r"\s*([^\W\d_]+)", clause[match.end():], re.UNICODE)
        if unit:
            result.append((match, unit.group(1)))
    return result


# Deliberately bounded units, not a natural-language unit/comparator parser.
# English must match the complete adjacent token; Chinese has no word boundary,
# so only these explicit units are recognized, longest first. No conversions.
_ASCII_UNITS = frozenset({
    "second", "seconds", "millisecond", "milliseconds", "minute", "minutes",
    "hour", "hours", "attempt", "attempts", "item", "items", "byte", "bytes",
    "character", "characters",
})
_CJK_UNITS = ("毫秒", "分钟", "小时", "字节", "字符", "秒", "次", "个")


def _recognized_unit(token):
    if token.isascii():
        return token if token.lower() in _ASCII_UNITS else None
    return next((unit for unit in _CJK_UNITS if token.startswith(unit)), None)


def quantity_axis_id(source, literal, threshold, unit):
    identity = [source.source_id, source.document_id, source.chunk_id]
    if not any(identity):
        identity = [source.locator, source.excerpt]
    payload = dict(version=1, source=identity, literal=literal,
                   threshold=str(Decimal(str(threshold)).normalize()), unit=unit)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "qaxis:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def boundary_evidence_bindings(context):
    """Server-owned quantity identities, never semantic/time-origin certificates."""
    from casepilot_agent.planning_sources import source_catalog

    result = []
    for source_index, source in enumerate(source_catalog(context)):
        for clause in _evidence_clauses(source.excerpt):
            quantities = _quantity_tokens(clause)
            if len(quantities) != 1:
                continue
            number, quantity_token = quantities[0]
            unit = _recognized_unit(quantity_token)
            if unit is None:
                continue
            threshold = float(number.group())
            if not isfinite(threshold) or Decimal(str(threshold)) != Decimal(number.group()):
                continue
            for sampling in _sampling_choices(context, unit):
                result.append(dict(
                    id=f"boundary:{len(result)}", source_slot=f"source:{source_index}",
                    source_literal=clause, threshold=threshold, unit=unit,
                    quantity_axis_id=quantity_axis_id(source, clause, threshold, unit),
                    quantity_token=quantity_token, **sampling,
                ))
    return result


def _bound_quantity_matches(contract, bindings):
    return any(all(getattr(contract, field) == binding[field] for field in (
        "source_slot", "source_literal", "threshold", "unit", "quantity_axis_id"
    )) for binding in bindings)


def _relation_present(contract):
    for clause in _evidence_clauses(contract.source_literal):
        quantities = _quantity_tokens(clause)
        if len(quantities) != 1:
            continue
        number, unit = quantities[0]
        if (Decimal(number.group()) == Decimal(str(contract.threshold))
                and (unit == contract.unit or (not contract.unit.isascii()
                                              and unit.startswith(contract.unit)))
                and contract.axis in clause
                and (contract.time_origin == "not_applicable" or contract.time_origin in clause)):
            return True
    return False


def _sampling_step_present(step, unit, literal):
    ending = r"(?![A-Za-z])" if unit.isascii() else ""
    if any(Decimal(match.group()) == Decimal(str(step))
           and re.match(r"\s*" + re.escape(unit) + ending, literal[match.end():])
           for match in _NUMERIC_TOKEN.finditer(literal)):
        return True
    # Explicit test setup integer-unit sampling means one unit, never a rule
    # threshold inference. Unit text must itself be present without conversion.
    if Decimal(str(step)) != Decimal(1):
        return False
    ending = r"(?![A-Za-z])" if unit.isascii() else ""
    return bool(re.search(
        r"(?:整数\s*|\binteger\s+)" + re.escape(unit) + ending,
        literal, re.IGNORECASE,
    ))


# Bounded sampling clauses, not a general natural-language rule interpreter.
_SAMPLING_MARKER = re.compile(r"采样|取样|\bsampl(?:e|es|ed|ing)\b", re.IGNORECASE)
_SAMPLING_REVOCATION = re.compile(
    r"不要|不用|不再|不按|不采用|取消|撤销|停止|禁止|"
    r"\b(?:do\s+not|don't|never|not|no\s+longer|cancel|revoke)\b", re.IGNORECASE,
)
_SAMPLING_CHANGE = re.compile(r"改(?:为|用)?|\b(?:change\s+to|instead)\b", re.IGNORECASE)
_NUMBER = r"[+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"


def _sampling_clauses(prompt, unit=None):
    # Keep decimal dots; inspect whole original clauses so trimming a negative
    # prefix cannot create permission. Numeric shorthand revocation in the same
    # unit also invalidates an earlier setting, but unrelated negatives do not.
    clauses = [text.strip() for text in re.split(r"[，,；;。!?！？\n]|\.(?=\s|$)", prompt)]
    changes = [index for index, text in enumerate(clauses)
               if (_SAMPLING_MARKER.search(text)
                   and (_SAMPLING_CHANGE.search(text) or _SAMPLING_REVOCATION.search(text)))
               or (unit and unit in text and re.search(_NUMBER, text)
                   and (_SAMPLING_CHANGE.search(text) or _SAMPLING_REVOCATION.search(text)))]
    if changes:
        clauses = clauses[changes[-1]:]
    return [text for text in clauses
            if _SAMPLING_MARKER.search(text) and not _SAMPLING_REVOCATION.search(text)]


def sampling_instruction_sources(prompt):
    """Only this guarded job's original user instruction, never history/data.

    Same-run continuation restores its authorized request before creating the job.
    New runs get their own prompt; no other run/collection/history is looked up.
    """
    if not isinstance(prompt, str) or not prompt.strip() or not _sampling_clauses(prompt):
        return []
    return [{"origin": "user_input", "text": prompt}]


def _user_sampling_steps(literal, unit):
    """Recognize explicit step syntax only, not any number near a sampling word."""
    escaped = re.escape(unit)
    ending = r"(?![A-Za-z])" if unit.isascii() else ""
    chinese = (r"(?:每|按|间隔|步长(?:为)?)\s*(" + _NUMBER + r")\s*"
               + escaped + r"\s*(?:进行)?(?:采样|取样)")
    english = (r"\bsampl(?:e|es|ed|ing)\s+(?:every|at)\s*(" + _NUMBER
               + r")\s*" + escaped + ending)
    values = {Decimal(value) for pattern in (chinese, english)
              for value in re.findall(pattern, literal, re.IGNORECASE)}
    integer = (r"按\s*整数\s*" + escaped + r"\s*(?:采样|取样)|"
               r"\bsampl(?:e|es|ed|ing)\s+(?:every|at)\s+integer\s+"
               + escaped + ending)
    if re.search(integer, literal, re.IGNORECASE):
        values.add(Decimal(1))
    return values


def _sampling_literal_authorized(literal, context, setup, step, unit):
    # Existing explicitly supplied test_setup remains supported unchanged.
    if any(literal in text for text in setup):
        return True
    if not _SAMPLING_MARKER.search(literal) or _SAMPLING_REVOCATION.search(literal):
        return False
    original = context.get("user_input")
    expected = sampling_instruction_sources(original)
    entries = context.get("sampling_instruction_sources", [])
    if not isinstance(entries, list) or not any(entry in expected for entry in entries):
        return False
    clauses = _sampling_clauses(original, unit)
    if not any(literal in clause for clause in clauses):
        return False
    declared = set().union(*(_user_sampling_steps(clause, unit) for clause in clauses))
    if len(declared) != 1:
        return False
    values = _user_sampling_steps(literal, unit)
    return bool(values) and (step is None or Decimal(str(step)) in values)


def _sampling_choices(context, unit):
    """Enumerate only existing explicit sampling authority; no new NL grammar."""
    setup = context.get("test_setup", [])
    setup = [setup] if isinstance(setup, str) else setup
    setup = [text for text in setup if isinstance(text, str)] if isinstance(setup, list) else []
    candidates = list(setup)
    original = context.get("user_input")
    if isinstance(original, str):
        candidates.extend(_sampling_clauses(original, unit))
    choices = []
    seen = set()
    for literal in candidates:
        if _SAMPLING_REVOCATION.search(literal):
            continue
        steps = {Decimal(match.group()) for match in _NUMERIC_TOKEN.finditer(literal)}
        steps.add(Decimal(1))
        steps = {step for step in steps if step > 0 and isfinite(float(step))
                 and Decimal(str(float(step))) == step
                 and _sampling_step_present(step, unit, literal)
                 and _sampling_literal_authorized(literal, context, setup, step, unit)}
        if len(steps) != 1:
            continue
        step = float(next(iter(steps)))
        if (literal, step) not in seen:
            choices.append(dict(sampling_literal=literal, sampling_step=step))
            seen.add((literal, step))
    return [*choices, dict(sampling_literal="", sampling_step=None)]


def _expected_sample_value(contract, position):
    threshold = Decimal(str(contract.threshold))
    if position == "at":
        return threshold
    if (position in {"before", "after"} and contract.sampling_step is not None
            and contract.sampling_literal.strip()):
        return threshold + Decimal(str(contract.sampling_step)) * (
            -1 if position == "before" else 1
        )
    raise ValueError("planning_boundary_coordinate_invalid")


def validate_boundary_contracts(obligations, points, context, feature_source_slots, *,
                                derive_missing_values=False):
    """Return unresolved IDs; reject fabricated provenance or coordinates.

    A step needs exact explicit setup or a positive sampling instruction in this
    guarded job's original user text, never a business threshold or model claim.
    By default no fields or scenarios change (including legacy inputs). The new
    request-local schema may explicitly opt into missing-value derivation after
    authority/link validation. Supplied coordinates are never overwritten.
    """
    from casepilot_agent.planning_sources import payload_catalog

    catalog = {item["slot"]: item["excerpt"] for item in payload_catalog(context)}
    bindings = boundary_evidence_bindings(context)
    obligation_map = {_get(item, "id"): item for item in obligations}
    incomplete, contracts, positions = set(), {}, {}
    derived_values = []
    setup = context.get("test_setup", [])
    setup = [setup] if isinstance(setup, str) else setup
    setup = [text for text in setup if isinstance(text, str)] if isinstance(setup, list) else []
    for obligation_index, (identifier, item) in enumerate(obligation_map.items()):
        value = _get(item, "boundary_contract")
        if value is None:
            continue
        def invalid(code, item=item, obligation_index=obligation_index):
            error = ValueError(code)
            error.casepilot_safe_metadata = {
                "obligation_index": obligation_index,
                "dimension": _get(item, "dimension"),
                "contract_present": True,
                "clarification_present": bool(_get(item, "clarification", "").strip()),
                "point_count": len(_get(item, "point_ids", [])),
            }
            return error

        contract = _contract(value)
        contracts[identifier] = contract
        positions[identifier] = set()
        allowed = {slot for feature in _get(item, "feature_point_ids", [])
                   for slot in feature_source_slots.get(feature, [])}
        if contract.source_slot not in catalog or contract.source_slot not in allowed:
            raise invalid("planning_boundary_source_invalid")
        if contract.source_literal not in catalog[contract.source_slot]:
            raise invalid("planning_boundary_literal_invalid")
        if not _number_present(contract.threshold, contract.source_literal):
            raise invalid("planning_boundary_threshold_invalid")
        if contract.unit not in contract.source_literal:
            raise invalid("planning_boundary_unit_invalid")
        if contract.quantity_axis_id is not None:
            if not _bound_quantity_matches(contract, bindings):
                raise invalid("planning_boundary_binding_conflict")
        else:
            # Historical contracts retain their exact old validation behavior.
            if contract.axis not in contract.source_literal:
                raise invalid("planning_boundary_axis_invalid")
            if (contract.time_origin != "not_applicable"
                    and contract.time_origin not in contract.source_literal):
                raise invalid("planning_boundary_time_origin_invalid")
            if not _relation_present(contract):
                raise invalid("planning_boundary_relation_invalid")
        if contract.sampling_literal.strip() and (
            not _sampling_literal_authorized(
                contract.sampling_literal, context, setup, contract.sampling_step, contract.unit
            )
            or contract.unit not in contract.sampling_literal
            or (contract.sampling_step is not None and not _sampling_step_present(
                contract.sampling_step, contract.unit, contract.sampling_literal
            ))
        ):
            raise invalid("planning_boundary_sampling_invalid")
        if contract.sampling_step is None or not contract.sampling_literal.strip():
            incomplete.add(identifier)
    for point in points:
        for value in (_get(point, "boundary_samples", []) or []):
            candidate = value
            if derive_missing_values and _get(value, "value") is None:
                identifier = _get(value, "obligation_id")
                item = obligation_map.get(identifier)
                if (item is None or identifier not in contracts
                        or _get(point, "id") not in _get(item, "point_ids", [])):
                    raise ValueError("planning_boundary_sample_link_invalid")
                expected = _expected_sample_value(contracts[identifier], _get(value, "position"))
                derived = float(expected)
                if not isfinite(derived) or Decimal(str(derived)) != expected:
                    raise ValueError("planning_boundary_coordinate_invalid")
                candidate = (value.model_copy(update={"value": derived})
                             if isinstance(value, BaseModel) else {**value, "value": derived})
                derived_values.append((value, derived))
            sample = _sample(candidate)
            item = obligation_map.get(sample.obligation_id)
            if (item is None or sample.obligation_id not in contracts
                    or _get(point, "id") not in _get(item, "point_ids", [])):
                raise ValueError("planning_boundary_sample_link_invalid")
            feature = sample.assertion_feature_id
            primary = _get(point, "primary_feature_id")
            if (feature not in _get(point, "feature_point_ids", [])
                    or sample.assertion_source_slot not in catalog
                    or sample.assertion_source_slot not in feature_source_slots.get(feature, [])
                    or (sample.assertion_role == "primary" and feature != primary)
                    or (sample.assertion_role == "secondary" and feature == primary)):
                raise ValueError("planning_boundary_assertion_owner_invalid")
            contract = contracts[sample.obligation_id]
            if (sample.quantity_axis_id is not None
                    and sample.quantity_axis_id != contract.quantity_axis_id):
                raise ValueError("planning_boundary_binding_conflict")
            coordinate = Decimal(str(sample.value))
            expected = _expected_sample_value(contract, sample.position)
            if coordinate != expected:
                raise ValueError("planning_boundary_coordinate_invalid")
            positions[sample.obligation_id].add(sample.position)
    for identifier, covered in positions.items():
        if covered != {"before", "at", "after"}:
            incomplete.add(identifier)
    # Publish derived coordinates only after every supplied contract/sample passed.
    for value, derived in derived_values:
        if isinstance(value, dict):
            value["value"] = derived
        else:
            value.value = derived
    return incomplete


def point_boundary_markdown(point):
    """Display explicit proposed coordinates, without rewriting scenario prose."""
    samples = [_sample(value)
               for value in (_get(point, "boundary_samples", []) or [])]
    if not samples:
        return ""
    lines = ["### Proposed boundary samples"]
    for sample in samples:
        lines.append(
            f"- {sample.obligation_id}: {sample.position} = {sample.value} {sample.unit}; "
            f"axis: {sample.axis}; origin: {sample.time_origin}; "
            f"initial state: {sample.initial_state}; "
            f"{sample.assertion_role} assertion ({sample.assertion_feature_id}): {sample.assertion}"
        )
    return "\n".join(lines)


def project_boundary_metadata(plan, context):
    """Copy a validated plan and hydrate temporary slots into canonical references.

    Canonical fields supplied by the model are never trusted: even if present,
    they are overwritten from a known current slot or the projection rejects.
    """
    from casepilot_agent.planning_sources import source_catalog

    catalog = {f"source:{index}": BoundarySourceRef.model_validate(ref.model_dump())
               for index, ref in enumerate(source_catalog(context))}
    copied = deepcopy(plan)
    bindings = boundary_evidence_bindings(context)
    contracts = {}
    for obligation in _get(copied, "coverage_obligations", []):
        value = _get(obligation, "boundary_contract")
        if value is None:
            continue
        contract = _contract(value)
        if contract.source_slot not in catalog:
            raise ValueError("planning_boundary_source_invalid")
        if (contract.quantity_axis_id is not None
                and not _bound_quantity_matches(contract, bindings)):
            raise ValueError("planning_boundary_binding_conflict")
        contract = contract.model_copy(update={"source_ref": catalog[contract.source_slot]})
        contracts[_get(obligation, "id")] = contract
        if isinstance(obligation, dict):
            obligation["boundary_contract"] = contract.model_dump(mode="json")
        else:
            obligation.boundary_contract = contract
    for point in _get(copied, "test_points", []):
        if _get(point, "boundary_samples") is None:
            continue
        projected = []
        for value in (_get(point, "boundary_samples", []) or []):
            sample = _sample(value)
            contract = contracts.get(sample.obligation_id)
            if contract is None or sample.assertion_source_slot not in catalog:
                raise ValueError("planning_boundary_source_invalid")
            if (sample.quantity_axis_id is not None
                    and sample.quantity_axis_id != contract.quantity_axis_id):
                raise ValueError("planning_boundary_binding_conflict")
            sample = sample.model_copy(update={
                "quantity_axis_id": contract.quantity_axis_id,
                "assertion_source_ref": catalog[sample.assertion_source_slot],
                "unit": contract.unit, "axis": contract.axis, "time_origin": contract.time_origin,
            })
            projected.append(sample)
        if isinstance(point, dict):
            point["boundary_samples"] = [sample.model_dump(mode="json") for sample in projected]
        else:
            point.boundary_samples = projected
    return copied


def validate_persisted_quantity_links(plan):
    """Fail closed before a completed brief can publish an orphan quantity graph.

    This checks persisted point/obligation identity, not source authorization or
    semantic coverage. Historical no-ID plans are neither rewritten nor upgraded.
    """
    linked = {}
    for batch in (plan.get("coverage_review") or {}).get("batches", []):
        for obligation in batch.get("obligations", []):
            value = obligation.get("boundary_contract")
            if not value:
                continue
            contract = _contract(value)
            for point_id in obligation.get("point_ids", []):
                linked.setdefault((point_id, obligation.get("id")), []).append(contract)
    for point in plan.get("test_points", []):
        for value in point.get("boundary_samples") or []:
            sample = _sample(value)
            contracts = linked.get((point["id"], sample.obligation_id), [])
            if sample.quantity_axis_id is None and not any(c.quantity_axis_id for c in contracts):
                continue
            matching = [c for c in contracts if c.quantity_axis_id == sample.quantity_axis_id]
            if not matching:
                raise ValueError("planning_boundary_binding_conflict")
            if not any(sample.unit == c.unit and Decimal(str(sample.value)) ==
                       _expected_sample_value(c, sample.position) for c in matching):
                raise ValueError("planning_boundary_coordinate_invalid")
