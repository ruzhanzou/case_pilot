"""Authoritative, versioned workspace selection. No domain copies or formal writes.

Callers own transactions. API callers must lock before editing; agent submissions
already own the conversation lock and use changed_by='agent' to retain dirty context.
"""

from copy import deepcopy
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select

from casepilot_api.auth import require_space_membership
from casepilot_api.models import (
    CaseCollection,
    CollectionCaseMembership,
    Conversation,
    ConversationOperation,
    TestCase,
    TestCaseRevision,
    WorkspaceCandidate,
)
from casepilot_api.schemas import ConversationTarget, ConversationTargetSnapshot


class SourceIdentity(BaseModel):
    ref: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)


class SelectionUpdate(BaseModel):
    base_version: int = Field(ge=0)
    action: Literal["replace", "add", "remove", "clear"] = "replace"
    sources: list[SourceIdentity] = Field(default_factory=list, max_length=100)
    targets: list[ConversationTarget] = Field(default_factory=list, max_length=100)
    active_collection_id: UUID | None = None

    @model_validator(mode="after")
    def one_input(self):
        if self.sources and self.targets:
            raise ValueError("choose_sources_or_targets")
        if self.action == "clear" and (self.sources or self.targets):
            raise ValueError("clear_has_no_targets")
        return self


def selection_state(conversation):
    state = (conversation.context or {}).get("workbench_selection")
    return deepcopy(state) if isinstance(state, dict) else None


def _error(code="workbench_selection_changed"):
    raise HTTPException(409, code)


def authorize(db, account, conversation):
    if conversation.account_id != account.id:
        raise HTTPException(404, "conversation_not_found")
    require_space_membership(db, account.id, conversation.space_id)


def collection_catalog(db, account, conversation):
    authorize(db, account, conversation)
    return [
        {"id": str(row.id), "name": row.name}
        for row in db.scalars(
            select(CaseCollection)
            .where(
                CaseCollection.space_id == conversation.space_id,
                CaseCollection.deleted_at.is_(None),
            )
            .order_by(CaseCollection.name, CaseCollection.id)
            .limit(500)
        )
    ]


def _resolve_sources(db, account, conversation, sources):
    authorize(db, account, conversation)
    return _resolve_sources_in_space(db, conversation, sources)


def _resolve_sources_in_space(db, conversation, sources):
    """Internal resolver. Caller must already authorize the containing space.

    Unlike user-facing _resolve_sources, this supports collection cleanup across
    owners without pretending the deletion requester owns another conversation.
    Candidate identities remain bound to the exact conversation, assets to space.
    """
    result = []
    for source in sources:
        source = source.model_dump() if isinstance(source, BaseModel) else source
        ref, expected = source["ref"], str(source.get("version", ""))
        if ref.startswith("asset:"):
            try:
                identifier = UUID(ref[6:])
            except ValueError:
                raise HTTPException(404, "source_not_found") from None
            row = db.execute(
                select(TestCase, TestCaseRevision)
                .join(TestCaseRevision, TestCase.current_revision_id == TestCaseRevision.id)
                .where(
                    TestCase.id == identifier,
                    TestCase.space_id == conversation.space_id,
                    TestCase.deleted_at.is_(None),
                )
                .execution_options(populate_existing=True)
            ).first()
            if row is None:
                raise HTTPException(404, "source_not_found")
            case, revision = row
            collections = list(
                db.scalars(
                    select(CaseCollection.id)
                    .join(
                        CollectionCaseMembership,
                        CollectionCaseMembership.collection_id == CaseCollection.id,
                    )
                    .where(
                        CollectionCaseMembership.test_case_id == case.id,
                        CaseCollection.space_id == conversation.space_id,
                        CaseCollection.deleted_at.is_(None),
                    )
                )
            )
            if not collections:
                raise HTTPException(404, "source_not_found")
            item = {
                "ref": ref,
                "kind": "asset",
                "version": str(revision.id),
                "case_id": str(case.id),
                "label": revision.title,
                "collection_ids": [str(value) for value in collections],
            }
        elif ref.startswith("candidate:"):
            candidate = db.scalar(
                select(WorkspaceCandidate)
                .where(
                    WorkspaceCandidate.conversation_id == conversation.id,
                    WorkspaceCandidate.ref == ref[10:],
                )
                .order_by(WorkspaceCandidate.version.desc())
                .limit(1)
                .execution_options(populate_existing=True)
            )
            if candidate is None:
                raise HTTPException(404, "source_not_found")
            if candidate.status != "candidate":
                _error("workbench_source_changed")
            item = {
                "ref": ref,
                "kind": "candidate",
                "version": str(candidate.version),
                "candidate_ref": candidate.ref,
                "label": candidate.snapshot.get("title", ""),
            }
        else:
            raise HTTPException(422, "unsupported_selection_source")
        if expected and expected != item["version"]:
            _error("workbench_source_changed")
        result.append(item)
    return result


