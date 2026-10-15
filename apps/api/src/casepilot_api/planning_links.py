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
    for point_id in set(candidate.snapshot.get("test_point_ids") or []) & allowed:
        db.add(
            WorkspaceCaseLink(
                brief_id=brief.id,
                test_point_id=point_id,
                test_case_id=case.id,
                revision_id=case.current_revision_id,
                origin="generated",
            )
        )


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
