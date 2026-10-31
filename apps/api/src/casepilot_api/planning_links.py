"""Versioned coverage links, independent of formal case content."""

from fastapi import HTTPException
from sqlalchemy import select

from casepilot_api.models import (
    CollectionCaseMembership,
    TestCase,
    TestCaseRevision,
    WorkspaceCaseLink,
    WorkspaceTestBrief,
)


def links_view(db, conversation):
    rows = db.execute(
        select(WorkspaceCaseLink, WorkspaceTestBrief.version, TestCase, TestCaseRevision)
        .join(WorkspaceTestBrief, WorkspaceTestBrief.id == WorkspaceCaseLink.brief_id)
        .join(TestCase, TestCase.id == WorkspaceCaseLink.test_case_id)
        .join(TestCaseRevision, TestCaseRevision.id == TestCase.current_revision_id)
        .where(
            WorkspaceTestBrief.conversation_id == conversation.id,
            TestCase.space_id == conversation.space_id,
            TestCase.deleted_at.is_(None),
        )
        .order_by(WorkspaceTestBrief.version, WorkspaceCaseLink.test_point_id, TestCase.case_key)
    ).all()
    return [
        {
            "brief_version": version,
            "test_point_id": link.test_point_id,
            "test_case_id": str(case.id),
            "revision_id": str(link.revision_id),
            "case_key": case.case_key,
            "title": revision.title,
            "origin": link.origin,
            "stale": case.current_revision_id != link.revision_id,
        }
        for link, version, case, revision in rows
    ]


def link_existing_case(db, conversation, brief, point_id, case_id, revision_id, remove=False):
    if point_id not in {
        p["id"] for p in (brief.content.get("planning") or {}).get("test_points", [])
    }:
        raise HTTPException(422, "planning_selection_invalid")
    case = db.scalar(
        select(TestCase)
        .join(CollectionCaseMembership, CollectionCaseMembership.test_case_id == TestCase.id)
        .where(
            TestCase.id == case_id,
            TestCase.space_id == conversation.space_id,
            TestCase.deleted_at.is_(None),
            CollectionCaseMembership.collection_id == conversation.collection_id,
        )
        .with_for_update(of=TestCase)
    )
    if case is None:
        raise HTTPException(404, "test_case_not_found")
    if not remove and case.current_revision_id != revision_id:
        raise HTTPException(409, "case_link_revision_changed")
    link = db.scalar(
        select(WorkspaceCaseLink).where(
            WorkspaceCaseLink.brief_id == brief.id,
            WorkspaceCaseLink.test_point_id == point_id,
            WorkspaceCaseLink.test_case_id == case.id,
        )
    )
    if remove:
        if link is not None:
            db.delete(link)
    elif link is not None:
        link.revision_id = revision_id
    else:
        db.add(
            WorkspaceCaseLink(
                brief_id=brief.id,
                test_point_id=point_id,
                test_case_id=case.id,
                revision_id=revision_id,
                origin="manual",
            )
        )


def link_committed_candidate(db, conversation, candidate, case, cache):
    if not candidate.snapshot.get("test_point_ids"):
        return
    if candidate.generation_job_id in cache:
        brief = cache[candidate.generation_job_id]
    else:
        brief = _candidate_brief(db, conversation, candidate)
        cache[candidate.generation_job_id] = brief
    if brief is None:
        return
    allowed = {p["id"] for p in (brief.content.get("planning") or {}).get("test_points", [])}
    existing_key = ("links", brief.id)
    if existing_key not in cache:
        cache[existing_key] = {
            (link.test_point_id, link.test_case_id): link
            for link in db.scalars(
                select(WorkspaceCaseLink).where(WorkspaceCaseLink.brief_id == brief.id)
            )
        }
    for point_id in set(candidate.snapshot.get("test_point_ids") or []) & allowed:
        key = (point_id, case.id)
        if key in cache[existing_key]:
            cache[existing_key][key].revision_id = case.current_revision_id
            continue
        link = WorkspaceCaseLink(
            brief_id=brief.id,
            test_point_id=point_id,
            test_case_id=case.id,
            revision_id=case.current_revision_id,
            origin="generated",
        )
        db.add(link)
        cache[existing_key][key] = link


def _candidate_brief(db, conversation, candidate):
    from casepilot_api.models import GenerationJob

    job = (
        db.get(GenerationJob, candidate.generation_job_id) if candidate.generation_job_id else None
    )
    version = (job.input_payload or {}).get("confirmed_test_brief_version") if job else None
    if version is None:
        return
    brief = db.scalar(
        select(WorkspaceTestBrief).where(
            WorkspaceTestBrief.conversation_id == conversation.id,
            WorkspaceTestBrief.version == version,
        )
    )
    return brief