def _target_sources(targets):
    sources = []
    for target in targets:
        if target.kind != "case" or target.module or target.condition or target.source_operation_id:
            raise HTTPException(422, "selection_requires_concrete_targets")
        sources.extend({"ref": f"asset:{value}"} for value in target.case_ids)
        sources.extend({"ref": f"candidate:{value}"} for value in target.candidate_refs)
    return sources


class _LegacyConcreteTarget(ConversationTarget):
    model_config = ConfigDict(extra="forbid")


def legacy_selection_sources(context):
    """Strict identity-only migration; malformed entries never broaden/drop scope.

    Legacy targets carry no historical revision versions. Their current versions
    are captured by the authorized resolver during the locked first CAS write.
    """
    raw_targets = (context or {}).get("selected_targets", [])
    if not isinstance(raw_targets, list):
        raise HTTPException(422, "invalid_legacy_selection")
    targets = []
    try:
        for raw in raw_targets:
            if not isinstance(raw, dict):
                raise ValueError("invalid_target")
            if "target" in raw:
                if (set(raw) - {"label", "target"}
                        or ("label" in raw and not isinstance(raw["label"], str))):
                    raise ValueError("invalid_wrapper")
                raw = raw["target"]
            targets.append(_LegacyConcreteTarget.model_validate(raw))
    except (ValueError, ValidationError) as error:
        raise HTTPException(422, "invalid_legacy_selection") from error
    sources = list({value["ref"]: value for value in _target_sources(targets)}.values())
    if len(sources) > 100:
        raise HTTPException(422, "selection_limit_exceeded")
    return sources


def _effective_selection_input(conversation):
    state = selection_state(conversation)
    if state is None:
        return None, legacy_selection_sources(conversation.context)
    if (type(state.get("version")) is not int or state["version"] < 0
            or not isinstance(state.get("items"), list) or len(state["items"]) > 100):
        _error("invalid_workbench_selection")
    expected_destination = str(conversation.collection_id) if conversation.collection_id else None
    if state.get("active_collection_id") != expected_destination:
        _error("workbench_destination_changed")
    try:
        # Missing versions must not fall back to the current revision silently.
        sources = [SourceIdentity.model_validate(item).model_dump() for item in state["items"]]
    except (ValueError, ValidationError) as error:
        raise HTTPException(409, "invalid_workbench_selection") from error
    return state, sources


def _effective_selection_result(conversation, state, items):
    for item in items:
        if "collection_ids" in item:
            item["collection_ids"] = sorted(item["collection_ids"])
    return {
        "schema_version": 1,
        "version": state["version"] if state is not None else 0,
        "active_collection_id": state.get("active_collection_id") if state is not None
            else str(conversation.collection_id) if conversation.collection_id else None,
        "items": items,
        "targets": _projection(items),
    }


def _effective_selection_in_space(db, conversation):
    """Pure internal projection; caller owns space authorization and any locks."""
    state, sources = _effective_selection_input(conversation)
    return _effective_selection_result(
        conversation, state, _resolve_sources_in_space(db, conversation, sources))


def effective_selection(db, account, conversation):
    """Authorized, non-mutating canonical-or-legacy exact selection projection."""
    authorize(db, account, conversation)
    state, sources = _effective_selection_input(conversation)
    return _effective_selection_result(
        conversation, state, _resolve_sources(db, account, conversation, sources))


def _projection(items):
    return [
        {
            "kind": "case",
            "case_ids": [i["case_id"] for i in items if i["kind"] == "asset"],
            "candidate_refs": [i["candidate_ref"] for i in items if i["kind"] == "candidate"],
        }
    ]


def _write(conversation, items, version, active, changed_by):
    state = {
        "schema_version": 1,
        "version": version,
        "active_collection_id": active,
        "items": items,
        "targets": _projection(items),
        "changed_by": changed_by,
    }
    conversation.context = {
        **(conversation.context or {}),
        "workbench_selection": state,
        "selected_targets": state["targets"],
        "selected_case_id": None,
    }
    return deepcopy(state)


