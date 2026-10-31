"""QA transport for the original continuous CRUD oracle, without a new scheduler."""

from typing import ClassVar
from unittest.mock import patch
from uuid import UUID

from sqlalchemy import select
from workbench_agent_live_continuation import DurableDispatch
from workbench_agent_live_crud import CrudJourney
from workbench_agent_live_journey import require
from workbench_request_continuation import NaturalDurableJourney, RequestWorkerDispatch

INDEX = "casepilot.agent.index_knowledge_source"


class UploadBatch(DurableDispatch):
    """Source-owned upload task, deliberately not a fabricated workbench run."""

    task_methods: ClassVar = {INDEX: "index_knowledge_source"}

    def __init__(self, cid, response, existing_sources):
        super().__init__(cid)
        from casepilot_api.database import get_session_factory
        from casepilot_api.models import (
            Conversation,
            KnowledgeDocument,
            KnowledgeSource,
            TaskOutbox,
        )

        self.source_id = UUID(response["source"]["id"])
        require(self.source_id not in existing_sources, "crud_index_not_new_upload")
        self.versions = {
            UUID(d["id"]): d["version"] for d in response["source"]["documents"]
        }
        require(
            set(self.versions) == {UUID(d) for d in response["document_ids"]}
            and bool(self.versions),
            "crud_index_document_mismatch",
        )
        with get_session_factory()() as db:
            conv = db.get(Conversation, self.cid)
            source = db.get(KnowledgeSource, self.source_id)
            require(
                conv is not None
                and source is not None
                and source.account_id == conv.account_id
                and source.space_id == conv.space_id,
                "crud_index_owner_mismatch",
            )
            self.account_id, self.space_id = conv.account_id, conv.space_id
            rows = list(
                db.scalars(
                    select(TaskOutbox).where(
                        TaskOutbox.task_name == INDEX,
                        TaskOutbox.task_id == f"knowledge-index:{self.source_id}",
                    )
                )
            )
            require(
                len(rows) == 1 and rows[0].status == "pending",
                "crud_index_task_mismatch",
            )
            self.outbox_id = rows[0].id
            self.checksums = {
                d.id: d.checksum
                for d in db.scalars(
                    select(KnowledgeDocument).where(
                        KnowledgeDocument.source_id == self.source_id
                    )
                )
            }
            self.validate(db, rows[0])

    def validate(self, db, row):
        from casepilot_api.models import (
            Conversation,
            KnowledgeDocument,
            KnowledgeSource,
        )

        conv = db.get(Conversation, self.cid)
        source = db.get(KnowledgeSource, self.source_id, populate_existing=True)
        require(
            conv is not None
            and conv.account_id == self.account_id
            and conv.space_id == self.space_id
            and source is not None
            and source.account_id == self.account_id
            and source.space_id == self.space_id
            and source.deleted_at is None
            and str(source.id) in conv.context.get("knowledge_source_ids", []),
            "crud_index_owner_mismatch",
        )
        docs = list(
            db.scalars(
                select(KnowledgeDocument)
                .where(KnowledgeDocument.source_id == self.source_id)
                .execution_options(populate_existing=True)
            )
        )
        require(
            {d.id: d.version for d in docs} == self.versions
            and {d.id: d.checksum for d in docs} == self.checksums
            and all(
                d.space_id == self.space_id
                and str(d.id) in conv.context.get("document_ids", [])
                for d in docs
            ),
            "crud_index_document_changed",
        )
        require(
            row.id == self.outbox_id
            and row.task_name == INDEX
            and row.task_id == f"knowledge-index:{self.source_id}"
            and row.task_args == [str(self.source_id)]
            and row.status in {"pending", "dispatched"},
            "crud_index_task_mismatch",
        )

    def before_dispatch(self):
        from casepilot_api.database import get_session_factory
        from casepilot_api.models import TaskOutbox

        with get_session_factory()() as db:
            for row in db.scalars(
                select(TaskOutbox).where(TaskOutbox.status == "pending")
            ):
                self.validate(
                    db, row
                )  # Unknown/foreign deliveries remain untouched, not skipped.

    def enqueue(self, name, args, **kwargs):
        from casepilot_api.database import get_session_factory
        from casepilot_api.models import TaskOutbox

        require(
            name == INDEX and args == [str(self.source_id)], "crud_index_task_mismatch"
        )
        with get_session_factory()() as db:
            self.validate(db, db.get(TaskOutbox, self.outbox_id))
        self.queue.append((name, str(self.source_id)))

    async def index(self, tasks):
        with patch.object(tasks.celery_app, "send_task", side_effect=self.enqueue):
            await self.drain(
                tasks, timeout_seconds=180, before_dispatch=self.before_dispatch
            )
        from casepilot_api.database import get_session_factory
        from casepilot_api.models import KnowledgeSource, TaskOutbox

        with get_session_factory()() as db:
            row = db.get(TaskOutbox, self.outbox_id)
            self.validate(db, row)
            source = db.get(KnowledgeSource, self.source_id)
            require(
                row.status == "dispatched" and source.status == "ready",
                "crud_index_not_ready",
            )


class CrudDispatch(RequestWorkerDispatch):
    @property
    def queue(self):
        # Preserve the original no-unconsumed-task assertion using actual persisted state.
        from casepilot_api.database import get_session_factory
        from casepilot_api.models import TaskOutbox

        with get_session_factory()() as db:
            return list(
                db.scalars(select(TaskOutbox.id).where(TaskOutbox.status == "pending"))
            )


class DurableCrudJourney(NaturalDurableJourney, CrudJourney):
    upload_batch = None

    async def request(self, method, path, **kwargs):
        is_upload = method == "POST" and path.endswith("/attachments")
        if is_upload:
            from casepilot_api.database import get_session_factory
            from casepilot_api.models import KnowledgeSource

            with get_session_factory()() as db:
                existing = set(db.scalars(select(KnowledgeSource.id)))
        result = await super().request(method, path, **kwargs)
        if is_upload:
            require(self.upload_batch is None, "crud_index_batch_not_drained")
            self.upload_batch = UploadBatch(path.split("/")[2], result, existing)
        return result

    async def drain_workers(self, tasks):
        if self.upload_batch is not None:
            batch = self.upload_batch
            await batch.index(tasks)
            self.report["source_owned_index_tasks"] = (
                self.report.get("source_owned_index_tasks", 0) + batch.executed
            )
            self.upload_batch = None
            return
        await super().drain_workers(tasks)

    async def post(self, path, body):
        result = await super().post(path, body)
        mode = None
        if "/collection-proposals/" in path and path.endswith("/confirm"):
            mode = "applied"
        elif path.endswith("/test-briefs/confirm"):
            mode = "workers"
        elif path.endswith("/candidates/commit") or (
            path.startswith("/case-change-sets/") and path.endswith("/apply")
        ):
            mode = "applied"
        if mode:
            require(self.current_request is not None, "durable_request_missing")
            await self.current_request.advance(self.tasks, mode)
            state = self.current_request.state()
            self.report.setdefault("crud_human_boundaries", []).append(
                {
                    "mode": mode,
                    "status": state["status"],
                    "cursor": state["cursor"],
                    "steps": state["steps"],
                    "pending_outbox": state["pending_outbox"],
                    "pending_events": state["pending_events"],
                }
            )
            if mode == "applied":
                require(state["status"] == "completed", "durable_apply_not_terminal")
        return result
