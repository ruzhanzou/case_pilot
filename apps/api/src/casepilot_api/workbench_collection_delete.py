"""Exact, user-approved collection soft deletion; never delete case assets."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from casepilot_api.models import (
    CaseCollection,
    CollectionCaseMembership,
    Conversation,
    ConversationOperation,
    GenerationJob,
    Space,
    TestCase,
    WorkspaceCandidate,
)
from casepilot_api.workbench_collection_revision import collection_revision

IMPACT_KEY = "_workbench_collection_delete_impact"


def lock_nowait(db, row):
    try:
        db.refresh(row, with_for_update={"nowait": True})
    except OperationalError as error:
        if getattr(error.orig, "sqlstate", None) == "55P03":
            raise HTTPException(409, "collection_impact_busy") from error
        raise


def _selection_references_collection(conversation, target, member_refs):
    """Structural impact probe only, not a selection or scope expansion.

    Known unrelated collection-local module/condition targets need no migration.
    Unknown cross-collection legacy scope blocks approval rather than being lost.
    """
    from casepilot_api.schemas import ConversationTarget
    from casepilot_api.workbench_selection import legacy_selection_sources

    context = conversation.context or {}
    canonical = context.get("workbench_selection")
    if canonical is not None:
        if not isinstance(canonical, dict) or not isinstance(canonical.get("items"), list):
            raise HTTPException(409, "collection_impact_unresolved")
        for item in canonical["items"]:
            if not isinstance(item, dict) or not isinstance(item.get("ref"), str):
                raise HTTPException(409, "collection_impact_unresolved")
            memberships = item.get("collection_ids", [])
            if not isinstance(memberships, list):
                raise HTTPException(409, "collection_impact_unresolved")
            if item["ref"] in member_refs or target in memberships:
                return True
        return False
    entries = context.get("selected_targets", [])
    if not isinstance(entries, list):
        raise HTTPException(409, "collection_impact_unresolved")
    for entry in entries:
        if not isinstance(entry, dict):
            raise HTTPException(409, "collection_impact_unresolved")
        if "target" in entry and set(entry) - {"target", "label"}:
            raise HTTPException(409, "collection_impact_unresolved")
        value = entry.get("target") if "target" in entry else entry
        if (not isinstance(value, dict)
                or set(value) - set(ConversationTarget.model_fields)):
            raise HTTPException(409, "collection_impact_unresolved")
        if value.get("kind") in {"module", "condition"}:
            destination = value.get("collection_id") or conversation.collection_id
            try:
                destination = str(UUID(str(destination)))
            except ValueError as error:
                raise HTTPException(409, "collection_impact_unresolved") from error
            if destination == target:
                return True  # Strict effective decoder will reject implicit expansion.
            continue
        try:
            sources = legacy_selection_sources({"selected_targets": [entry]})
        except HTTPException as error:
            raise HTTPException(409, "collection_impact_unresolved") from error
        if any(source["ref"] in member_refs for source in sources):
            return True
    return False


def _impact(db, collection, requester):
    from casepilot_api.workbench_selection import _effective_selection_in_space

    # Private space-scoped cleanup analysis: never expose these projections or
    # impersonate requester as the owner of other affected conversations.
    if collection.space_id != requester.space_id:
        raise HTTPException(404, "collection_not_found")
    memberships = list(
        db.scalars(
            select(CollectionCaseMembership)
            .where(
                CollectionCaseMembership.collection_id == collection.id,
            )
            .order_by(CollectionCaseMembership.id)
        )
    )
    member_ids = {row.test_case_id for row in memberships}
    conversations = list(
        db.scalars(
            select(Conversation)
            .where(
                Conversation.space_id == collection.space_id,
            )
            .order_by(Conversation.id)
        )
    )
    # Discover exact references before resolving revisions. Unrelated workspaces'
    # assets must not expand the delete impact/lock set or its revision digest.
    affected = []
    target = str(collection.id)
    member_refs = {f"asset:{value}" for value in member_ids}
    for conversation in conversations:
        state = (conversation.context or {}).get("workbench_selection") or {}
        proposal = (conversation.context or {}).get("workbench_collection_proposal") or {}
        referenced = _selection_references_collection(conversation, target, member_refs)
        if (conversation.id == requester.id or conversation.collection_id == collection.id
                or state.get("active_collection_id") == target or referenced
                or (proposal.get("status") == "pending" and target in {
                    proposal.get("collection_id"), proposal.get("destination_collection_id")})):
            affected.append(conversation)
    try:
        effective = {row.id: _effective_selection_in_space(db, row) for row in affected}
    except HTTPException as error:
        if error.status_code != 422:
            raise
        raise HTTPException(409, "collection_impact_unresolved") from error
    # Include cached source references even if membership moved before proposal.
    # Cleanup must derive remaining accessibility from current memberships, not
    # mistake an old collection_ids projection for the authoritative catalog.
    tracked_ids = set(member_ids)
    for conversation in affected:
        tracked_ids.update(UUID(item["case_id"]) for item in effective[conversation.id]["items"]
                           if item["kind"] == "asset")
    all_memberships = (
        list(
            db.scalars(
                select(CollectionCaseMembership)
                .where(
                    CollectionCaseMembership.test_case_id.in_(tracked_ids),
                )
                .order_by(CollectionCaseMembership.id)
            )
        )
        if tracked_ids
        else []
    )
    relevant_collections = list(
        db.scalars(
            select(CaseCollection)
            .where(
                CaseCollection.id.in_(
                    {row.collection_id for row in all_memberships} | {collection.id}
                ),
            )
            .order_by(CaseCollection.id)
        )
    )
    cases = list(
        db.scalars(select(TestCase).where(TestCase.id.in_(tracked_ids)).order_by(TestCase.id))
    )
    payload = {
        "memberships": [
            (str(row.id), str(row.collection_id), str(row.test_case_id)) for row in all_memberships
        ],
        "collections": [
            (str(row.id), collection_revision(db, row.id), str(row.deleted_at))
            for row in relevant_collections
        ],
        "cases": [
            (str(row.id), str(row.current_revision_id), str(row.deleted_at)) for row in cases
        ],
        "conversations": [
            {
                "id": str(row.id),
                "destination": str(row.collection_id),
                "selection": effective[row.id],
                "phase": (row.context or {}).get("phase"),
                "job": (row.context or {}).get("active_job_id"),
                "proposal": None
                if row.id == requester.id
                else (row.context or {}).get("workbench_collection_proposal"),
            }
            for row in affected
        ],
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    return digest, affected, all_memberships, relevant_collections, cases, effective


def prepare_impact(db, collection, requester, proposal_id):
    digest, affected, memberships, _, _, _ = _impact(db, collection, requester)
    requester.context = {
        **dict(requester.context),
        IMPACT_KEY: {"proposal_id": proposal_id, "digest": digest},
    }
    return {
        "member_case_count": len(
            {row.test_case_id for row in memberships if row.collection_id == collection.id}
        ),
        "affected_conversation_count": len(affected),
    }


def apply_soft_delete(db, transaction, account, requester, proposal):
    from casepilot_api.case_management import delete_collection, ensure_collection
    from casepilot_api.conversations import _require_idle_conversation
    from casepilot_api.workbench_selection import _write

    # JSON selection references have no FK to the collection. Lock the space
    # against new conversation inserts, then all existing same-space workspaces
    # so source-only selection cannot become a new impact after the scan.
    lock_nowait(db, db.get(Space, requester.space_id))
    collection = ensure_collection(db, account, UUID(proposal["collection_id"]))
    lock_nowait(db, collection)
    for conversation in db.scalars(
        select(Conversation)
        .where(
            Conversation.space_id == collection.space_id,
        )
        .order_by(Conversation.id)
    ):
        lock_nowait(db, conversation)
    if (
        collection.name != proposal["base_name"]
        or collection_revision(db, collection.id) != proposal["base_updated_at"]
    ):
        raise HTTPException(409, "collection_proposal_stale")
    digest, affected, memberships, related_collections, cases, observed = _impact(
        db, collection, requester)
    # NOWAIT on every additional lock: no cross-workspace lock waits or cycles.
    for row in [*affected, *related_collections, *cases, *memberships]:
        lock_nowait(db, row)
    for conversation in affected:
        for item in observed[conversation.id]["items"]:
            if item["kind"] == "candidate":
                candidate = db.scalar(select(WorkspaceCandidate).where(
                    WorkspaceCandidate.conversation_id == conversation.id,
                    WorkspaceCandidate.ref == item["candidate_ref"],
                    WorkspaceCandidate.version == int(item["version"]),
                ))
                if candidate is None:
                    raise HTTPException(409, "collection_impact_changed")
                lock_nowait(db, candidate)
    digest, affected_after, _, _, _, effective = _impact(db, collection, requester)
    frozen = dict(requester.context).get(IMPACT_KEY) or {}
    if (
        frozen.get("proposal_id") != proposal["id"]
        or frozen.get("digest") != digest
        or {row.id for row in affected_after} != {row.id for row in affected}
    ):
        raise HTTPException(409, "collection_impact_changed")
    for conversation in affected:
        _require_idle_conversation(db, conversation)
    if (
        db.scalar(
            select(GenerationJob.id)
            .where(
                GenerationJob.collection_id == collection.id,
                GenerationJob.status.in_(["queued", "running"]),
            )
            .limit(1)
        )
        is not None
    ):
        raise HTTPException(409, "conversation_task_running")
    # All authoritative bindings and affected workspaces are now locked.
    delete_collection(collection.id, account, transaction)
    live_collection_ids = {
        row.id for row in related_collections if row.deleted_at is None and row.id != collection.id
    }
    accessible = {
        str(row.test_case_id) for row in memberships if row.collection_id in live_collection_ids
    }
    tracked_ids = {str(row.id) for row in cases}
    for conversation in affected:
        # Preserve the locked pre-delete destination and resolved source set;
        # deleted A-only sources cannot be re-resolved after the deletion.
        state = effective[conversation.id]
        old_version = state.get("version", 0)
        items = []
        for item in state.get("items", []):
            if (
                item.get("kind") == "asset"
                and item.get("case_id") in tracked_ids
                and item.get("case_id") not in accessible
            ):
                continue
            item = dict(item)
            if item.get("kind") == "asset" and item.get("case_id") in tracked_ids:
                item["collection_ids"] = sorted(
                    {
                        str(row.collection_id)
                        for row in memberships
                        if str(row.test_case_id) == item["case_id"]
                        and row.collection_id in live_collection_ids
                    }
                )
            items.append(item)
        for operation in db.scalars(
            select(ConversationOperation).where(
                ConversationOperation.conversation_id == conversation.id,
            )
        ):
            operation.payload = {
                "selection_version": old_version,
                "destination_collection_id": state.get("active_collection_id"),
                **dict(operation.payload or {}),
            }
        active = state.get("active_collection_id")
        if active == str(collection.id):
            active = None
        _write(conversation, items, old_version + 1, active, "approved_collection_delete")
        pending = dict(conversation.context).get("workbench_collection_proposal") or {}
        if pending.get("status") == "pending" and pending.get("id") != proposal["id"]:
            conversation.context = {
                **dict(conversation.context),
                "workbench_collection_proposal": {
                    **pending,
                    "status": "invalidated",
                    "reason": "collection_impact_changed",
                },
            }
        conversation.updated_at = datetime.now(UTC)
    return {
        "action": "delete",
        "collection_id": str(collection.id),
        "name": proposal["name"],
        "deleted": True,
        "preserved_assets": True,
    }
