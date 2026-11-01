"""Typed reuse output proposals and exact user-approved destination transitions."""

from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy import select

from casepilot_api.models import CaseCollection


def prepare_destination(db, account, conversation, payload, destination):
    from casepilot_api.case_management import ensure_collection

    ids = set(payload.source_collection_ids)
    if conversation.collection_id:
        ids.add(conversation.collection_id)
    target = (
        conversation.collection_id if destination.kind == "current" else destination.collection_id
    )
    if destination.kind != "new":
        if target is None:
            raise HTTPException(409, "reuse_destination_required")
        collection = ensure_collection(db, account, target)
        if collection.space_id != conversation.space_id:
            raise HTTPException(404, "collection_not_found")
    elif db.scalar(
        select(CaseCollection.id)
        .where(
            CaseCollection.space_id == conversation.space_id,
            CaseCollection.deleted_at.is_(None),
            CaseCollection.name == destination.name,
        )
        .limit(1)
    ):
        raise HTTPException(409, "reuse_destination_name_ambiguous")
    return {"reuse_destination": destination, "source_collection_ids": sorted(ids, key=str)}


def approved(operation):
    return bool(operation and (operation.payload or {}).get("reuse_destination_approved"))


def proposal_metadata(conversation, destination):
    target = (
        conversation.collection_id if destination.kind == "current" else destination.collection_id
    )
    return {
        "reuse_destination": destination.model_dump(mode="json"),
        "suggested_collection_id": str(target) if target else None,
        "suggested_collection_name": destination.name,
        "allow_create_collection": destination.kind == "new",
        "require_new_collection": destination.kind == "new",
    }


def validate_choice(db, account, conversation, operation, request, choice):
    """Validate the pre-effect authority, before creating any destination."""
    from casepilot_api.conversations import _assert_workbench_selection
    from casepilot_api.schemas import ConversationMessageCreate, ReuseDestination

    destination = ReuseDestination.model_validate(request["reuse_destination"])
    _assert_workbench_selection(db, conversation, operation, account=account)
    target = (
        conversation.collection_id if destination.kind == "current" else destination.collection_id
    )
    if destination.kind == "new":
        if choice.collection_id is not None or choice.create_collection_name != destination.name:
            raise HTTPException(409, "collection_confirmation_choice_mismatch")
        # A concurrent user-created namesake requires a fresh explicit choice.
        prepare_destination(
            db,
            account,
            conversation,
            ConversationMessageCreate(content="Validate destination"),
            destination,
        )
    elif choice.collection_id != target or choice.create_collection_name is not None:
        raise HTTPException(409, "collection_confirmation_choice_mismatch")


def apply_destination(db, account, conversation, operation, collection, request):
    """Called only inside the exact human confirmation transaction; preserves sources."""
    from casepilot_api.collection_references import capture_reference_binding
    from casepilot_api.schemas import ConversationMessageCreate
    from casepilot_api.workbench_selection import selection_state, stamp_operation_binding

    state = selection_state(conversation)
    conversation.collection_id = collection.id
    if state is not None:
        from casepilot_api.workbench_selection import _write

        _write(
            conversation, deepcopy(state["items"]), state["version"] + 1, str(collection.id), "user"
        )
        request = {**request, "selection_version": state["version"] + 1}
    # Original source collection and exact versions were locked and checked before
    # this transition. They remain in the new binding and in every downstream job.
    binding = capture_reference_binding(
        db, conversation, ConversationMessageCreate.model_validate(request), lock=True
    )
    operation.payload = {
        **operation.payload,
        "prepared_request": request,
        "reuse_destination_approved": str(collection.id),
        "reference_binding": binding,
    }
    stamp_operation_binding(conversation, operation)
