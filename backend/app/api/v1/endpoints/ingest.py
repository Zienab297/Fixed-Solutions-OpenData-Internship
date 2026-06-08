"""
/ingest endpoints — document upload, web crawl, and replace.

Flow for changed files:
  POST /ingest/document
    → same title + different hash → 409 FileChangedResponse
    → client asks user: replace or keep?
    → user confirms replace → POST /ingest/replace (with old_document_id)
    → hard delete old + insert new + dispatch Celery job
"""
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from uuid import UUID

from app.core.database import get_db
from app.api.v1.dependencies.auth import get_current_user, require_domain_access
from app.models.schemas.auth import CurrentUser
from app.models.schemas.ingest import IngestJobResponse, FileChangedResponse
from app.models.db.models import User
from app.repositories.document_repository import (
    DocumentRepository,
    DuplicateDocumentError,
    FileChangedError,
)
from app.workers.tasks import process_document, process_web_crawl

router = APIRouter(prefix="/ingest", tags=["Ingestion"])

ALLOWED_CONTENT_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/csv": "csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}


async def _resolve_user_id(current_user: CurrentUser, db: AsyncSession) -> UUID | None:
    result = await db.execute(
        select(User.id).where(User.keycloak_id == current_user.id)
    )
    row = result.scalar_one_or_none()
    return row if row else None


@router.post("/document", response_model=IngestJobResponse)
async def ingest_document(
    domain_id: UUID = Form(...),
    title: str = Form(None),
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a document for ingestion.

    Returns:
        200 IngestJobResponse       — new document queued
        409 FileChangedResponse     — same filename, content changed; confirm via /ingest/replace
        409 {error: duplicate}      — exact same file already ingested, nothing to do
        400                         — unsupported file type
    """
    await require_domain_access(domain_id, "contributor", current_user, db)

    source_type = ALLOWED_CONTENT_TYPES.get(file.content_type)
    if not source_type:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}")

    file_bytes = await file.read()
    resolved_title = title or file.filename
    internal_user_id = await _resolve_user_id(current_user, db)
    repo = DocumentRepository(db)

    try:
        doc = await repo.create(
            domain_id=domain_id,
            title=resolved_title,
            source_type=source_type,
            file_bytes=file_bytes,
            ingested_by=internal_user_id,
        )
    except DuplicateDocumentError as exc:
        # Exact same file — nothing changed, nothing to do
        raise HTTPException(
            status_code=409,
            detail={
                "error": "duplicate_document",
                "message": "This exact file has already been ingested into this domain.",
                "existing_document_id": str(exc.existing_id),
            },
        )
    except FileChangedError as exc:
        # Same filename, different content — ask the user what to do
        return JSONResponse(
            status_code=409,
            content=FileChangedResponse(
                error="file_changed",
                existing_document_id=exc.existing_id,
                old_hash_preview=exc.existing_hash[:8],
                new_hash_preview=exc.new_hash[:8],
                message=(
                    "A document with this name already exists in this domain but its "
                    "content has changed. Call POST /ingest/replace with the "
                    "old_document_id to replace it, or discard this upload to keep the "
                    "existing version."
                ),
            ).model_dump(mode="json"),
        )

    job = process_document.delay(
        document_id=str(doc.id),
        domain_id=str(domain_id),
        file_content=file_bytes,
        filename=file.filename,
    )

    return IngestJobResponse(
        job_id=job.id,
        document_id=doc.id,
        status="pending",
        message="Document queued for processing.",
    )


@router.post("/replace", response_model=IngestJobResponse)
async def replace_document(
    domain_id: UUID = Form(...),
    old_document_id: UUID = Form(...),
    title: str = Form(None),
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Hard delete the old document and all its chunks, then ingest the new file.
    Only call this after the user explicitly confirms they want to replace.

    Note: Qdrant vectors for the old document are NOT yet cleaned up here —
    that will be hooked in when we implement the Qdrant layer.
    """
    await require_domain_access(domain_id, "contributor", current_user, db)

    source_type = ALLOWED_CONTENT_TYPES.get(file.content_type)
    if not source_type:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}")

    file_bytes = await file.read()
    resolved_title = title or file.filename
    internal_user_id = await _resolve_user_id(current_user, db)
    repo = DocumentRepository(db)

    try:
        new_doc = await repo.replace(
            old_document_id=old_document_id,
            domain_id=domain_id,
            title=resolved_title,
            source_type=source_type,
            file_bytes=file_bytes,
            ingested_by=internal_user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    job = process_document.delay(
        document_id=str(new_doc.id),
        domain_id=str(domain_id),
        file_content=file_bytes,
        filename=file.filename,
    )

    return IngestJobResponse(
        job_id=job.id,
        document_id=new_doc.id,
        status="pending",
        message="Old document deleted. New version queued for processing.",
    )


@router.post("/web", response_model=IngestJobResponse)
async def ingest_web(
    domain_id: UUID = Form(...),
    seed_urls: list[str] = Form(...),
    max_depth: int = Form(2),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_domain_access(domain_id, "contributor", current_user, db)

    result = await db.execute(
        text("SELECT url_whitelist FROM rag.crawl_configs WHERE domain_id = :domain_id"),
        {"domain_id": str(domain_id)},
    )
    config = result.fetchone()
    if not config:
        raise HTTPException(status_code=404, detail="No crawl configuration found for this domain")

    for url in seed_urls:
        if not any(url.startswith(w) for w in config.url_whitelist):
            raise HTTPException(status_code=400, detail=f"URL {url} not in domain whitelist")

    job = process_web_crawl.delay(
        domain_id=str(domain_id),
        seed_urls=seed_urls,
        max_depth=max_depth,
    )

    return IngestJobResponse(
        job_id=job.id,
        status="pending",
        message="Web crawl queued.",
    )


@router.get("/status/{job_id}")
async def get_ingest_status(job_id: str):
    from app.workers.celery_app import celery_app
    result = celery_app.AsyncResult(job_id)
    return {"job_id": job_id, "status": result.status, "result": result.result}