def inherit_unchanged_links(db, previous, current):
    """Reviewer choice-only revisions retain links; requirement edits do not."""
    from copy import deepcopy

    if previous is None:
        return
    before, after = deepcopy(previous.content), deepcopy(current.content)
    for content in (before, after):
        planning = content.get("planning") or {}
        planning.pop("reuse", None)
        planning.pop("brief_version", None)
    if before != after:
        return
    for link in db.scalars(
        select(WorkspaceCaseLink).where(WorkspaceCaseLink.brief_id == previous.id)
    ):
        db.add(
            WorkspaceCaseLink(
                brief_id=current.id,
                test_point_id=link.test_point_id,
                test_case_id=link.test_case_id,
                revision_id=link.revision_id,
                origin=link.origin,
            )
        )


def reusable_current_case(db, conversation, candidate, cache):
    """Link only an unchanged candidate to its pinned, live, same-collection asset."""
    import json
    from uuid import UUID

    from casepilot_api.models import GenerationJob

    job_id = candidate.generation_job_id
    if not job_id or not candidate.snapshot.get("test_point_ids"):
        return None
    if job_id not in cache:
        cache[job_id] = db.get(GenerationJob, job_id)
    job = cache[job_id]
    if job is None:
        return None
    plan = job.input_payload.get("confirmed_plan") or {}
    reuse = plan.get("reuse") or {}
    decisions = {item["point_id"]: item for item in reuse.get("decisions", [])}
    points = candidate.snapshot["test_point_ids"]
    if any(reuse.get("user_choices", {}).get(point) == "copy" for point in points):
        return None
    reserved = {item["source"]["key"]: item
                for item in plan.get("reserved_reuse_outputs", [])}
    claimed = set()
    for reference in candidate.snapshot.get("source_refs", []):
        try:
            value = json.loads(reference.get("excerpt") or "")
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict) and value.get("action") == "reuse":
            key = value.get("source_key")
            if isinstance(key, str) and key in reserved:
                claimed.add(key)
    if claimed:
        if len(claimed) != 1:
            raise HTTPException(409, "reserved_reuse_binding_changed")
        reservation = reserved[next(iter(claimed))]
        actual_points = {point["id"]: point for point in plan.get("test_points", [])}
        ids = reservation.get("point_ids", [])
        if (reservation.get("action") != "reuse" or len(points) != len(set(points))
                or set(points) != set(ids)
                or set(reservation.get("point_snapshots", {})) != set(ids)
                or any(reservation["point_snapshots"][pid] != actual_points.get(pid) for pid in ids)
                or any(reuse.get("user_choices", {}).get(pid) in {"new", "exclude"}
                       for pid in ids)):
            raise HTTPException(409, "reserved_reuse_binding_changed")
        source = reservation["source"]
        same_object = source.get("test_object_match") == "same"
    else:
        selected = [decisions.get(point) for point in points]
        if any(not item or item.get("action") != "reuse" for item in selected):
            return None
        sources = [item.get("source") or {} for item in selected]
        source = sources[0]
        if any(s.get("key") != source.get("key") for s in sources):
            return None
        same_object = all(item.get("test_object_match") == "same" for item in selected)
    if source.get("kind") != "formal":
        return None
    try:
        case_id, revision_id = UUID(source["case_id"]), UUID(str(source["revision"]))
    except (ValueError, KeyError, TypeError):
        return None
    membership = db.scalar(
        select(CollectionCaseMembership).where(
            CollectionCaseMembership.collection_id == conversation.collection_id,
            CollectionCaseMembership.test_case_id == case_id,
        )
    )
    if membership is None and (
        reuse.get("asset_confirmation") != "reuse"
        or source.get("key") not in reuse.get("confirmed_asset_keys", [])
        or not same_object
    ):
        return None
    case = db.scalar(
        select(TestCase)
        .where(
            TestCase.id == case_id,
            TestCase.space_id == conversation.space_id,
            TestCase.deleted_at.is_(None),
        )
        .with_for_update(of=TestCase)
    )
    if case is None:
        raise HTTPException(409, "generation_asset_changed")
    if case.current_revision_id != revision_id:
        raise HTTPException(409, "case_link_revision_changed")
    revision = db.get(TestCaseRevision, revision_id)
    fields = ("title", "module", "priority", "case_type", "preconditions")
    if any(candidate.snapshot.get(field) != getattr(revision, field) for field in fields):
        return None
    steps = [
        {"action": s.get("action", ""), "expected": s.get("expected", "")}
        for s in candidate.snapshot.get("steps", [])
    ]
    original = [
        {"action": s.get("action", ""), "expected": s.get("expected", "")} for s in revision.steps
    ]
    if steps != original or candidate.snapshot.get("tags", []) != revision.tags:
        return None
    if membership is None:
        # A concurrent adoption may have linked this asset while we waited for its lock.
        membership = db.scalar(
            select(CollectionCaseMembership).where(
                CollectionCaseMembership.collection_id == conversation.collection_id,
                CollectionCaseMembership.test_case_id == case.id,
            )
        )
    if membership is None:
        from sqlalchemy import func

        position = (
            db.scalar(
                select(func.coalesce(func.max(CollectionCaseMembership.position), -1)).where(
                    CollectionCaseMembership.collection_id == conversation.collection_id
                )
            )
            + 1
        )
        db.add(
            CollectionCaseMembership(
                collection_id=conversation.collection_id, test_case_id=case.id, position=position
            )
        )
        db.flush()
    return case
