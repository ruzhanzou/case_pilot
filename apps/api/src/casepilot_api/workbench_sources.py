"""Bounded discovery and source provenance; attachment discovery never imports assets."""

import json
from copy import deepcopy
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select

from casepilot_api.models import (
    CaseCollection,
    CollectionCaseMembership,
    TestCase,
    TestCaseRevision,
    WorkspaceCandidate,
)
from casepilot_api.workbench_selection import _resolve_sources, authorize, selection_state


def source_version(snapshot, provenance):
    return sha256(
        json.dumps(
            {"snapshot": snapshot, "provenance": provenance}, sort_keys=True, ensure_ascii=False
        ).encode()
    ).hexdigest()


def uploaded_row_identity(document_id, sheet, row):
    return f"upload:{document_id}:{sha256(str(sheet).encode()).hexdigest()[:16]}:{row}"


def bounded_rows(rows, max_chars=60000):
    output, size = [], 0
    for original in rows:
        item = deepcopy(original)
        encoded = json.dumps(item, ensure_ascii=False)
        if len(encoded) > 12000 and "snapshot" in item:
            snapshot = item["snapshot"]
            item["snapshot"] = {
                key: str(snapshot.get(key, ""))[:1000] for key in ("title", "module", "priority")
            }
            item["snapshot_truncated"] = True
            encoded = json.dumps(item, ensure_ascii=False)
        if size + len(encoded) > max_chars:
            break
        output.append(item)
        size += len(encoded)
    return {"cases": output, "truncated": len(output) < len(rows)}


