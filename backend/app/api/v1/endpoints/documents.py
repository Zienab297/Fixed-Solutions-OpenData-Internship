"""
/documents endpoints — list, get, delete, and serve the original file
for preview/download. Ingestion (create/replace) lives in ingest.py;
this router covers read + delete of already-ingested documents.

Destination: app/api/v1/endpoints/documents.py
Remember to register this router alongside ingest.router, e.g. in
app/api/v1/api.py:

    from app.api.v1.endpoints import documents as documents_router
    api_router.include_router(documents_router.router)
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.v1.dependencies.auth import get_current_user, require_domain_access
from app.models.schemas.auth import CurrentUser
from app.models.db.models import Document
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import DocumentOut
from app.services.storage.file_storage import delete_document_file, resolve_full_path

router = APIRouter(prefix="/documents", tags=["Documents"])

_CONTENT_TYPE_BY_SOURCE_TYPE = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _to_document_out(doc: Document) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        domain_id=doc.domain_id,
        title=doc.title,
        source_type=doc.source_type,
        ingest_status=doc.ingest_status,
        ocr_used=doc.ocr_used,
        language=doc.language,
        has_file=bool(doc.file_path),
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    domain_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    require_domain_access(domain_id, "reader", current_user, db)
    repo = DocumentRepository(db)
    docs = await repo.list_by_domain(domain_id, limit=200)
    return [_to_document_out(doc) for doc in docs]


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    repo = DocumentRepository(db)
    doc = await repo.get(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    require_domain_access(doc.domain_id, "reader", current_user, db)
    return _to_document_out(doc)


@router.get("/{document_id}/file")
async def get_document_file(
    document_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    repo = DocumentRepository(db)
    doc = await repo.get(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    require_domain_access(doc.domain_id, "reader", current_user, db)

    if not doc.file_path:
        raise HTTPException(
            status_code=404,
            detail="Original file is not available for this document "
                    "(it was likely ingested before file storage was added).",
        )

    full_path = resolve_full_path(doc.file_path)
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")

    media_type = _CONTENT_TYPE_BY_SOURCE_TYPE.get(doc.source_type, "application/octet-stream")
    return FileResponse(path=full_path, media_type=media_type, filename=doc.title)


@router.delete("/{document_id}")
async def delete_document(
    document_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    repo = DocumentRepository(db)
    doc = await repo.get(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    require_domain_access(doc.domain_id, "contributor", current_user, db)

    file_path = await repo.delete(document_id)
    await db.commit()
    delete_document_file(file_path)

    return {"id": str(document_id), "deleted": True}        