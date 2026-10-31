"""Batch-scoped, server-owned provenance for newly generated planning features.

The model chooses a locator slot; it never authors the persisted evidence text or
identity. Existing exact catalog tuples remain readable for cached/preloaded plans.
This module does not rewrite historical confirmed plans or reuse output snapshots.
"""

import json
from copy import deepcopy
from typing import Literal

from pydantic import Field, create_model

from casepilot_agent.contracts import FeaturePoint, SourceRef, TestPointPlan


def _identity(ref):
    return (ref.source_id, ref.document_id, ref.chunk_id)


def source_catalog(context):
    """Return a fresh catalog containing only this batch's authorized inputs."""
    user_input = str(context.get("user_input") or context.get("query") or "")
    catalog = ([SourceRef(label="用户输入", locator="user_input", excerpt=user_input)]
               if user_input.strip() else [])
    catalog.extend(SourceRef.model_validate(item) for item in context.get("evidence", []))
    for source in context.get("planning_authorized_sources", []):
        # Planning uses reference evidence, not an output reuse receipt. Formal reuse
        # retains its original source snapshot and provenance in the output path.
        catalog.append(SourceRef(
            label=str(source.get("label") or "已确认历史来源"),
            locator=str(source.get("canonical_ref") or source["key"]),
            excerpt=json.dumps({
                "source_key": source["key"], "action": "reference",
                "revision": source.get("revision"),
                "document_version": source.get("document_version"),
                "document_checksum": source.get("document_checksum"),
                "snapshot": source["snapshot"],
            }, ensure_ascii=False, sort_keys=True),
        ))
    return catalog


def payload_catalog(context):
    """Model-facing slots deliberately omit physical source/document/chunk IDs."""
    return [{"slot": f"source:{index}", "label": ref.label,
             "locator": ref.locator, "excerpt": ref.excerpt}
            for index, ref in enumerate(source_catalog(context))]


def _source_selection_type(context):
    """Only slots actually shown in this request are valid model identities."""
    slots = tuple(f"source:{index}" for index in range(len(source_catalog(context))))
    if not slots:
        raise ValueError("planning_source_reference_invalid")
    return create_model(
        "PlanningSourceSelection", __base__=SourceRef,
        source_id=(type(None), None), document_id=(type(None), None),
        chunk_id=(type(None), None), locator=(Literal[slots], ...),
    )


def point_source_selection_type(base_type, context):
    """Point ownership and evidence dependencies are independently selected."""
    return create_model(
        f"SourceScoped{base_type.__name__}", __base__=base_type,
        source_refs=(list[_source_selection_type(context)], Field(default_factory=list)),
    )


def source_selection_schema(base_type, context):
    """Constrain only the new planning feature refs, without altering global schemas."""
    selection_type = _source_selection_type(context)
    feature_type = create_model(
        "SourceScopedFeaturePoint", __base__=FeaturePoint,
        source_refs=(list[selection_type], Field(default_factory=list)),
    )
    result_type = create_model(
        f"SourceScoped{base_type.__name__}", __base__=base_type,
        feature_points=(list[feature_type], Field(default_factory=list)),
    )
    # Projection returns the original model contract; revalidating hydrated IDs
    # against the null-only model selection schema would be incorrect.
    result_type.__planning_source_base__ = base_type
    return result_type


def _project_sources(plan, context, item_field, base_type):
    """Validate identity against this batch and hydrate all fields from the server."""
    catalog = source_catalog(context)
    slots = {f"source:{index}": ref for index, ref in enumerate(catalog)}
    identities = {}
    for ref in catalog:
        identity = _identity(ref)
        if any(identity):
            identities.setdefault(identity, []).append(ref)
    data = deepcopy(plan.model_dump(mode="json"))
    for feature in data.get(item_field, []):
        refs = feature.get("source_refs", [])
        if not refs:
            # Compatible explicit empty selection: use this batch's evidence, not
            # a different batch, or the original user input when no evidence exists.
            selected = [SourceRef.model_validate(value) for value in context.get("evidence", [])]
            if not selected:
                selected = [ref for ref in catalog if ref.locator == "user_input"]
            if not selected:
                raise ValueError("planning_source_reference_invalid")
        else:
            selected = []
            for value in refs:
                ref = SourceRef.model_validate(value)
                exact = [item for item in catalog if item == ref]
                if exact:
                    # A real document locator may itself start with the slot prefix.
                    selected.extend(exact)
                elif ref.locator.startswith("source:"):
                    if ref.locator not in slots or any(_identity(ref)):
                        raise ValueError("planning_source_reference_invalid")
                    selected.append(slots[ref.locator])
                elif any(_identity(ref)):
                    matches = identities.get(_identity(ref), [])
                    if not matches:
                        raise ValueError("planning_source_reference_invalid")
                    # A split evidence chunk can have several authorized excerpts
                    # within one batch. Hydrate all of those, never model text.
                    selected.extend(matches)
                else:
                    matches = [item for item in catalog if item == ref]
                    if matches:
                        selected.extend(matches)
                    elif not ref.locator:
                        # The legacy blank locator is an explicit user-input alias.
                        # Its model-authored label/excerpt are never retained.
                        user_ref = next((item for item in catalog if item.locator == "user_input"), None)
                        if user_ref is None:
                            raise ValueError("planning_source_reference_invalid")
                        selected.append(user_ref)
                    else:
                        raise ValueError("planning_source_reference_invalid")
        feature["source_refs"] = [json.loads(value) for value in dict.fromkeys(
            ref.model_dump_json() for ref in selected
        )]
    if item_field == "test_points":
        for point in data.get("test_points", []):
            for sample in point.get("boundary_samples") or []:
                # The dynamic schema already validated this explicit pair; the
                # persisted base contract retains its derived owner/slot only.
                sample.pop("assertion_binding", None)
    return base_type.model_validate(data)


