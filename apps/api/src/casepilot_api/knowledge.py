from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from casepilot_api.auth import CurrentAccount, require_space_membership
from casepilot_api.config import get_settings
from casepilot_api.database import get_db_session
from casepilot_api.models import KnowledgeDocument, KnowledgeSource
from casepilot_api.schemas import (
    KnowledgeDocumentView,
    KnowledgeSourceView,
    KnowledgeUploadView,
)
from casepilot_api.task_outbox import enqueue_task

router = APIRouter(prefix="/api/v1", tags=["knowledge"])
settings = get_settings()
DbSession = Annotated[Session, Depends(get_db_session)]
ALLOWED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".xlsx",
    ".csv",
    ".md",
    ".txt",
    ".png",
    ".jpg",
    ".jpeg",
}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/csv",
    "text/markdown",
    "text/plain",
    "image/png",
    "image/jpeg",
    "application/octet-stream",
}


def _signature_matches(extension: str, content: bytes) -> bool:
    if extension == ".pdf":
        return content.startswith(b"%PDF-")
    if extension in {".docx", ".xlsx"}:
        return content.startswith(b"PK\x03\x04")
    if extension == ".png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if extension in {".jpg", ".jpeg"}:
        return content.startswith(b"\xff\xd8\xff")
    return b"\x00" not in content[:4096]


def _source_view(db: Session, source: KnowledgeSource) -> KnowledgeSourceView:
    documents = db.scalars(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.source_id == source.id)
        .order_by(KnowledgeDocument.created_at.desc())
    ).all()
    return KnowledgeSourceView(
        id=source.id,
        space_id=source.space_id,
        name=source.name,
        kind=source.kind,
        persistence=source.persistence,
        status=source.status,
        error_code=source.error_code,
        document_count=len(documents),
        documents=[
            KnowledgeDocumentView(
                id=document.id,
                source_id=document.source_id,
                original_name=document.original_name,
                mime_type=document.mime_type,
                size_bytes=document.size_bytes,
                version=document.version,
                status=document.status,
                error_code=document.error_code,
                expires_at=document.expires_at,
                created_at=document.created_at,
            )
            for document in documents
        ],
        created_at=source.created_at,
    )


def _store_uploads(
    db: Session,
    account_id: UUID,
    space_id: UUID,
    name: str,
    files: list[UploadFile],
    persistence: str,
) -> KnowledgeUploadView:
    if not 1 <= len(files) <= 6:
        raise HTTPException(status_code=400, detail="upload_batch_must_contain_1_to_6_files")
    prepared: list[tuple[str, str, str, bytes]] = []
    for upload in files:
        original_name = Path(upload.filename or "document").name
        extension = Path(original_name).suffix.lower()
        mime_type = (upload.content_type or "application/octet-stream").lower()
        if extension not in ALLOWED_EXTENSIONS or mime_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(status_code=415, detail="unsupported_document_type")
        content = upload.file.read(settings.knowledge_max_file_bytes + 1)
        if not content or len(content) > settings.knowledge_max_file_bytes:
            raise HTTPException(status_code=413, detail="document_size_limit_exceeded")
        if not _signature_matches(extension, content):
            raise HTTPException(status_code=415, detail="document_signature_mismatch")
        prepared.append((original_name, extension, mime_type, content))

    source = KnowledgeSource(
        space_id=space_id,
        account_id=account_id,
        name=name.strip() or "未命名资料",
        kind="upload",
        persistence=persistence,
        status="uploaded",
    )
    db.add(source)
    db.flush()
    storage_root = Path(settings.knowledge_storage_path)
    storage_root.mkdir(parents=True, exist_ok=True)
    documents: list[KnowledgeDocument] = []
    written_paths: list[Path] = []
    try:
        for original_name, extension, mime_type, content in prepared:
            document_id = uuid4()
            storage_key = f"{document_id.hex}{extension}"
            storage_path = storage_root / storage_key
            storage_path.write_bytes(content)
            written_paths.append(storage_path)
            document = KnowledgeDocument(
                id=document_id,
                source_id=source.id,
                space_id=space_id,
                original_name=original_name[:300],
                mime_type=mime_type,
                storage_key=storage_key,
                size_bytes=len(content),
                checksum=sha256(content).hexdigest(),
                version=1,
                status="uploaded",
                expires_at=(
                    datetime.now(UTC) + timedelta(days=7)
                    if persistence == "temporary"
                    else None
                ),
            )
            db.add(document)
            documents.append(document)
        enqueue_task(
            db,
            "casepilot.agent.index_knowledge_source",
            [str(source.id)],
            task_id=f"knowledge-index:{source.id}",
        )
        db.commit()
    except Exception:
        db.rollback()
        for storage_path in written_paths:
            storage_path.unlink(missing_ok=True)
        raise
    db.refresh(source)
    return KnowledgeUploadView(
        source=_source_view(db, source),
        document_ids=[document.id for document in documents],
    )