class WorkbenchSources:
    def __init__(self, db, account, conversation, payload=None):
        self.db, self.account, self.conversation, self.payload = db, account, conversation, payload

    def query_assets(
        self, search="", limit=30, offset=0, collection_ids=None, priorities=None, scope="space"
    ):
        authorize(self.db, self.account, self.conversation)
        limit, offset = min(max(limit, 1), 100), max(offset, 0)
        query = (
            select(TestCase, TestCaseRevision)
            .join(TestCaseRevision, TestCase.current_revision_id == TestCaseRevision.id)
            .where(TestCase.space_id == self.conversation.space_id, TestCase.deleted_at.is_(None))
        )
        memberships = (
            select(CollectionCaseMembership.test_case_id)
            .join(CaseCollection, CaseCollection.id == CollectionCaseMembership.collection_id)
            .where(
                CaseCollection.space_id == self.conversation.space_id,
                CaseCollection.deleted_at.is_(None),
            )
        )
        if collection_ids:
            memberships = memberships.where(
                CaseCollection.id.in_([UUID(str(v)) for v in collection_ids])
            )
        if scope == "current_collection":
            memberships = memberships.where(CaseCollection.id == self.conversation.collection_id)
        elif scope == "selection":
            state = selection_state(self.conversation) or {}
            query = query.where(
                TestCase.id.in_(
                    [UUID(i["case_id"]) for i in state.get("items", []) if i["kind"] == "asset"]
                )
            )
        elif scope != "space":
            raise ValueError("invalid_source_scope")
        query = query.where(TestCase.id.in_(memberships))
        if search:
            query = query.where(TestCaseRevision.title.icontains(search, autoescape=True))
        if priorities:
            query = query.where(TestCaseRevision.priority.in_(priorities))
        rows = list(self.db.execute(query.order_by(TestCase.id).offset(offset).limit(limit + 1)))
        cases = []
        for case, revision in rows[:limit]:
            snapshot = {
                key: deepcopy(getattr(revision, key))
                for key in (
                    "title",
                    "description",
                    "module",
                    "priority",
                    "case_type",
                    "tags",
                    "preconditions",
                    "steps",
                    "source_refs",
                )
            }
            snapshot["current_revision_id"] = str(revision.id)
            cases.append(
                {
                    "ref": f"asset:{case.id}",
                    "kind": "asset",
                    "version": str(revision.id),
                    "source_ref": {
                        "kind": "asset",
                        "case_id": str(case.id),
                        "revision_id": str(revision.id),
                    },
                    "snapshot": snapshot,
                }
            )
        result = bounded_rows(cases)
        result.update(
            {
                "search_mode": "title_literal_substring" if search else "catalog",
                "returned_count": len(result["cases"]),
                "offset": offset,
                "has_more": len(rows) > limit or result["truncated"],
                "next_offset": offset + len(result["cases"]),
            }
        )
        return result

    def resolve_assets(self, targets):
        return _resolve_sources(self.db, self.account, self.conversation, targets)

    def query_candidates(self, limit=30, offset=0):
        authorize(self.db, self.account, self.conversation)
        # Latest across ALL lifecycle statuses: old candidate must not resurface.
        latest = {}
        rows = self.db.scalars(
            select(WorkspaceCandidate)
            .where(WorkspaceCandidate.conversation_id == self.conversation.id)
            .order_by(WorkspaceCandidate.ref, WorkspaceCandidate.version.desc())
            .limit(1001)
        )
        scanned = 0
        for row in rows:
            scanned += 1
            latest.setdefault(row.ref, row)
        cases = [
            {
                "ref": f"candidate:{r.ref}",
                "kind": "candidate",
                "version": str(r.version),
                "source_ref": {
                    "kind": "candidate",
                    "conversation_id": str(self.conversation.id),
                    "candidate_ref": r.ref,
                },
                "snapshot": deepcopy(r.snapshot),
            }
            for r in latest.values()
            if r.status == "candidate"
        ]
        limit, offset = min(max(limit, 1), 100), max(offset, 0)
        result = bounded_rows(cases[offset : offset + limit])
        result.update(
            {
                "has_more": len(cases) > offset + limit or scanned > 1000 or result["truncated"],
                "next_offset": offset + len(result["cases"]),
                "scan_truncated": scanned > 1000,
            }
        )
        return result

    def uploaded_cases(self, limit=100, offset=0, _exact=False):
        from datetime import UTC, datetime

        from sqlalchemy import or_

        from casepilot_api.conversations import _resolve_turn_attachments
        from casepilot_api.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSource
        from casepilot_api.schemas import ConversationMessageCreate

        authorize(self.db, self.account, self.conversation)
        payload = self.payload or ConversationMessageCreate(content="Read attached case rows")
        payload = _resolve_turn_attachments(self.db, self.conversation, payload)
        if not payload.document_ids:
            return {"cases": [], "has_more": False, "next_offset": offset}
        query = (
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .join(KnowledgeSource, KnowledgeDocument.source_id == KnowledgeSource.id)
            .where(
                KnowledgeDocument.id.in_(payload.document_ids),
                KnowledgeDocument.space_id == self.conversation.space_id,
                KnowledgeChunk.space_id == self.conversation.space_id,
                KnowledgeDocument.status == "ready",
                KnowledgeSource.deleted_at.is_(None),
                or_(
                    KnowledgeSource.persistence == "space",
                    KnowledgeSource.account_id == self.account.id,
                ),
                or_(
                    KnowledgeDocument.expires_at.is_(None),
                    KnowledgeDocument.expires_at > datetime.now(UTC),
                ),
            )
            .order_by(KnowledgeDocument.id, KnowledgeChunk.ordinal)
            .limit(201)
        )
        cases, seen, scanned = [], set(), 0
        rows = list(self.db.execute(query))
        for chunk, document in rows[:200]:
            metadata = chunk.chunk_metadata or {}
            for row in metadata.get("reference_cases", []):
                scanned += 1
                if scanned > 8000:
                    break
                if not isinstance(row, dict) or not isinstance(row.get("row"), int):
                    continue
                ref = uploaded_row_identity(document.id, metadata.get("sheet", ""), row["row"])
                if ref in seen:
                    continue
                seen.add(ref)
                provenance = {
                    "kind": "uploaded_row",
                    "document_id": str(document.id),
                    "source_id": str(document.source_id),
                    "chunk_id": str(chunk.id),
                    "label": document.original_name,
                    "document_version": document.version,
                    "checksum": document.checksum,
                    "sheet": metadata.get("sheet", ""),
                    "row": row["row"],
                    "row_end": row.get("row_end", row["row"]),
                    "source_cells": deepcopy(row.get("source_cells", {})),
                }
                cases.append(
                    {
                        "ref": ref,
                        "kind": "uploaded_row",
                        "version": source_version(row, provenance),
                        "source_ref": provenance,
                        "snapshot": deepcopy(row),
                    }
                )
            if scanned > 8000:
                break
        limit, offset = min(max(limit, 1), 100), max(offset, 0)
        if _exact:
            return {"cases": cases, "scan_truncated": len(rows) > 200 or scanned > 8000}
        result = bounded_rows(cases[offset : offset + limit])
        result.update(
            {
                "next_offset": offset + len(result["cases"]),
                "has_more": len(cases) > offset + limit or result["truncated"],
                "scan_truncated": len(rows) > 200 or scanned > 8000,
            }
        )
        return result

    def resolve_uploaded_rows(self, targets):
        from fastapi import HTTPException

        if len(targets) > 100:
            raise HTTPException(422, "selection_limit_exceeded")
        catalog = {row["ref"]: row for row in self.uploaded_cases(_exact=True)["cases"]}
        resolved = []
        for target in targets:
            target = target.model_dump() if hasattr(target, "model_dump") else target
            row = catalog.get(target["ref"])
            if row is None or row["version"] != str(target["version"]):
                raise HTTPException(409, "workbench_source_changed")
            resolved.append(row)
        return resolved

    def preview_uploaded_rows(self, targets):
        # Validate ALL sources first. Savepoint prevents partial materialization.
        from casepilot_agent.contracts import TestCaseDraft
        from fastapi import HTTPException

        sources = self.resolve_uploaded_rows(targets)
        for row in sources:
            TestCaseDraft.model_validate(
                {
                    **row["snapshot"],
                    "id": row["ref"],
                    "module": row["snapshot"].get("module") or "未分类",
                    "test_point_ids": [],
                }
            )
        output = []
        with self.db.begin_nested():
            for row in sources:
                ref = (
                    "upload-"
                    + sha256((row["ref"] + ":" + row["version"]).encode()).hexdigest()[:48]
                )
                candidate = self.db.scalar(
                    select(WorkspaceCandidate)
                    .where(
                        WorkspaceCandidate.conversation_id == self.conversation.id,
                        WorkspaceCandidate.ref == ref,
                    )
                    .order_by(WorkspaceCandidate.version.desc())
                    .limit(1)
                )
                if candidate is not None and candidate.status != "candidate":
                    raise HTTPException(409, "workbench_source_changed")
                if candidate is None:
                    candidate = WorkspaceCandidate(
                        conversation_id=self.conversation.id,
                        ref=ref,
                        version=1,
                        position=0,
                        included=False,
                        status="candidate",
                        created_by=self.account.id,
                        snapshot={
                            **deepcopy(row["snapshot"]),
                            "source_provenance": deepcopy(row["source_ref"]),
                            "source_version": row["version"],
                            "source_refs": [
                                {
                                    "source_id": row["source_ref"]["source_id"],
                                    "document_id": row["source_ref"]["document_id"],
                                    "chunk_id": row["source_ref"]["chunk_id"],
                                    "label": row["source_ref"]["label"][:300],
                                    "locator": (
                                        f"Sheet {row['source_ref']['sheet']}，行 "
                                        f"{row['source_ref']['row']}-{row['source_ref']['row_end']}"
                                    )[:500],
                                    "excerpt": "",
                                }
                            ],
                        },
                    )
                    self.db.add(candidate)
                    self.db.flush()
                output.append(
                    {
                        "ref": f"candidate:{candidate.ref}",
                        "kind": "candidate",
                        "version": str(candidate.version),
                        "source_ref": row["source_ref"],
                        "snapshot": deepcopy(candidate.snapshot),
                    }
                )
        return output