def project_feature_sources(plan, context):
    """Hydrate feature sources without changing an existing planning contract."""
    base_type = getattr(type(plan), "__planning_source_base__", type(plan))
    return _project_sources(plan, context, "feature_points", base_type)


def project_point_sources(plan, context, *, canonical_context=None):
    """Hydrate only selected point evidence; feature IDs never determine citations.

    The caller must supply the exact context whose source catalog was displayed to
    the point model. A missing selection retains the legacy current-batch fallback,
    not the owning feature's sources nor evidence hidden in other batches.
    """
    projected = _project_sources(plan, context, "test_points", TestPointPlan)
    for original, point in zip(plan.test_points, projected.test_points, strict=True):
        primary = getattr(original, "primary_feature_id", None)
        if primary is not None:
            if primary not in point.feature_point_ids:
                raise ValueError("planning_primary_feature_invalid")
            point.feature_point_ids = [primary] + [
                identity for identity in point.feature_point_ids if identity != primary
            ]
    if canonical_context is None:
        return projected
    # Selection authority comes exclusively from the displayed context above.
    # The original SAME-batch context validates displayed snippets only. It must
    # never expand a citation with text the model did not see or select.
    canonical = source_catalog(canonical_context)
    for point in projected.test_points:
        for ref in point.source_refs:
            if any(_identity(ref)):
                matches = [item for item in canonical
                           if _identity(item) == _identity(ref)
                           and item.label == ref.label and item.locator == ref.locator
                           and ref.excerpt in item.excerpt]
            else:
                # User/history snapshots are not compacted evidence chunks. Their
                # entire value must still match; a locator alone is not authority.
                matches = [item for item in canonical if item == ref]
            if not matches:
                raise ValueError("planning_source_reference_invalid")
    return projected



def validate_primary_sources(plan, features, context):
    """Validate coarse primary ownership provenance, not semantic correctness.

    Newly generated schemas require primary_feature_id. Legacy base plans lack
    that field and retain their first owner convention only when explicitly
    validated here. No historical plan is modified or implicitly reclassified.
    Shared source identity proves availability, never that a scenario is entailed.
    """
    by_id = {feature.id: feature for feature in features}
    for point in plan.test_points:
        owners = point.feature_point_ids
        primary = getattr(point, "primary_feature_id", None)
        if primary is None:
            primary = owners[0] if owners else None
        if primary not in owners or primary not in by_id:
            raise ValueError("planning_primary_feature_invalid")
        if not point.source_refs:
            raise ValueError("planning_point_sources_required")
    # Validate all selected refs before examining attribution: a foreign source
    # cannot be hidden behind one legitimate dependency.
    projected = project_point_sources(plan, context)
    for original, point in zip(plan.test_points, projected.test_points, strict=True):
        primary = (getattr(original, "primary_feature_id", None) or original.feature_point_ids[0])
        feature_refs = by_id[primary].source_refs
        if not any(_same_provenance(selected, origin)
                   for selected in point.source_refs for origin in feature_refs):
            raise ValueError("planning_primary_source_missing")



def _same_provenance(left, right):
    if any(_identity(left)) or any(_identity(right)):
        return _identity(left) == _identity(right)
    return left.locator == right.locator and left.excerpt == right.excerpt


def feature_source_slots(features, context):
    """Expose only displayed catalog slots with the feature's actual provenance."""
    catalog = source_catalog(context)
    return {feature.id: [f"source:{index}" for index, selected in enumerate(catalog)
                         if any(_same_provenance(selected, origin)
                                for origin in feature.source_refs)]
            for feature in features}


def primary_bindings(features, context):
    """Enumerate only server-proven feature/source pairs shown in this request."""
    pairs = [(feature_id, slot) for feature_id, slots in feature_source_slots(
        features, context).items() for slot in slots]
    return [{"id": f"primary:{index}", "feature_id": feature_id, "source_slot": slot}
            for index, (feature_id, slot) in enumerate(pairs)]


def bind_primary_selection(value, bindings):
    """Expand an explicit known pair selection before normal schema validation.

    This does not recover failed model output: unknown pairs and malformed lists
    remain invalid, and every secondary citation survives for strict validation.
    """
    if not isinstance(value, dict):
        return value
    data = deepcopy(value)
    binding = next((item for item in bindings if item["id"] == data.get("primary_binding")), None)
    if binding is None:
        return data
    owner = binding["feature_id"]
    if data.get("primary_feature_id") not in (None, owner):
        raise ValueError("planning_primary_binding_conflict")
    data["primary_feature_id"] = owner
    owners = data.get("feature_point_ids", [])
    if isinstance(owners, list):
        data["feature_point_ids"] = [owner] + [item for item in owners if item != owner]
    refs = data.get("source_refs", [])
    if isinstance(refs, list):
        slot = binding["source_slot"]
        # A malformed matching slot with physical IDs is deliberately retained;
        # the existing strict selection schema must reject it, not sanitize it.
        if not any(isinstance(ref, dict) and ref.get("locator") == slot for ref in refs):
            refs.append(SourceRef(label="Primary source selection", locator=slot).model_dump())
        data["source_refs"] = refs
    return data