@router.post(
    "/spaces/{space_id}/knowledge-sources",
    response_model=KnowledgeUploadView,
    status_code=202,
)
def upload_knowledge_source(
    space_id: UUID,
    account: CurrentAccount,
    db: DbSession,
    name: Annotated[str, Form(min_length=1, max_length=240)],
    files: Annotated[list[UploadFile], File()],
) -> KnowledgeUploadView:
    require_space_membership(db, account.id, space_id)
    return _store_uploads(db, account.id, space_id, name, files, "space")


@router.post(
    "/spaces/{space_id}/knowledge-documents",
    response_model=KnowledgeUploadView,
    status_code=202,
)
def upload_temporary_documents(
    space_id: UUID,
    account: CurrentAccount,
    db: DbSession,
    files: Annotated[list[UploadFile], File()],
    name: Annotated[str, Form(max_length=240)] = "本次生成附件",
) -> KnowledgeUploadView:
    require_space_membership(db, account.id, space_id)
    return _store_uploads(db, account.id, space_id, name, files, "temporary")


@router.get(
    "/spaces/{space_id}/knowledge-sources",
    response_model=list[KnowledgeSourceView],
)
def list_knowledge_sources(
    space_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> list[KnowledgeSourceView]:
    require_space_membership(db, account.id, space_id)
    sources = db.scalars(
        select(KnowledgeSource)
        .where(
            KnowledgeSource.space_id == space_id,
            KnowledgeSource.deleted_at.is_(None),
        )
        .order_by(KnowledgeSource.created_at.desc())
    ).all()
    return [_source_view(db, source) for source in sources]


def _get_source(db: Session, account_id: UUID, source_id: UUID) -> KnowledgeSource:
    source = db.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.id == source_id,
            KnowledgeSource.deleted_at.is_(None),
        )
    )
    if source is None:
        raise HTTPException(status_code=404, detail="knowledge_source_not_found")
    require_space_membership(db, account_id, source.space_id)
    return source


@router.post(
    "/knowledge-sources/{source_id}/reindex",
    response_model=KnowledgeSourceView,
    status_code=202,
)
def reindex_knowledge_source(
    source_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> KnowledgeSourceView:
    source = _get_source(db, account.id, source_id)
    source.status = "uploaded"
    source.error_code = None
    for document in db.scalars(
        select(KnowledgeDocument).where(KnowledgeDocument.source_id == source.id)
    ):
        document.status = "uploaded"
        document.error_code = None
    enqueue_task(
        db,
        "casepilot.agent.index_knowledge_source",
        [str(source.id)],
        task_id=f"knowledge-reindex:{source.id}:{uuid4()}",
    )
    db.commit()
    return _source_view(db, source)


@router.delete("/knowledge-sources/{source_id}", status_code=204)
def delete_knowledge_source(
    source_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> None:
    source = _get_source(db, account.id, source_id)
    source.status = "deleted"
    source.deleted_at = datetime.now(UTC)
    enqueue_task(
        db,
        "casepilot.agent.cleanup_knowledge_source",
        [str(source.id)],
        task_id=f"knowledge-cleanup:{source.id}",
    )
    db.commit()
