"""Exact durable request scope, distinct from the wider workspace selection.

Canonical A+B does not authorize widening an original explicit A request. Only
successful controlled selection receipts replace scope; approval receipts may
rebase existing exact refs or map an adopted candidate to its actual formal asset.
"""
from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy import select

from casepilot_api.models import WorkspaceCandidate
from casepilot_api.schemas import ConversationMessageCreate, ConversationTargetSnapshot
from casepilot_api.workbench_selection import selection_state


def capture_authorized_scope(run, conversation, payload):
    """payload must already have passed resolve_selection_payload, not model input."""
    canonical = selection_state(conversation)
    request = payload.model_dump(mode="json")
    refs = {f"asset:{value}" for value in payload.target_case_ids}
    refs.update(f"candidate:{value.ref}" for value in payload.target_candidate_snapshots)
    sources = ([{"ref": item["ref"], "version": str(item["version"])}
                for item in canonical["items"] if item["ref"] in refs] if canonical else [])
    if canonical:
        request["selection_version"] = canonical["version"]
    run.checkpoint = {**run.checkpoint, "authorized_scope_request": request,
                      "authorized_sources": sources,
                      "authorized_scope_canonical": canonical is not None}


def restore_authorized_scope(run, conversation):
    request = deepcopy(run.checkpoint.get("authorized_scope_request")
                       or run.checkpoint["original_request"])
    if run.checkpoint.get("authorized_scope_canonical"):
        canonical = selection_state(conversation)
        if canonical is None:
            raise HTTPException(409, "workbench_scope_requires_selection")
        available = {item["ref"]: str(item["version"]) for item in canonical["items"]}
        sources = run.checkpoint.get("authorized_sources", [])
        if any(available.get(source["ref"]) != str(source["version"]) for source in sources):
            raise HTTPException(409, "workbench_scope_requires_selection")
        # Empty explicit scope must not become the remaining canonical selection.
        if not sources and available:
            raise HTTPException(409, "workbench_scope_requires_selection")
        request["selection_version"] = canonical["version"]
    return ConversationMessageCreate.model_validate(request)


def apply_authorized_scope_delta(db, run, conversation, *, approved_updates=None,
                                 removed_refs=(), adopted_sources=None,
                                 approved_destination_id=None):
    """Called only AFTER the preapproval token and actual effect deltas validate."""
    if ("authorized_scope_request" not in run.checkpoint
            or not run.checkpoint.get("authorized_scope_canonical")):
        # Legacy selectors remain intact; they are not silently materialized or widened.
        return deepcopy(run.checkpoint)
    updates, adopted = approved_updates or {}, adopted_sources or {}
    removed = set(removed_refs)
    sources = []
    for original in run.checkpoint.get("authorized_sources", []):
        ref = original["ref"]
        if ref in adopted:
            mapped = adopted[ref]
            sources.append({"ref": mapped["ref"], "version": str(mapped["version"])})
        elif ref not in removed:
            sources.append({"ref": ref, "version": str(updates.get(ref, original["version"]))})
    request = deepcopy(run.checkpoint["authorized_scope_request"])
    request["target_case_ids"] = [source["ref"].split(":", 1)[1] for source in sources
                                  if source["ref"].startswith("asset:")]
    snapshots = []
    for source in sources:
        if not source["ref"].startswith("candidate:"):
            continue
        ref = source["ref"].split(":", 1)[1]
        candidate = db.scalar(select(WorkspaceCandidate).where(
            WorkspaceCandidate.conversation_id == run.conversation_id,
            WorkspaceCandidate.ref == ref, WorkspaceCandidate.version == int(source["version"]),
        ))
        if candidate is None:
            raise HTTPException(409, "workbench_scope_requires_selection")
        snapshots.append(ConversationTargetSnapshot(ref=ref, version=candidate.version,
                         snapshot=deepcopy(candidate.snapshot)).model_dump(mode="json"))
    request.update(target_candidate_snapshots=snapshots, targets=[], target_scope="selected")
    canonical = selection_state(conversation)
    if canonical:
        request["selection_version"] = canonical["version"]
    run.checkpoint = {**run.checkpoint, "authorized_scope_request": request,
                      "authorized_sources": sources}
    return deepcopy(run.checkpoint)


def validate_authorized_scope(db, run, conversation):
    """Preapproval subset check; source liveness is also checked by validate_binding."""
    if "authorized_scope_request" in run.checkpoint:
        restore_authorized_scope(run, conversation)
    return True