def update_selection(db, account, conversation, update, changed_by="user"):
    authorize(db, account, conversation)
    # Agent holds submission lock: persist catalog/plan before populate_existing.
    if changed_by == "agent":
        db.flush()
    db.scalar(
        select(Conversation)
        .where(Conversation.id == conversation.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    previous = selection_state(conversation)
    version = previous["version"] if previous else 0
    if update.base_version != version:
        _error("workbench_selection_version_conflict")
    active = (
        previous.get("active_collection_id")
        if previous
        else (str(conversation.collection_id) if conversation.collection_id else None)
    )
    if update.active_collection_id is not None:
        active = str(update.active_collection_id)
        if active not in {row["id"] for row in collection_catalog(db, account, conversation)}:
            raise HTTPException(404, "collection_not_found")
    existing = previous["items"] if previous else []
    if previous is None and update.action in {"add", "remove"}:
        existing = effective_selection(db, account, conversation)["items"]
    incoming = update.sources or _target_sources(update.targets)
    incoming = [v.model_dump() if isinstance(v, BaseModel) else v for v in incoming]
    if update.action == "clear":
        chosen = []
    elif update.action == "replace":
        chosen = incoming
    elif update.action == "add":
        chosen = [*existing, *incoming]
    else:
        removed = {v["ref"] for v in incoming}
        # Validate supplied exact versions even on removal.
        _resolve_sources(db, account, conversation, incoming)
        chosen = [v for v in existing if v["ref"] not in removed]
    chosen = list({v["ref"]: v for v in chosen}.values())
    if len(chosen) > 100:
        raise HTTPException(422, "selection_limit_exceeded")
    items = _resolve_sources(db, account, conversation, chosen)
    if previous and items == existing and active == previous.get("active_collection_id"):
        return previous
    # Legacy proposals cannot gain authority from later selection changes.
    for operation in db.scalars(
        select(ConversationOperation).where(
            ConversationOperation.conversation_id == conversation.id
        )
    ):
        payload = dict(operation.payload or {})
        if "selection_version" not in payload:
            payload["selection_version"] = version
            payload.setdefault(
                "destination_collection_id",
                str(conversation.collection_id) if conversation.collection_id else None,
            )
            operation.payload = payload
    if active != (str(conversation.collection_id) if conversation.collection_id else None):
        conversation.collection_id = UUID(active) if active else None
    return _write(conversation, items, version + 1, active, changed_by)


def resolve_selection_payload(db, account, conversation, payload):
    state = selection_state(conversation)
    if state is None:
        return payload
    observed = getattr(payload, "selection_version", None)
    if observed is not None and observed != state["version"]:
        _error("workbench_selection_version_conflict")
    explicit = _target_sources(payload.targets)
    explicit += [{"ref": f"asset:{value}"} for value in payload.target_case_ids]
    explicit += [
        {"ref": f"candidate:{value.ref}", "version": str(value.version)}
        for value in payload.target_candidate_snapshots
    ]
    allowed = {item["ref"]: item["version"] for item in state["items"]}
    if any(
        value["ref"] not in allowed
        or (value.get("version") and value["version"] != allowed[value["ref"]])
        for value in explicit
    ):
        _error("workbench_selection_target_conflict")
    if any(
        target.collection_id and str(target.collection_id) != state["active_collection_id"]
        for target in payload.targets
    ):
        _error("workbench_selection_target_conflict")
    # Explicit subset stays a subset; absent explicit targets means current selection.
    requested = {value["ref"] for value in explicit} if explicit else set(allowed)
    items = _resolve_sources(
        db, account, conversation, [item for item in state["items"] if item["ref"] in requested]
    )
    snapshots = []
    for item in items:
        if item["kind"] == "candidate":
            candidate = db.scalar(
                select(WorkspaceCandidate).where(
                    WorkspaceCandidate.conversation_id == conversation.id,
                    WorkspaceCandidate.ref == item["candidate_ref"],
                    WorkspaceCandidate.version == int(item["version"]),
                )
            )
            snapshots.append(
                ConversationTargetSnapshot(
                    ref=candidate.ref,
                    version=candidate.version,
                    snapshot=deepcopy(candidate.snapshot),
                )
            )
    return payload.model_copy(
        update={
            "targets": [ConversationTarget.model_validate(v) for v in _projection(items)],
            "target_case_ids": [UUID(i["case_id"]) for i in items if i["kind"] == "asset"],
            "target_candidate_snapshots": snapshots,
            "target_scope": "selected",
            "source_operation_id": None,
        }
    )


def canonical_scope_payload(db, account, conversation, payload):
    """Explicit opt-in to canonical exact targets, never a legacy collection fallback."""
    authorize(db, account, conversation)
    if selection_state(conversation) is None:
        _error("workbench_selection_missing")
    _effective_selection_input(conversation)
    return resolve_selection_payload(db, account, conversation, payload)


def stamp_operation_binding(conversation, operation):
    state = selection_state(conversation)
    operation.payload = {
        **(operation.payload or {}),
        "selection_version": state["version"] if state else 0,
        "destination_collection_id": str(conversation.collection_id)
        if conversation.collection_id
        else None,
    }


def assert_selection_binding(conversation, operation):
    state = selection_state(conversation)
    payload = operation.payload or {}
    if "selection_version" in payload and payload["selection_version"] != (
        state["version"] if state else 0
    ):
        _error("workbench_selection_changed")
    if "destination_collection_id" in payload and payload["destination_collection_id"] != (
        str(conversation.collection_id) if conversation.collection_id else None
    ):
        _error("workbench_destination_changed")


def refresh_selection_after_apply(
    db, account, conversation, operation, affected_refs, removed_refs=()
):
    state = selection_state(conversation)
    if not state:
        return
    assert_selection_binding(conversation, operation)
    affected, removed = set(affected_refs), set(removed_refs)
    items = []
    for item in state["items"]:
        if item["ref"] in removed:
            continue
        if item["ref"] in affected:
            items.extend(_resolve_sources(db, account, conversation, [{"ref": item["ref"]}]))
        else:
            items.append(item)
    if items != state["items"]:
        _write(
            conversation,
            items,
            state["version"] + 1,
            state["active_collection_id"],
            "approved_apply",
        )
        stamp_operation_binding(conversation, operation)
